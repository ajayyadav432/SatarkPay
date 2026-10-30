"""FastAPI application: the scoring API, the live stream and the screens."""
from __future__ import annotations

import asyncio
import hmac
import io
import ipaddress
import json
import re
import socket
import time
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import quote, urlencode

import segno
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import config
from app.analysis.extract import normalise_url
from app.analysis.pipeline import analyze, analyze_url
from app.analysis.scoring import level_rank
from app.payments import models as pay_models
from app.payments import scenarios, store
from app.payments.geo import city_index
from app.payments.live import ALLOWED_TPS, Live, PaymentRefused
from ml.simulate import PERSONAS

VERSION = "1.0.0"
live: Live | None = None


def get_live() -> Live:
    global live
    if live is None:
        live = Live()
    return live


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    if not pay_models.ready():
        raise RuntimeError("Models not found in models/. Run: ./run.sh train")
    engine = get_live()
    engine.start_thread()
    if config.env("SATARKPAY_AUTOSTART", "1") == "1":
        engine.running = True
    yield
    engine.shutdown()


app = FastAPI(title=config.APP_NAME, version=VERSION, lifespan=lifespan, description=f"{config.APP_TAGLINE}. {config.PROBLEM_STATEMENT}. All data is simulated.",
              docs_url=None, redoc_url=None)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _host_allowed(host: str | None) -> bool:
    """localhost or an IP address. DNS rebinding needs a hostname, so refusing the rest closes it."""
    if not host:
        return False
    name = host.rsplit(":", 1)[0] if not host.endswith("]") and host.count(":") == 1 else host
    name = name.split("]")[0].lstrip("[")
    if name == "localhost":
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if not _host_allowed(request.headers.get("host")):
        return JSONResponse({"detail": "Open this app by localhost or its IP address."}, status_code=403)
    # Another website must not drive this app through a browser on the laptop. The reused browser extension is allowed.
    origin = request.headers.get("origin")
    if request.method in UNSAFE and origin and not origin.startswith("chrome-extension://") and origin.split("://", 1)[-1] != request.headers.get("host"):
        return JSONResponse({"detail": "Request from another website refused."}, status_code=403)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    path = request.url.path
    if path.startswith("/api/") or path in ("/", "/pay", "/merchant", "/how", "/go"):
        response.headers["Cache-Control"] = "no-store"
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def is_local(request: Request) -> bool:
    return bool(request.client) and request.client.host in config.LOOPBACK


def only_this_laptop(request: Request) -> None:
    """Judges can use the phone screen from their own phones, but only the presenter's laptop runs the show."""
    if not is_local(request):
        raise HTTPException(status_code=403, detail="This control only works on the laptop running the demo.")


# --- request bodies ------------------------------------------------------------------

_VPA = re.compile(r"^[\w.\-]{1,100}@[A-Za-z0-9.\-]{1,30}$")


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payer: str = Field(max_length=config.MAX_VPA_CHARS)
    payee: str = Field(max_length=config.MAX_VPA_CHARS)
    amount: float = Field(gt=0, le=10_000_000)
    kind: Literal["PAY", "QR", "LINK", "COLLECT"] = "PAY"
    device: str | None = Field(default=None, max_length=80)
    city: str | int | None = None
    note: str | None = Field(default=None, max_length=config.MAX_NOTE_CHARS)
    link: str | None = Field(default=None, max_length=config.MAX_URL_CHARS)
    balance: float | None = Field(default=None, ge=0)
    sms: str | None = Field(default=None, max_length=2000)      # a message received just before; counts for this payment only
    sms_sender: str | None = Field(default=None, max_length=config.MAX_SENDER_CHARS)
    record: bool = False
    explain: bool = False       # also explain a payment that was allowed (alerts are always explained)

    @field_validator("payer", "payee")
    @classmethod
    def looks_like_a_upi_id(cls, v: str) -> str:
        v = v.strip().lower()
        if not _VPA.match(v):
            raise ValueError("must look like a UPI ID, for example name@bank")
        return v

    @field_validator("note", "link", "device")
    @classmethod
    def blank_is_none(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v else None


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    txn_id: str = Field(max_length=64)
    token: str = Field(max_length=64)
    decision: Literal["paid", "cancelled", "reported"]


class SmsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: str = Field(max_length=config.MAX_VPA_CHARS)
    text: str = Field(min_length=1, max_length=2000)
    sender: str | None = Field(default=None, max_length=config.MAX_SENDER_CHARS)


class AlertUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["new", "confirmed_fraud", "false_alarm"]


class SpeedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tps: int


class IngestIn(BaseModel):
    """The exact request of the reused SatarkAI Android app and browser extension."""
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=config.MAX_TEXT_CHARS)
    channel: Literal["sms", "email", "social", "url"]
    sender: str | None = Field(default=None, max_length=config.MAX_SENDER_CHARS)
    source: Literal["sms-app", "gmail-web"]
    ref: str | None = Field(default=None, max_length=300)


class UrlsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[str] = Field(min_length=1, max_length=200)


# --- pages ---------------------------------------------------------------------------

def _page(name: str):
    return FileResponse(config.STATIC_DIR / name)


@app.get("/", include_in_schema=False)
def page_dashboard():
    return _page("dashboard.html")


@app.get("/pay", include_in_schema=False)
def page_pay():
    return _page("pay.html")


@app.get("/merchant", include_in_schema=False)
def page_merchant():
    return _page("merchant.html")


@app.get("/qr", include_in_schema=False)
def page_qr():
    return _page("qr.html")


@app.get("/how", include_in_schema=False)
def page_how():
    return _page("how.html")


@app.get("/go", include_in_schema=False)
def page_go():
    return _page("go.html")


# --- scoring -------------------------------------------------------------------------

def _txn_from(body: PaymentIn) -> dict:
    return {"payer": body.payer, "payee": body.payee, "amount": float(body.amount), "kind": body.kind, "device": body.device, "city": city_index(body.city),
            "note": body.note or "", "link": body.link, "balance": body.balance, "sms": body.sms, "sms_sender": body.sms_sender}


@app.post("/api/v1/score")
def api_score(body: PaymentIn, engine: Live = Depends(get_live)):
    """Score one payment before it goes through. By default nothing is recorded until /api/v1/outcome says what happened.
    With record=true the payment counts as done, unless it was stopped."""
    entry = engine.score_request(_txn_from(body), source="api", explain_always=body.explain)
    result, txn = entry["result"], entry["txn"]
    if body.record:     # an app that only wants it recorded: warned payments go ahead, stopped ones do not
        engine.decide(txn["txn_id"], "cancelled" if result["stopped"] else "paid", source="api", skip_pause=True)
    return {**result, "txn_id": txn["txn_id"], "token": engine.pending.get(txn["txn_id"], {}).get("token")}


@app.post("/api/v1/outcome")
def api_outcome(body: DecisionIn, engine: Live = Depends(get_live)):
    """What the person did after seeing the result. 'reported' also counts as a complaint against the payee.
    A blocked payment cannot be paid, and a warned or held one only after its pause."""
    if not engine.token_ok(body.txn_id, body.token):
        raise HTTPException(status_code=404, detail="Unknown or already decided payment.")
    try:
        done = engine.decide(body.txn_id, body.decision)
    except PaymentRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if done is None:
        raise HTTPException(status_code=404, detail="Unknown or already decided payment.")
    return done


@app.post("/api/v1/sms")
def api_sms(body: SmsIn, request: Request, engine: Live = Depends(get_live)):
    """A message this user just received. It stays in memory for a day and can raise the risk of a payment that follows.
    From another device the pairing code is required, as it changes how someone else's payments are scored."""
    if not is_local(request) and not _ingest_token_ok(request.headers.get("x-satark-token")):
        raise HTTPException(status_code=401, detail="Wrong or missing pairing code.")
    user = body.user.strip().lower()
    sig = engine.record_sms(user, body.text, body.sender or "")
    return {"score": sig["score"], "level": sig["level"], "category": sig["category"], "reasons": sig["reasons"]}


@app.get("/api/v1/graph")
def api_graph(vpa: str = Query(max_length=config.MAX_VPA_CHARS), engine: Live = Depends(get_live)):
    return engine.graph.around(vpa.strip().lower(), engine.world.directory, engine.reports_of)


# --- alerts --------------------------------------------------------------------------

@app.get("/api/v1/alerts")
def api_alerts(status: Literal["new", "confirmed_fraud", "false_alarm"] | None = None, limit: int = Query(default=50, ge=1, le=200)):
    return {"alerts": store.list_alerts(status, limit), "labelled": store.labelled_counts()}


@app.get("/api/v1/alerts/{alert_id}")
def api_alert(alert_id: int):
    alert = store.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    return alert


@app.patch("/api/v1/alerts/{alert_id}")
def api_alert_update(alert_id: int, body: AlertUpdate, _: None = Depends(only_this_laptop), engine: Live = Depends(get_live)):
    """An analyst's decision. These are the labels for the next training. A confirmed scam also counts as a report against the payee."""
    before = store.get_alert(alert_id)
    if before is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    alert = store.set_status(alert_id, body.status)
    if body.status == "confirmed_fraud" and before["status"] != "confirmed_fraud":
        engine.report(alert["payee"])
    return {**alert, "reports": engine.reports_of(alert["payee"])}


