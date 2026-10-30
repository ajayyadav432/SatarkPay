"""What is known about a payment at the moment it happens.

One class serves training and live scoring, so the two cannot drift apart. Features only read what has already
been observed: a payment is scored first and recorded after, so it can never see itself or the future.

    x = store.features_for(txn)     # read
    store.observe(txn)              # then record it
"""
from __future__ import annotations

import math
from collections import deque

from app.payments.context import link_signal, note_signal, sms_signal, vpa_signal
from app.payments.geo import km_between

HOUR = 3600.0
DAY = 86400.0
NAN = float("nan")
IST_OFFSET = 19800
AMOUNT_HISTORY = 60
SMS_WINDOW = 15 * 60.0
SMS_MEMORY = DAY
REPORT_WINDOW = 30 * DAY

PAYER = ["amount", "amt_vs_median", "amt_vs_max", "amt_to_balance", "hour_rarity", "is_night", "out_count_1h", "out_count_24h",
         "out_sum_1h", "out_sum_24h", "new_payee", "new_payees_1h", "new_device", "device_age_h", "device_accounts",
         "km_from_last", "kmph", "history_n", "payer_age_days", "kind_pay", "kind_qr", "kind_link", "kind_collect"]
MOVER = ["payer_in_count_24h", "payer_unique_in_24h", "payer_in_sum_24h", "forward_ratio", "payer_first_time_share"]
PAYEE = ["payee_known", "payee_age_days", "payee_is_merchant", "payee_verified", "payee_in_count_24h", "payee_unique_in_24h",
         "payee_first_time_share", "payee_in_sum_24h", "payee_out_sum_24h", "payee_passthrough", "payee_collects_24h",
         "payee_decline_share", "payee_reports_30d"]
CONTEXT = ["note_risk", "receive_lure", "link_risk", "link_official", "vpa_risk", "sms_risk_15m", "sms_mentions_payee"]

FEATURES = PAYER + MOVER + PAYEE + CONTEXT
FEATURE_INDEX = {n: i for i, n in enumerate(FEATURES)}

# The anomaly model sees behaviour only, and no labels. Words are read by other layers.
ANOMALY_FEATURES = ["amt_vs_median", "amt_vs_max", "hour_rarity", "out_count_1h", "out_sum_1h", "new_payees_1h", "device_accounts", "kmph",
                    "payer_unique_in_24h", "forward_ratio", "payer_first_time_share", "payee_age_days", "payee_unique_in_24h",
                    "payee_first_time_share", "payee_passthrough", "payee_decline_share", "payee_reports_30d"]


