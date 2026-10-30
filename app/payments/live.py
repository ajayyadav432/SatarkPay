"""The running system: payments flow in, get scored, and the result goes out to the dashboard and the phones.

The Bus is the seam where Kafka would go. A producer publishes events, one consumer scores them in order. In production
this class would wrap a Kafka topic and nothing else would change. That has not been built or tested here: this laptop has
no Docker or Java, and the problem statement allows a simple stream simulator.
"""
from __future__ import annotations

import logging
import math
import queue
import secrets
import statistics
import threading
import time
from collections import Counter, deque
from datetime import datetime

from app import config
from app.payments import policy, store
from app.payments.features import FeatureStore
from app.payments.graph import MoneyGraph
from app.payments.scorer import Scorer
from ml.simulate import DAY, IST, PERSONA_SHOP, PERSONAS, START_TS, World, WorldConfig

ACCOUNT_AGE_IF_UNKNOWN_DAYS = 1.0

WARMUP_DAYS = 14
LIVE_USERS = 3000
DEFAULT_TPS = 25
ALLOWED_TPS = (5, 10, 25, 50, 100, 250, 500)
FEED_SIZE = 200
LATENCY_WINDOW = 1000
MAX_PENDING = 5000
CHANNEL_SIZE = 2000     # a slow screen loses its oldest updates instead of growing without limit

log = logging.getLogger("satarkpay")


class PaymentRefused(Exception):
    """The person asked to pay, and the decision does not allow it, or not yet."""


class Bus:
    """A topic with one consumer. publish() is what a Kafka producer's send() would be."""

    def __init__(self):
        self._q: queue.SimpleQueue = queue.SimpleQueue()

    def publish(self, ev: dict) -> None:
        self._q.put(ev)

    def poll(self) -> dict | None:
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None


class Channel:
    """One open dashboard or phone. Messages wait here until its connection picks them up."""

    def __init__(self):
        self.q: deque = deque(maxlen=CHANNEL_SIZE)

    def put(self, msg: dict) -> None:
        self.q.append(msg)

    def drain(self, limit: int = 400) -> list[dict]:
        out = []
        while self.q and len(out) < limit:
            try:
                out.append(self.q.popleft())
            except IndexError:
                break
        return out


def fresh_kpis() -> dict:
    return {"scored": 0, "alerts": 0, "stopped": 0, "by_action": Counter(), "by_likely": Counter(), "scams": 0, "scams_flagged": 0, "scams_stopped": 0,
            "scams_missed": 0, "genuine": 0, "false_alarms": 0, "genuine_stopped": 0, "rupees_stopped": 0.0, "rupees_recoverable": 0.0, "rupees_lost": 0.0, "phone_payments": 0}