# --- the live stream -----------------------------------------------------------------

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _events(request: Request, channel, engine: Live, vpa: str | None = None):
    try:
        yield _sse({"type": "hello", "kpis": engine.snapshot()})
        last_kpis = 0.0
        while not await request.is_disconnected():
            batch = channel.drain()
            now = time.monotonic()
            kpis_due = now - last_kpis > 0.5
            if batch or kpis_due:
                yield _sse({"type": "batch", "items": batch, "kpis": engine.snapshot() if kpis_due else None})
                if kpis_due:
                    last_kpis = now
            await asyncio.sleep(0.25)
    finally:
        engine.unsubscribe(channel, vpa)


_SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


@app.get("/api/v1/stream")
async def api_stream(request: Request, engine: Live = Depends(get_live)):
    channel = engine.subscribe_dashboard()
    return StreamingResponse(_events(request, channel, engine), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/api/v1/stream/user/{vpa}")
async def api_stream_user(vpa: str, request: Request, engine: Live = Depends(get_live)):
    vpa = vpa.strip().lower()[: config.MAX_VPA_CHARS]
    channel = engine.subscribe_phone(vpa)
    for waiting in engine.phone_inbox.get(vpa, ()):     # requests that arrived before this phone connected
        from app.payments.live import _public_txn
        channel.put({"type": "incoming", "txn": _public_txn(waiting["txn"]), "result": waiting["result"]})
    return StreamingResponse(_events(request, channel, engine, vpa), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/api/v1/kpis")
def api_kpis(engine: Live = Depends(get_live)):
    return engine.snapshot()


@app.get("/api/v1/feed")
def api_feed(limit: int = Query(default=50, ge=1, le=200), engine: Live = Depends(get_live)):
    return {"rows": list(engine.feed)[-limit:]}


# --- running the show (laptop only) ---------------------------------------------------

@app.post("/api/v1/sim/start")
def api_sim_start(_: None = Depends(only_this_laptop), engine: Live = Depends(get_live)):
    engine.running = True
    return {"running": True}


@app.post("/api/v1/sim/stop")
def api_sim_stop(_: None = Depends(only_this_laptop), engine: Live = Depends(get_live)):
    engine.running = False
    return {"running": False}


@app.post("/api/v1/sim/speed")
def api_sim_speed(body: SpeedIn, _: None = Depends(only_this_laptop), engine: Live = Depends(get_live)):
    if body.tps not in ALLOWED_TPS:
        raise HTTPException(status_code=422, detail=f"Speed must be one of {ALLOWED_TPS}.")
    engine.tps = body.tps
    return {"tps": engine.tps}


@app.post("/api/v1/sim/attack/{name}")
def api_sim_attack(name: str, _: None = Depends(only_this_laptop), engine: Live = Depends(get_live)):
    if name not in scenarios.ATTACKS:
        raise HTTPException(status_code=404, detail="Unknown attack.")
    return engine.launch(name)


@app.get("/api/v1/demo")
def api_demo(persona: Literal["sunita", "rahul", "priya"] = "sunita", engine: Live = Depends(get_live)):
    """What the phone screen shows: who you are, ready-made payments and the attacks."""
    me = PERSONAS[persona]
    return {"persona": persona, "me": {**next(p for p in engine.persona_list() if p["key"] == persona), "device": engine.world.users[me["vpa"]].device},
            "personas": engine.persona_list(), "scenarios": scenarios.phone_scenarios(engine, persona), "attacks": scenarios.ATTACKS,
            "shop": engine.persona_shop(), "lan": _lan_address(), "local": None}


# --- the model card -------------------------------------------------------------------

@app.get("/api/v1/metrics")
def api_metrics():
    """Every number on the 'How it works' page. Written by the evaluation scripts, never typed by hand."""
    if not config.METRICS_FILE.exists():
        raise HTTPException(status_code=404, detail="No metrics yet. Run: ./run.sh evaluate")
    return json.loads(config.METRICS_FILE.read_text(encoding="utf-8"))


# --- joining from a phone -------------------------------------------------------------

def _lan_address() -> str | None:
    """This laptop's address on the Wi-Fi or hotspot. No traffic is sent."""
    if config.HOST in ("127.0.0.1", "localhost"):
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        return f"http://{ip}:{config.PORT}"
    except OSError:
        return None


# The QR codes on /qr: fake payment requests, for the phone app to scan.
DEMO_QR = {"shop": "Ramesh Kirana", "qr": "OLX Buyer", "fake_collect": "SBI Refund", "mule": "Job Deposit"}


def _demo_qr_text(engine: Live, name: str) -> str:
    sc = next((s for s in scenarios.phone_scenarios(engine, "sunita") if s["id"] == name), None)
    if sc is None:
        raise HTTPException(status_code=404, detail="No such demo QR code.")
    if name == "phishing":
        return sc["link"]
    return "upi://pay?" + urlencode({"pa": sc["payee"], "pn": DEMO_QR.get(name, ""), "am": f"{sc['amount']:.2f}", "tn": sc["note"], "cu": "INR"}, quote_via=quote)


@app.get("/api/v1/demo/qr/{name}.svg", include_in_schema=False)
def api_demo_qr(name: Literal["shop", "qr", "fake_collect", "mule", "phishing"], engine: Live = Depends(get_live)):
    buf = io.BytesIO()
    segno.make(_demo_qr_text(engine, name), error="m").save(buf, kind="svg", scale=8, border=4, dark="#000", light="#fff")
    return Response(buf.getvalue(), media_type="image/svg+xml")


@app.get("/api/v1/join")
def api_join():
    lan = _lan_address()
    return {"lan": lan, "pay_url": f"{lan}/pay" if lan else None}


@app.get("/api/v1/join.svg", include_in_schema=False)
def api_join_svg():
    lan = _lan_address()
    if not lan:
        raise HTTPException(status_code=404, detail="Start with ./run.sh wifi so that phones can join.")
    # A complete SVG file: an <img> cannot show the inline kind, which has no XML namespace.
    buf = io.BytesIO()
    segno.make(f"{lan}/pay", error="m").save(buf, kind="svg", scale=5, border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml")


# --- compatibility with the reused SatarkAI Android app and browser extension -----------

_seen_ingest: dict[str, dict] = {}
MAX_SEEN_INGEST = 2000


def _ingest_token_ok(given: str | None) -> bool:
    expected = config.env("SATARK_TOKEN")
    return bool(expected and given and hmac.compare_digest(expected.encode(), given.encode()))


@app.get("/api/health")
def health():
    return {"status": "ok", "app": config.APP_NAME, "version": VERSION, "models": pay_models.ready()}


@app.post("/api/ingest")
def api_ingest(body: IngestIn, request: Request, engine: Live = Depends(get_live)):
    """An SMS that arrived on the phone with SMS Guard. It is judged, and remembered as context for the phone's user.
    From another device the pairing code (header X-Satark-Token) is required."""
    if not is_local(request) and not _ingest_token_ok(request.headers.get("x-satark-token")):
        raise HTTPException(status_code=401, detail="Wrong or missing pairing code.")
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")
    key = f"{body.source}:{body.ref}" if body.ref else None
    if key and key in _seen_ingest:
        return {**_seen_ingest[key], "duplicate": True}
    r = analyze(body.text, channel=body.channel, sender=body.sender)
    for user in tuple(engine.phones) or (PERSONAS["sunita"]["vpa"],):   # the phone screen that is open, or the demo's main person
        engine.record_sms(user, body.text, body.sender or "")
    out = {"case_id": None, "source": body.source, "level": r["level"], "score": r["score"], "own_level": r["own_level"], "own_score": r["own_score"], "history_raised": False,
           "category": r.get("category"), "summary": r.get("summary"), "reasons": [f["title"] for f in r.get("factors", [])[:3]], "advice": (r.get("advice") or [])[:2],
           "sender": r.get("sender"), "channel": r.get("channel"), "sender_risky_count": 0, "block": None}
    if key:
        _seen_ingest[key] = out
        while len(_seen_ingest) > MAX_SEEN_INGEST:
            _seen_ingest.pop(next(iter(_seen_ingest)))
    return {**out, "duplicate": False}


@app.post("/api/check-urls")
def api_check_urls(body: UrlsIn):
    out = {}
    for u in dict.fromkeys(body.urls):
        if not u.lower().startswith(("http://", "https://")):
            continue
        r = analyze_url(normalise_url(u[: config.MAX_URL_CHARS].replace("\\", "/")), raw=u, lookup=False)
        out[u] = {"level": r["level"], "score": r["score"], "reason": r["factors"][0]["title"] if r.get("factors") else None,
                  "needs_warning": level_rank(r["level"]) >= level_rank(config.WARN_FROM_LEVEL)}
    return {"results": out}


@app.get("/api/check-url")
def api_check_url(u: str = Query(min_length=1, max_length=config.MAX_URL_CHARS), lookup: bool = False):
    url = normalise_url(u.replace("\\", "/"))     # browsers read a backslash as a slash: evil.com\@bank.com opens evil.com
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Only http and https links can be checked.")
    result = analyze_url(url, raw=u, lookup=lookup)
    result["needs_warning"] = level_rank(result["level"]) >= level_rank(config.WARN_FROM_LEVEL)
    return result


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return JSONResponse(status_code=404, content={"detail": getattr(exc, "detail", "Not found")})


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