def hour_of(ts: float) -> int:
    return int(((ts + IST_OFFSET) % DAY) // HOUR)


class Account:
    """Everything remembered about one UPI ID, both as a payer and as a payee."""
    __slots__ = ("n_out", "amounts", "max_amount", "hour_counts", "payees", "devices", "last_ts", "last_city", "out", "out_sum",
                 "payers_ever", "in_", "in_sum", "in_unique", "in_first", "collects", "declines", "approved", "reports")

    def __init__(self):
        self.n_out = 0
        self.amounts = deque(maxlen=AMOUNT_HISTORY)
        self.max_amount = 0.0
        self.hour_counts = [0] * 24
        self.payees: dict[str, float] = {}
        self.devices: dict[str, float] = {}
        self.last_ts = None
        self.last_city = None
        self.out: deque = deque()         # (ts, amount, was a new payee), last 24 h
        self.out_sum = 0.0
        self.payers_ever: set[str] = set()
        self.in_: deque = deque()         # (ts, amount, payer, first time), last 24 h
        self.in_sum = 0.0
        self.in_unique: dict[str, int] = {}
        self.in_first = 0
        self.collects: deque = deque()    # timestamps, last 24 h
        self.declines: deque = deque()
        self.approved: deque = deque()
        self.reports: deque = deque()     # timestamps, last 30 days

    def prune(self, ts: float) -> None:
        cut = ts - DAY
        while self.out and self.out[0][0] < cut:
            self.out_sum -= self.out.popleft()[1]
        while self.in_ and self.in_[0][0] < cut:
            _, amount, payer, first = self.in_.popleft()
            self.in_sum -= amount
            self.in_first -= first
            left = self.in_unique[payer] - 1
            if left:
                self.in_unique[payer] = left
            else:
                del self.in_unique[payer]
        for q in (self.collects, self.declines, self.approved):
            while q and q[0] < cut:
                q.popleft()
        cut = ts - REPORT_WINDOW
        while self.reports and self.reports[0] < cut:
            self.reports.popleft()


def _median(values) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


class FeatureStore:
    def __init__(self, directory: dict | None = None):
        self.directory = directory if directory is not None else {}
        self.accounts: dict[str, Account] = {}
        self.device_accounts: dict[str, set] = {}
        self.sms: dict[str, deque] = {}
        self.pending_collects: dict[str, dict] = {}

    def _acct(self, vpa: str) -> Account:
        a = self.accounts.get(vpa)
        if a is None:
            a = self.accounts[vpa] = Account()
        return a

    # --- reading -----------------------------------------------------------------------

    def features_for(self, t: dict) -> dict:
        """Features of a payment, using only what happened before it."""
        ts, amount, kind = t["ts"], float(t["amount"]), t["kind"]
        payer, payee = t["payer"], t["payee"]
        p, q = self._acct(payer), self._acct(payee)
        p.prune(ts)
        q.prune(ts)
        h = t.get("hour")
        if h is None:
            h = hour_of(ts)
        hist = p.n_out
        cut_1h = ts - HOUR
        out_count_1h, out_sum_1h, new_1h = 0, 0.0, 0
        for when, amt, was_new in reversed(p.out):
            if when < cut_1h:
                break
            out_count_1h += 1
            out_sum_1h += amt
            new_1h += was_new

        device, city, balance = t.get("device"), t.get("city"), t.get("balance")
        known_device = device in p.devices
        if hist == 0 or device is None:
            new_device, device_age = NAN, NAN
        else:
            new_device = 0.0 if known_device else 1.0
            device_age = min(1440.0, (ts - p.devices[device]) / HOUR) if known_device else 0.0
        accounts_on_device = len(self.device_accounts.get(device, ())) + (0 if device is None or payer in self.device_accounts.get(device, ()) else 1)
        if p.last_city is None or city is None:
            km, kmph = NAN, NAN
        else:
            km = km_between(p.last_city, city)
            kmph = min(5000.0, km / max((ts - p.last_ts) / HOUR, 0.05))

        payer_dir = self.directory.get(payer)
        payee_dir = self.directory.get(payee)
        verified = bool(payee_dir and payee_dir.get("verified"))
        in_outcomes = len(q.declines) + len(q.approved)

        note = note_signal(t.get("note") or "")
        link = link_signal(t.get("link") or "")
        vpa_risk = 0 if verified else vpa_signal(payee)["score"]
        sms_risk, sms_mentions = self._sms_context(payer, payee, link["domain"], ts, self.one_off_sms(t))

        return {
            "amount": amount,
            "amt_vs_median": amount / max(_median(p.amounts), 1.0) if hist >= 3 else NAN,
            "amt_vs_max": amount / max(p.max_amount, 1.0) if hist >= 3 else NAN,
            "amt_to_balance": amount / max(balance, 1.0) if balance is not None else NAN,
            "hour_rarity": 1.0 - (p.hour_counts[h] + p.hour_counts[(h + 1) % 24] + p.hour_counts[h - 1]) / hist if hist >= 5 else NAN,
            "is_night": 1.0 if h < 6 else 0.0,
            "out_count_1h": out_count_1h,
            "out_count_24h": len(p.out),
            "out_sum_1h": out_sum_1h,
            "out_sum_24h": p.out_sum,
            "new_payee": 0.0 if payee in p.payees else 1.0,
            "new_payees_1h": new_1h,
            "new_device": new_device,
            "device_age_h": device_age,
            "device_accounts": accounts_on_device,
            "km_from_last": km,
            "kmph": kmph,
            "history_n": min(hist, 500),
            "payer_age_days": (ts - payer_dir["created"]) / DAY if payer_dir else NAN,
            "kind_pay": 1.0 if kind == "PAY" else 0.0,
            "kind_qr": 1.0 if kind == "QR" else 0.0,
            "kind_link": 1.0 if kind == "LINK" else 0.0,
            "kind_collect": 1.0 if kind == "COLLECT" else 0.0,

            "payer_in_count_24h": len(p.in_),
            "payer_unique_in_24h": len(p.in_unique),
            "payer_in_sum_24h": p.in_sum,
            "forward_ratio": min(2.0, amount / p.in_sum) if p.in_sum > 1 else NAN,
            "payer_first_time_share": p.in_first / len(p.in_) if p.in_ else NAN,

            "payee_known": 1.0 if payee_dir else 0.0,
            "payee_age_days": (ts - payee_dir["created"]) / DAY if payee_dir else NAN,
            "payee_is_merchant": 1.0 if payee_dir and payee_dir.get("merchant") else 0.0,
            "payee_verified": 1.0 if verified else 0.0,
            "payee_in_count_24h": len(q.in_),
            "payee_unique_in_24h": len(q.in_unique),
            "payee_first_time_share": q.in_first / len(q.in_) if q.in_ else NAN,
            "payee_in_sum_24h": q.in_sum,
            "payee_out_sum_24h": q.out_sum,
            "payee_passthrough": min(1.5, q.out_sum / q.in_sum) if q.in_sum > 1 else NAN,
            "payee_collects_24h": len(q.collects),
            "payee_decline_share": len(q.declines) / in_outcomes if in_outcomes >= 3 else NAN,
            "payee_reports_30d": len(q.reports),

            "note_risk": note["score"],
            "receive_lure": 1.0 if note["receive_lure"] else 0.0,
            "link_risk": link["score"],
            "link_official": 1.0 if link["official"] else 0.0,
            "vpa_risk": vpa_risk,
            "sms_risk_15m": sms_risk,
            "sms_mentions_payee": sms_mentions,
        }

    def one_off_sms(self, t: dict) -> tuple | None:
        """A message sent along with one payment. It counts for that payment only and is never remembered."""
        text = t.get("sms")
        if not text:
            return None
        sig = sms_signal(text, t.get("sms_sender") or "")
        return (t["ts"], sig["score"], sig["vpas"], sig["domains"])

    def _sms_context(self, payer: str, payee: str, domain: str | None, ts: float, extra: tuple | None = None) -> tuple[float, float]:
        box = self.sms.get(payer)
        while box and box[0][0] < ts - SMS_MEMORY:
            box.popleft()
        messages = list(box or ()) + ([extra] if extra else [])
        risk, mention = 0.0, 0.0
        payee_lower = payee.lower()
        for when, score, vpas, domains in reversed(messages):
            if when >= ts - SMS_WINDOW and score > risk:
                risk = float(score)
            # The risk of the very message that names this payee, not of some other message: a harmless SMS naming a
            # shop yesterday and an unrelated scam today must not add up to "a scam SMS named this shop".
            if score > mention and (payee_lower in vpas or (domain and domain in domains)):
                mention = float(score)
        return risk, mention

    def recent_sms(self, payer: str, payee: str, domain: str | None, ts: float, extra: tuple | None = None) -> dict | None:
        """The message behind the explanation: the riskiest one that names this payment, else the riskiest of the last 15 minutes."""
        named, latest = None, None
        payee_lower = payee.lower()
        for when, score, vpas, domains in reversed(list(self.sms.get(payer, ())) + ([extra] if extra else [])):
            if (payee_lower in vpas or (domain and domain in domains)) and (named is None or score > named[0]):
                named = (score, when)
            if when >= ts - SMS_WINDOW and (latest is None or score > latest[0]):
                latest = (score, when)
        best = named or latest
        return {"score": best[0], "minutes_ago": max(0, round((ts - best[1]) / 60))} if best else None

    # --- recording ---------------------------------------------------------------------

    def observe(self, ev: dict, moved: bool = True) -> None:
        """Record an event. moved=False: the payment was stopped, so nothing changes hands."""
        kind = ev["event"]
        if kind == "txn":
            if ev["kind"] == "COLLECT":
                self._acct(ev["payee"]).collects.append(ev["ts"])
                if moved:
                    self.pending_collects[ev["txn_id"]] = ev
            elif moved:
                self._record_payment(ev["payer"], ev["payee"], float(ev["amount"]), ev["ts"], ev.get("device"), ev.get("city"), ev.get("hour"))
        elif kind == "outcome":
            self._record_outcome(ev)
        elif kind == "report":
            self._acct(ev["payee"]).reports.append(ev["ts"])
        elif kind == "sms":
            self.record_sms(ev["user"], ev.get("text") or "", ev.get("sender") or "", ev["ts"])

    def record_sms(self, user: str, text: str, sender: str, ts: float) -> dict:
        sig = sms_signal(text, sender)
        self.sms.setdefault(user, deque(maxlen=50)).append((ts, sig["score"], sig["vpas"], sig["domains"]))
        return sig

    def _record_outcome(self, ev: dict) -> None:
        q = self._acct(ev["payee"])
        original = self.pending_collects.pop(ev["txn_id"], None)
        if ev["approved"]:
            q.approved.append(ev["ts"])
            o = original or {}
            self._record_payment(ev["payer"], ev["payee"], float(ev["amount"]), ev["ts"], o.get("device"), o.get("city"), o.get("hour"))
        else:
            q.declines.append(ev["ts"])

    def _record_payment(self, payer: str, payee: str, amount: float, ts: float, device, city, hour: int | None = None) -> None:
        p, q = self._acct(payer), self._acct(payee)
        p.prune(ts)
        q.prune(ts)
        p.n_out += 1
        p.amounts.append(amount)
        if amount > p.max_amount:
            p.max_amount = amount
        p.hour_counts[hour_of(ts) if hour is None else hour] += 1
        was_new = payee not in p.payees
        if was_new:
            p.payees[payee] = ts
        if device is not None:
            p.devices.setdefault(device, ts)
            self.device_accounts.setdefault(device, set()).add(payer)
        p.last_ts = ts
        if city is not None:
            p.last_city = city
        p.out.append((ts, amount, was_new))
        p.out_sum += amount
        first = payer not in q.payers_ever
        q.payers_ever.add(payer)
        q.in_.append((ts, amount, payer, first))
        q.in_sum += amount
        q.in_first += first
        q.in_unique[payer] = q.in_unique.get(payer, 0) + 1


def vector(features: dict) -> list[float]:
    return [float(features[n]) for n in FEATURES]


def is_missing(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)