class Live:
    def __init__(self, n_users: int | None = None, n_merchants: int | None = None, warmup_days: int = WARMUP_DAYS, seed: int = 2026):
        users = n_users or int(config.env("SATARKPAY_LIVE_USERS", str(LIVE_USERS)))
        merchants = n_merchants or max(60, users // 7)
        self.world = World(WorldConfig(seed=seed, days=1000, n_users=users, n_merchants=merchants))
        self.scorer = Scorer(FeatureStore(self.world.directory))
        self.bus = Bus()
        self.graph = MoneyGraph()
        self.world_lock = threading.RLock()
        self.clock = START_TS
        self.running = False
        self.stream_errors = 0
        self.reported_pairs: set[tuple[str, str]] = set()
        self.pauses = dict(policy.PAUSE_SECONDS)
        self.tps = DEFAULT_TPS
        self.kpis = fresh_kpis()
        self.latencies: deque = deque(maxlen=LATENCY_WINDOW)
        self.feed: deque = deque(maxlen=FEED_SIZE)
        self.attacks: list[dict] = []
        self.pending: dict[str, dict] = {}          # scored on request, waiting for the user's decision
        self.phone_inbox: dict[str, deque] = {}     # requests waiting for a phone to open
        self.dashboards: set[Channel] = set()
        self.phones: dict[str, set[Channel]] = {}
        self._rate_marks: deque = deque(maxlen=64)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._phone_txn = 0
        self._warm_up(warmup_days)

    # --- starting up -------------------------------------------------------------------

    def _warm_up(self, days: int) -> None:
        """Replays days of history without scoring, so users are known from the first payment."""
        until = START_TS + days * DAY
        while True:
            ev = self.world.next_event()
            if ev is None:
                break
            if ev["ts"] >= until:
                self.bus.publish(ev)    # already taken off the queue: it goes first when the stream starts
                break
            self.scorer.observe(ev)
            self.world.commit(ev)
            self.clock = ev["ts"]
        self.clock = max(self.clock, until - 1)

    def start_thread(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="satarkpay-stream", daemon=True)
            self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        next_tick = time.perf_counter()
        while not self._stop.is_set():
            if not self.running:
                time.sleep(0.05)
                next_tick = time.perf_counter()
                continue
            try:
                self.step()
            except Exception:       # one bad event must not silently end the stream while the screen still says Live
                self.stream_errors += 1
                log.exception("A stream event failed; carrying on")
                time.sleep(0.2)
            next_tick += 1.0 / self.tps
            delay = next_tick - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -1.0:      # fell behind: do not try to catch up in a burst
                next_tick = time.perf_counter()

    # --- the stream --------------------------------------------------------------------

    def step(self, count: int = 1) -> None:
        for _ in range(count):
            ev = self.bus.poll()
            if ev is None:
                with self.world_lock:
                    ev = self.world.next_event()
            if ev is None:
                return
            self.handle(ev)

    def handle(self, ev: dict) -> None:
        kind = ev["event"]
        self.clock = max(self.clock, ev["ts"])
        if kind == "txn":
            self._handle_txn(ev)
            return
        self.scorer.observe(ev)
        with self.world_lock:
            self.world.commit(ev)
        if kind == "outcome":       # the person answered a collect request: only now does money move, or not
            self._settle(ev, "moved" if ev["approved"] else "cancelled", count=False)
            self._tell_phones(ev, {"type": "settled", "txn_id": ev["txn_id"], "status": "moved" if ev["approved"] else "cancelled"})

    def _handle_txn(self, ev: dict) -> None:
        to_phone = ev["kind"] == "COLLECT" and ev.get("label") and ev["payer"] in self.phones
        result = self.scorer.score(ev)
        self.latencies.append(result["latency_ms"])
        if to_phone:
            self._send_to_phone(ev, result)
        goes_ahead = not result["stopped"] and not to_phone
        self.scorer.observe(ev, moved=goes_ahead)
        with self.world_lock:
            self.world.commit(ev, moved=goes_ahead)
        if to_phone or (goes_ahead and ev["kind"] == "COLLECT"):
            status = "pending"      # a request moves no money until the person answers it
        else:
            status = "moved" if goes_ahead else "stopped"
        self._after_scoring(ev, result, status, source="stream")

    def _send_to_phone(self, ev: dict, result: dict) -> None:
        """A scam request reaches a phone that is open: the person answers it, not the simulator."""
        txn = {k: ev.get(k) for k in ("txn_id", "payer", "payee", "amount", "kind", "note", "link", "device", "city", "balance", "label", "typology", "ts")}
        txn["event"] = "txn"
        self._remember(txn, result, counted=True)
        result = {**result, "txn_id": txn["txn_id"], "token": self.pending[txn["txn_id"]]["token"]}
        self.phone_inbox.setdefault(ev["payer"], deque(maxlen=5)).append({"txn": txn, "result": result})
        for ch in tuple(self.phones.get(ev["payer"], ())):
            ch.put({"type": "incoming", "txn": _public_txn(txn), "result": result})

    def _remember(self, txn: dict, result: dict, counted: bool = False) -> None:
        self.pending[txn["txn_id"]] = {"txn": txn, "result": result, "counted": counted, "scored_at": time.monotonic(), "token": secrets.token_urlsafe(16)}
        while len(self.pending) > MAX_PENDING:
            self.pending.pop(next(iter(self.pending)))

    def _settle(self, ev: dict, status: str, count: bool = True) -> None:
        """Where the money ended up. status: moved, stopped (by the system or by the person after an alert), cancelled, pending."""
        k, amount, label = self.kpis, float(ev["amount"]), ev.get("label")
        if label and status == "stopped":
            k["rupees_stopped"] += amount
            if ev.get("typology") == "mule_layering":
                k["rupees_recoverable"] += amount
        elif label and status == "moved":
            k["rupees_lost"] += amount
        self.graph.record(ev["payer"], ev["payee"], amount, status, ev["ts"], count=count)
        for a in self.attacks:
            if ev["payee"] in a["ring_set"] or ev["payer"] in a["ring_set"]:
                if status == "stopped":
                    a["rupees_stopped"] += amount
                elif status == "moved":
                    a["rupees_moved"] += amount

    def _after_scoring(self, ev: dict, result: dict, status: str, source: str) -> None:
        """Everything the result changes: numbers, feed, graph, stored alert, and who needs to be told."""
        k, amount, action = self.kpis, float(ev["amount"]), result["action"]
        label = ev.get("label")
        k["scored"] += 1
        k["by_action"][action] += 1
        flagged = action != "ALLOW"
        if flagged:
            k["alerts"] += 1
            if result.get("likely"):
                k["by_likely"][result["likely"]] += 1
        if result["stopped"]:
            k["stopped"] += 1
        if label is not None:       # ground truth exists only because this is a simulation; no model sees it
            if label:
                k["scams"] += 1
                k["scams_flagged"] += int(flagged)
                k["scams_stopped"] += int(result["stopped"])
                k["scams_missed"] += int(not flagged)
            else:
                k["genuine"] += 1
                k["false_alarms"] += int(flagged)
                k["genuine_stopped"] += int(result["stopped"])
        if flagged:
            self.graph.add_suspect(ev["payee"])
            if result.get("likely") == "forward":
                self.graph.add_suspect(ev["payer"])
        self._settle(ev, status)
        row = {"txn_id": ev["txn_id"], "ts": ev["ts"], "time": self.clock_label(ev["ts"]), "payer": ev["payer"], "payee": ev["payee"], "amount": amount, "kind": ev["kind"], "status": status,
               "score": result["score"], "level": result["level"], "action": action, "source": source, "truth": None if label is None else ("scam" if label else "genuine")}
        self.feed.append(row)
        msg = {"type": "txn", "row": row}
        if flagged:
            alert = {**row, "note": ev.get("note") or "", "link": ev.get("link"), "likely": result.get("likely"), "headline_en": result.get("headline_en"), "headline_hi": result.get("headline_hi"),
                     "reasons": result.get("reasons", []), "advice": result.get("advice", []), "shap": result.get("shap"), "model": result["model"], "rules": result["rules"], "values": result.get("values"),
                     "typology": ev.get("typology"), "status": "new"}
            alert["id"] = store.save_alert(alert)
            msg["alert"] = alert
        self._track_attacks(ev, result)
        for ch in tuple(self.dashboards):
            ch.put(msg)
        self._tell_phones(ev, msg)

    def _tell_phones(self, ev: dict, msg: dict) -> None:
        for vpa in (ev["payer"], ev["payee"]):
            for ch in tuple(self.phones.get(vpa, ())):
                ch.put(msg)

    def _track_attacks(self, ev: dict, result: dict) -> None:
        for a in self.attacks:
            if ev["payee"] in a["ring_set"] or ev["payer"] in a["ring_set"]:
                a["events"] += 1
                if result["action"] != "ALLOW":
                    a["flagged"] += 1
                    if a["first_caught_after"] is None:
                        a["first_caught_after"] = a["events"]
                if result["stopped"]:
                    a["stopped"] += 1

    # --- attacks -----------------------------------------------------------------------

    def launch(self, name: str) -> dict:
        from app.payments.scenarios import launch_attack
        with self.world_lock:
            info = launch_attack(self, name)
        ring = info.get("ring") or []
        attack = {"id": len(self.attacks) + 1, "name": name, "entry": info.get("entry"), "ring": ring, "ring_set": set(ring) | set(info.get("entries", [])), "events": 0, "flagged": 0, "stopped": 0,
                  "rupees_stopped": 0.0, "rupees_moved": 0.0, "first_caught_after": None, "started": self.clock}
        self.attacks.append(attack)
        self.attacks = self.attacks[-12:]
        return _public_attack(attack)

    # --- phone payments ----------------------------------------------------------------

    def new_txn_id(self) -> str:
        self._phone_txn += 1
        return f"P-{self._phone_txn}"

    def score_request(self, txn: dict, source: str = "api", explain_always: bool = False) -> dict:
        """A payment asked for by a person or an app. It waits for their decision: see decide()."""
        txn = {"event": "txn", "label": None, "typology": None, **txn}
        txn["ts"] = max(self.clock, txn.get("ts") or 0) + 1.0
        self.clock = txn["ts"]
        txn["txn_id"] = txn.get("txn_id") or self.new_txn_id()
        # The simulated clock races through the day. A real person is paying now, so "an unusual hour" means the real hour.
        txn["hour"] = datetime.now(IST).hour
        self._know_the_payee(txn)
        result = self.scorer.score(txn, explain_always=explain_always)
        self.latencies.append(result["latency_ms"])
        self._remember(txn, result)
        txn["source"] = source
        return {"txn": txn, "result": result}

    def _know_the_payee(self, txn: dict) -> None:
        """In production the bank or the network knows every account. In this small world a UPI ID typed by a judge does
        not exist yet, so it counts as just opened. Only a merchant-style account can send a collect request now."""
        self.world.directory.setdefault(txn["payee"], {"created": txn["ts"] - ACCOUNT_AGE_IF_UNKNOWN_DAYS * DAY, "merchant": txn["kind"] == "COLLECT", "verified": False, "category": "typed"})

    def token_ok(self, txn_id: str, token: str) -> bool:
        """Payment numbers are sequential, so only whoever was given the token can answer for a payment."""
        entry = self.pending.get(txn_id)
        return bool(entry) and secrets.compare_digest(entry["token"], token)

    def decide(self, txn_id: str, decision: str, source: str = "phone", skip_pause: bool = False) -> dict | None:
        """paid: the person went ahead. cancelled: they stopped. reported: they stopped and told us.
        The server enforces the decision: hiding a button on the phone would not stop anyone calling this directly."""
        entry = self.pending.get(txn_id)
        if entry is None:
            return None
        txn, result = entry["txn"], entry["result"]
        moved = decision == "paid"
        if moved and result["action"] == policy.BLOCK:
            raise PaymentRefused("This payment was blocked. Your bank can review it and release it.")
        if moved and not skip_pause:
            wait = self.pauses.get(result["action"], 0) - (time.monotonic() - entry["scored_at"])
            if wait > 0:
                raise PaymentRefused(f"Please wait {math.ceil(wait)} more seconds before continuing.")
        self.pending.pop(txn_id, None)
        self.clock += 1.0
        ts = self.clock
        if txn["kind"] == "COLLECT":
            outcome = {"event": "outcome", "ts": ts, "txn_id": txn_id, "payer": txn["payer"], "payee": txn["payee"], "amount": txn["amount"], "approved": moved,
                       "label": txn.get("label"), "typology": txn.get("typology")}
            if entry["counted"]:    # the request was seen when it arrived; the outcome needs its phone and place
                self.scorer.store.pending_collects[txn_id] = txn
            else:
                self.scorer.observe(txn, moved=True)
            self.scorer.observe(outcome)
            with self.world_lock:
                self.world.commit(outcome)
        else:
            self.scorer.observe(txn, moved=moved)
            with self.world_lock:
                self.world.commit(txn, moved=moved)
        if decision == "reported" and (txn["payer"], txn["payee"]) not in self.reported_pairs:     # one person counts once
            self.reported_pairs.add((txn["payer"], txn["payee"]))
            self.report(txn["payee"], ts)
        self.kpis["phone_payments"] += 1
        status = "moved" if moved else ("stopped" if result["action"] != policy.ALLOW else "cancelled")
        if entry["counted"]:        # a request that reached the phone was already counted when it arrived
            self._settle(txn, status, count=False)
            self._tell_phones(txn, {"type": "settled", "txn_id": txn_id, "status": status})
        else:
            self._after_scoring(txn, result, status, source=source)
        inbox = self.phone_inbox.get(txn["payer"])
        if inbox:
            remaining = [i for i in inbox if i["txn"]["txn_id"] != txn_id]
            inbox.clear()
            inbox.extend(remaining)
        return {"decision": decision, "moved": moved, "reports": self.reports_of(txn["payee"])}

    def report(self, payee: str, ts: float | None = None) -> None:
        self.scorer.observe({"event": "report", "ts": ts if ts is not None else self.clock, "payee": payee})

    def reports_of(self, vpa: str) -> int:
        a = self.scorer.store.accounts.get(vpa)
        return len(a.reports) if a else 0

    def record_sms(self, user: str, text: str, sender: str) -> dict:
        self.clock += 1.0
        return self.scorer.record_sms(user, text, sender, self.clock)

    # --- what the screens read ---------------------------------------------------------

    def clock_label(self, ts: float | None = None) -> str:
        t = ts if ts is not None else self.clock
        day = int((t - START_TS) // DAY) + 1
        return f"Day {day}, {datetime.fromtimestamp(t, IST).strftime('%H:%M')}"

    def snapshot(self) -> dict:
        k = self.kpis
        now = time.perf_counter()
        self._rate_marks.append((now, k["scored"]))
        rate = 0.0
        recent = [m for m in self._rate_marks if now - m[0] <= 5.0]
        if len(recent) >= 2 and recent[-1][0] > recent[0][0]:
            rate = (recent[-1][1] - recent[0][1]) / (recent[-1][0] - recent[0][0])
        lat = sorted(self.latencies)
        return {
            "clock": self.clock, "clock_label": self.clock_label(), "running": self.running, "tps_target": self.tps, "tps": round(rate, 1), "stream_errors": self.stream_errors,
            "latency_ms": {"p50": round(statistics.median(lat), 2) if lat else None, "p95": round(lat[int(len(lat) * 0.95)], 2) if len(lat) > 20 else None},
            "scored": k["scored"], "alerts": k["alerts"], "stopped": k["stopped"], "by_action": dict(k["by_action"]), "by_likely": dict(k["by_likely"]),
            "truth": {"scams": k["scams"], "flagged": k["scams_flagged"], "stopped": k["scams_stopped"], "missed": k["scams_missed"], "genuine": k["genuine"], "false_alarms": k["false_alarms"], "genuine_stopped": k["genuine_stopped"]},
            "rupees": {"stopped": round(k["rupees_stopped"]), "recoverable": round(k["rupees_recoverable"]), "lost": round(k["rupees_lost"])},
            "attacks": [_public_attack(a) for a in self.attacks[-6:]],
        }

    def subscribe_dashboard(self) -> Channel:
        ch = Channel()
        self.dashboards.add(ch)
        return ch

    def subscribe_phone(self, vpa: str) -> Channel:
        ch = Channel()
        self.phones.setdefault(vpa, set()).add(ch)
        return ch

    def unsubscribe(self, ch: Channel, vpa: str | None = None) -> None:
        self.dashboards.discard(ch)
        if vpa and vpa in self.phones:
            self.phones[vpa].discard(ch)
            if not self.phones[vpa]:
                del self.phones[vpa]

    def phone_is_open(self, vpa: str) -> bool:
        return bool(self.phones.get(vpa))

    def persona_list(self) -> list[dict]:
        out = []
        for key, p in PERSONAS.items():
            acct = self.scorer.store.accounts.get(p["vpa"])
            out.append({"key": key, "vpa": p["vpa"], "segment": p["segment"], "city": p["city"], "history": acct.n_out if acct else 0, "balance": round(self.world.balance.get(p["vpa"], 0.0))})
        return out

    def persona_shop(self) -> str:
        return PERSONA_SHOP


def _public_txn(txn: dict) -> dict:
    return {k: txn.get(k) for k in ("txn_id", "payer", "payee", "amount", "kind", "note", "link")}


def _public_attack(a: dict) -> dict:
    return {k: v for k, v in a.items() if k != "ring_set"}
