"""FastAPI application: the scoring API, the live stream and the screens."""
from __future__ import annotations

import asyncio
import csv
import hmac
import io
import ipaddress
import json
import os
import re
import socket
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import quote, urlencode

import segno
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import auth, config
from app.analysis.extract import normalise_url
from app.analysis.pipeline import analyze, analyze_url
from app.analysis.scoring import level_rank
from app.payments import i18n
from app.payments.sample_feed import SAMPLE_POSTS
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
    store.seed_samples(SAMPLE_POSTS)
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

IST = timezone(timedelta(hours=5, minutes=30))
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
    # A public deployment answers on its own address only. Vercel sets these; SATARK_PUBLIC_HOST covers anything else.
    if name in {os.environ.get(k) for k in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL", "SATARK_PUBLIC_HOST")} - {None}:
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
    # Another website must not drive this app through a browser on the laptop. The browser extension is allowed.
    origin = request.headers.get("origin")
    if request.method in UNSAFE and origin and not origin.startswith("chrome-extension://") and origin.split("://", 1)[-1] != request.headers.get("host"):
        return JSONResponse({"detail": "Request from another website refused."}, status_code=403)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    path = request.url.path
    if path.startswith("/api/") or path in ("/", "/pay", "/merchant", "/how", "/go", "/login", "/feed", "/history"):
        response.headers["Cache-Control"] = "no-store"
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def is_local(request: Request) -> bool:
    return bool(request.client) and request.client.host in config.LOOPBACK


ADMIN = Depends(auth.require("admin"))
ANYONE_LOGGED_IN = Depends(auth.require("user", "merchant", "admin"))


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "merchant", "admin"]
    username: str = Field(max_length=40)
    password: str = Field(max_length=200)


class SignUpIn(LoginIn):
    name: str = Field(max_length=60)


class TestLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "merchant", "admin"]


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
    """The exact request of the SatarkPay Android app and browser extension."""
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


def _gated(request: Request, name: str, *roles: str):
    """Not logged in: to the login page. Logged in with another role: to that role's own home."""
    role = auth.role_of(request)
    if role is None:
        return RedirectResponse("/login", status_code=303)
    if role not in roles:
        return RedirectResponse(auth.ACCOUNTS[role]["home"], status_code=303)
    return _page(name)


@app.get("/login", include_in_schema=False)
def page_login(request: Request):
    role = auth.role_of(request)
    return RedirectResponse(auth.ACCOUNTS[role]["home"], status_code=303) if role else _page("login.html")


@app.get("/", include_in_schema=False)
def page_dashboard(request: Request):
    return _gated(request, "dashboard.html", "admin")


@app.get("/pay", include_in_schema=False)
def page_pay(request: Request):
    return _gated(request, "pay.html", "user", "admin")


@app.get("/merchant", include_in_schema=False)
def page_merchant(request: Request):
    return _gated(request, "merchant.html", "merchant", "admin")


@app.get("/qr", include_in_schema=False)
def page_qr():
    return _page("qr.html")


@app.get("/how", include_in_schema=False)
def page_how():
    return _page("how.html")


@app.get("/go", include_in_schema=False)
def page_go():
    return _page("go.html")


# --- the community: reports, blocks, the feed ----------------------------------------

REPORTS_TO_WARN = 3         # reports from this many different accounts make a warning. Only an admin can block.
SIMULATED_ID = re.compile(r"@sim[a-z]*$")
_ID_IN_TEXT = re.compile(r"[\w.\-]+@[a-zA-Z][a-zA-Z0-9.\-]*")
_PHONE_IN_TEXT = re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?\d{10}(?!\d)")
FEED_CATEGORIES = ("Fake collect", "QR scam", "Phishing link", "Job or prize", "Digital arrest", "Mule account", "Other")


def mask_vpa(vpa: str) -> str:
    """A public report is an accusation nobody has checked, so a real UPI ID is never shown in full. Simulated ones are made up."""
    if not vpa or SIMULATED_ID.search(vpa):
        return vpa
    name, _, handle = vpa.partition("@")
    return f"{name[:2]}***@{handle}"


def _mask_text(text: str) -> str:
    text = _ID_IN_TEXT.sub(lambda m: mask_vpa(m.group(0).lower()), text)
    return _PHONE_IN_TEXT.sub(lambda m: m.group(0)[:2] + "********", text)


def _reporter(request: Request) -> str:
    session = auth.session_of(request)
    return f"{session['r']}:{session['u']}"


def apply_reputation(result: dict, payee: str) -> None:
    """What people and analysts have said about this UPI ID. Changes the result in place, so that /outcome enforces it too."""
    block = store.get_block(payee)
    count = store.report_count(payee)
    result["reports"] = count
    result["blocked"] = bool(block)
    if block:
        result.update(action="BLOCK", stopped=True, alert=True, score=max(result["score"], 90), level="Critical",
                      headline_en="Stopped. An analyst has blocked this UPI ID", headline_hi="रोक दिया गया। एक विश्लेषक ने इस UPI ID को ब्लॉक किया है")
        result["reasons"].insert(0, {"id": "blocked", "source": "community", "text_en": "An analyst reviewed the reports about this UPI ID and blocked it",
                                     "text_hi": "एक विश्लेषक ने इस UPI ID की शिकायतों की जाँच करके इसे ब्लॉक किया"})
    elif count >= REPORTS_TO_WARN:
        if result["action"] == "ALLOW":
            result.update(action="WARN", headline_en="Check before you pay. People have reported this UPI ID", headline_hi="भुगतान से पहले जाँच लें। लोगों ने इस UPI ID की शिकायत की है")
        result["reasons"].insert(0, {"id": "community_reports", "source": "community", "text_en": f"{count} accounts have reported this UPI ID. Reports are not verified",
                                     "text_hi": f"{count} खातों ने इस UPI ID की शिकायत की है। शिकायतों की जाँच नहीं हुई है"})


def scan_stages(result: dict, txn: dict) -> list[dict]:
    """The steps of a check and what each one really found, for the step-by-step view. The check has already finished."""
    ids = {r.get("id") for r in result.get("reasons", [])}
    rules = set(result.get("rules", []))
    model = result.get("model", {})
    return [{"id": "details", "warn": False},
            {"id": "upi_id", "warn": bool(ids & {"fake_vpa", "blocked", "community_reports", "reports"} or "fake_vpa" in rules or result.get("blocked"))},
            {"id": "words", "warn": bool(ids & {"note", "link", "sms"} or rules & {"receive_lure", "scam_link", "scam_sms_link"})},
            {"id": "behaviour", "warn": bool(ids & {"amount_unusual", "drains_balance", "burst", "new_device", "jump", "forwarding", "odd_hour"})},
            {"id": "models", "warn": bool(model.get("layers_agreeing"))},
            {"id": "decision", "warn": result["action"] != "ALLOW"}]


def _feed_view(post: dict, votes: dict[int, int]) -> dict:
    return {"id": post["id"], "created": post["created"], "author": post["author_name"], "sample": post["author"].startswith("sample:"), "payee": mask_vpa(post["payee"]), "category": post["category"], "body": _mask_text(post["body"]),
            "votes": int(post["votes"]), "comments": int(post["comments"]), "my_vote": votes.get(post["id"], 0), "reports": store.report_count(post["payee"]) if post["payee"] else 0,
            "blocked": bool(store.get_block(post["payee"])) if post["payee"] else False}


class PostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payee: str = Field(default="", max_length=config.MAX_VPA_CHARS)
    category: Literal[FEED_CATEGORIES]
    body: str = Field(min_length=10, max_length=1000)


class VoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Literal[-1, 0, 1]


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=500)


class BlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payee: str = Field(max_length=config.MAX_VPA_CHARS)
    reason: str = Field(min_length=3, max_length=300)


def _clean_vpa(v: str) -> str:
    v = v.strip().lower()
    if v and not _VPA.match(v):
        raise HTTPException(status_code=422, detail="That does not look like a UPI ID. Example: name@bank")
    return v


@app.get("/feed", include_in_schema=False)
def page_feed():
    return _page("feed.html")


@app.get("/history", include_in_schema=False)
def page_history(request: Request):
    return _gated(request, "history.html", "user", "merchant", "admin")


@app.get("/api/v1/posts")
def api_feed_list(request: Request, sort: Literal["new", "top"] = "new", limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    """Anyone can read the feed. Real UPI IDs and phone numbers are masked."""
    session = auth.session_of(request)
    votes = store.my_votes(f"{session['r']}:{session['u']}") if session else {}
    return {"posts": [_feed_view(p, votes) for p in store.list_posts(sort, limit, offset)], "categories": FEED_CATEGORIES}


@app.post("/api/v1/posts")
def api_feed_post(body: PostIn, request: Request, _: str = ANYONE_LOGGED_IN):
    """A post that names a UPI ID also counts as one report against it."""
    session = auth.session_of(request)
    payee = _clean_vpa(body.payee)
    who = _reporter(request)
    post_id = store.add_post(who, session["n"], payee, body.category, body.body.strip())
    if payee:
        store.add_report(payee, who)
    return _feed_view(store.get_post(post_id), {})


@app.post("/api/v1/posts/{post_id}/vote")
def api_feed_vote(post_id: int, body: VoteIn, request: Request, _: str = ANYONE_LOGGED_IN):
    if store.get_post(post_id) is None:
        raise HTTPException(status_code=404, detail="Post not found.")
    who = _reporter(request)
    store.vote(post_id, who, body.value)
    return _feed_view(store.get_post(post_id), store.my_votes(who))


@app.get("/api/v1/posts/{post_id}/comments")
def api_feed_comments(post_id: int):
    return {"comments": [{"id": c["id"], "created": c["created"], "author": c["author_name"], "body": _mask_text(c["body"])} for c in store.list_comments(post_id)]}


@app.post("/api/v1/posts/{post_id}/comments")
def api_feed_comment(post_id: int, body: CommentIn, request: Request, _: str = ANYONE_LOGGED_IN):
    if store.get_post(post_id) is None:
        raise HTTPException(status_code=404, detail="Post not found.")
    session = auth.session_of(request)
    store.add_comment(post_id, _reporter(request), session["n"], body.body.strip())
    return api_feed_comments(post_id)


@app.delete("/api/v1/posts/{post_id}")
def api_feed_hide(post_id: int, _: str = ADMIN):
    if not store.hide_post(post_id):
        raise HTTPException(status_code=404, detail="Post not found.")
    return {"hidden": True}


@app.get("/api/v1/reputation")
def api_reputation(vpa: str = Query(max_length=config.MAX_VPA_CHARS), _: str = ANYONE_LOGGED_IN):
    payee = _clean_vpa(vpa)
    return {"payee": mask_vpa(payee), "reports": store.report_count(payee), "blocked": bool(store.get_block(payee))}


@app.get("/api/v1/blocks")
def api_blocks(request: Request, _: str = ADMIN):
    blocks, reported = store.list_blocks(), store.most_reported()
    if auth.session_of(request).get("t"):     # a public test login sees only made-up IDs, as those are all it can act on
        blocks = [b for b in blocks if SIMULATED_ID.search(b["payee"])]
        reported = [r for r in reported if SIMULATED_ID.search(r["payee"])]
    return {"blocks": blocks, "most_reported": reported}


@app.post("/api/v1/blocks")
def api_block(body: BlockIn, request: Request, _: str = ADMIN):
    """Only an admin can block, so that a group of people cannot get an honest shop blocked. A public test login reaches simulated IDs only."""
    payee = _clean_vpa(body.payee)
    if not payee:
        raise HTTPException(status_code=422, detail="Enter a UPI ID.")
    session = auth.session_of(request)
    if session.get("t") and not SIMULATED_ID.search(payee):
        raise HTTPException(status_code=403, detail="A test login can only block simulated UPI IDs.")
    store.set_block(payee, session["u"], body.reason.strip())
    return {"blocked": payee}


@app.delete("/api/v1/blocks/{payee}")
def api_unblock(payee: str, request: Request, _: str = ADMIN):
    payee = _clean_vpa(payee)
    if auth.session_of(request).get("t") and not SIMULATED_ID.search(payee):
        raise HTTPException(status_code=403, detail="A test login can only unblock simulated UPI IDs.")
    if not store.remove_block(payee):
        raise HTTPException(status_code=404, detail="That UPI ID is not blocked.")
    return {"blocked": False}


# --- history and export ----------------------------------------------------------------

EXPORT_FIELDS = ("created", "kind", "subject", "amount", "note", "score", "level", "action", "outcome", "summary")
HISTORY_KINDS = {"payment": ("PAY", "QR", "LINK", "COLLECT", "SIMULATED"), "sms": ("SMS",), "email": ("EMAIL",), "link": ("LINK CHECK",), "social": ("SOCIAL",)}
HistoryKind = Literal["", "payment", "sms", "email", "link", "social"]
DEMO_USERS = {account["username"] for account in auth.ACCOUNTS.values()}


def _simulated_rows(session: dict, everyone: bool, engine: Live, q: str, action: str, kind: str, seen: set[str]) -> list[dict]:
    """Past payments from the simulation, kept in memory, for the demo accounts. They have no real date, only the simulation's clock."""
    if session["u"] not in DEMO_USERS or kind not in ("", "payment"):
        return []
    if everyone:
        rows = list(engine.feed)
    elif session["r"] == "merchant":
        rows = list(engine.shop_rows)
    elif session["r"] == "user":
        rows = [r for r in engine.feed if r["payer"] in _persona_vpas()]
    else:
        return []
    out = []
    needle, digits = q.lower(), re.sub(r"[\s+()-]", "", q)
    for r in reversed(rows):
        if r["txn_id"] in seen or (action and r["action"] != action):
            continue
        fields = f"{r['payee']} {r['payer']} {round(r['amount'])}".lower()
        if needle and needle not in fields and not (digits.isdigit() and digits[-10:] in fields):
            continue
        out.append({"created": 0, "when": "Simulation " + r["time"], "kind": "SIMULATED", "subject": r["payee"], "amount": r["amount"], "note": "From " + r["payer"],
                    "score": r["score"], "level": r["level"], "action": r["action"], "outcome": r["status"], "summary": "", "txn_id": r["txn_id"]})
    return out


def _history_rows(request: Request, q: str, action: str, limit: int, everyone: bool, kind: str = "") -> list[dict]:
    session = auth.session_of(request)
    if everyone and (session["r"] != "admin" or session.get("t")):     # a public test login must not read what others checked
        raise HTTPException(status_code=403, detail="This account cannot do that.")
    # This laptop's own phone and extension: shown on the laptop or to a real login, never to a test login over Wi-Fi.
    device = session["u"] in DEMO_USERS and (is_local(request) or not session.get("t"))
    rows = store.list_checks(None if everyone else _history_owner(session), None if everyone else session["r"], q.strip(), action, limit, HISTORY_KINDS.get(kind, ()), device)
    for row in rows:
        row["when"] = datetime.fromtimestamp(row["created"], IST).strftime("%Y-%m-%d %H:%M")
    seen = {r["txn_id"] for r in rows}
    return (rows + _simulated_rows(session, everyone, get_live(), q.strip(), action, kind, seen))[:limit]


def _csv_safe(value) -> str:
    """A spreadsheet runs a cell that starts with = + - or @ as a formula, and notes come from strangers."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@app.get("/api/v1/history")
def api_history(request: Request, q: str = Query(default="", max_length=100), action: Literal["", "ALLOW", "WARN", "HOLD", "BLOCK"] = "", limit: int = Query(default=500, ge=1, le=5000),
                everyone: bool = False, kind: HistoryKind = "", _: str = ANYONE_LOGGED_IN):
    return {"checks": _history_rows(request, q, action, limit, everyone, kind)}


@app.delete("/api/v1/history")
def api_history_clear(request: Request, _: str = ANYONE_LOGGED_IN):
    session = auth.session_of(request)
    store.clear_checks(_history_owner(session), session["r"])
    return {"cleared": True}


@app.get("/api/v1/history/export.{fmt}")
def api_history_export(fmt: Literal["csv", "json"], request: Request, q: str = Query(default="", max_length=100), action: Literal["", "ALLOW", "WARN", "HOLD", "BLOCK"] = "",
                       everyone: bool = False, kind: HistoryKind = "", _: str = ANYONE_LOGGED_IN):
    rows = _history_rows(request, q, action, 5000, everyone, kind)
    fields = ("when", *EXPORT_FIELDS[1:])
    name = f"satarkpay-history.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if fmt == "json":
        return Response(json.dumps([{k: r[k] for k in fields} for r in rows], ensure_ascii=False, indent=1), media_type="application/json", headers=headers)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields)
    writer.writerows([_csv_safe(r[k]) for k in fields] for r in rows)
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)     # the mark lets Excel read Hindi and rupee signs


def _history_owner(session: dict) -> str:
    """Each test login has its own history. Strangers share the test account, and what they check is theirs."""
    return f'{session["u"]}~{session["i"]}' if session.get("i") else session["u"]


def _log_check(request: Request, kind: str, subject: str, amount, note: str, score: int, level: str, action: str, summary: str, txn_id: str = "") -> None:
    session = auth.session_of(request)
    if session:
        store.add_check(_history_owner(session), session["r"], kind, subject, amount, note, score, level, action, summary, txn_id)
    elif not config.ON_VERCEL and not store.is_shared():     # the laptop's own phone or extension, which has no login
        store.add_check(store.DEVICE, "device", kind, subject, amount, note, score, level, action, summary, txn_id)


# --- login ---------------------------------------------------------------------------

def _home(role: str, token: str, request: Request, response: Response) -> dict:
    """A browser gets a cookie that scripts cannot read. The phone app sends the returned token as a Bearer header."""
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_SECONDS, httponly=True, samesite="strict", secure=secure, path="/")
    session = auth._read(token)
    return {"role": role, "username": session["u"], "name": session["n"], "home": auth.ACCOUNTS[role]["home"], "token": token}


@app.post("/api/v1/auth/login")
def api_login(body: LoginIn, request: Request, response: Response):
    return _home(body.role, auth.login(body.role, body.username, body.password), request, response)


@app.post("/api/v1/auth/signup")
def api_signup(body: SignUpIn, request: Request, response: Response):
    return _home(body.role, auth.sign_up(body.role, body.username, body.password, body.name), request, response)


@app.post("/api/v1/auth/test-login")
def api_test_login(body: TestLoginIn, request: Request, response: Response):
    return _home(body.role, auth.test_login(body.role), request, response)


@app.get("/api/v1/auth/options")
def api_auth_options():
    return {"test_logins": auth.test_logins_on(), "sign_up_roles": list(auth.SIGN_UP_ROLES)}


@app.post("/api/v1/auth/logout")
def api_logout(request: Request, response: Response):
    auth.logout(auth.token_of(request))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/v1/auth/me")
def api_me(request: Request, role: str = ANYONE_LOGGED_IN):
    session = auth.session_of(request)
    return {"role": role, "username": session["u"], "name": session["n"], "home": auth.ACCOUNTS[role]["home"], "test": bool(session.get("t"))}


def _persona_vpas() -> set[str]:
    return {p["vpa"] for p in PERSONAS.values()}


# --- scoring -------------------------------------------------------------------------

def _txn_from(body: PaymentIn) -> dict:
    return {"payer": body.payer, "payee": body.payee, "amount": float(body.amount), "kind": body.kind, "device": body.device, "city": city_index(body.city),
            "note": body.note or "", "link": body.link, "balance": body.balance, "sms": body.sms, "sms_sender": body.sms_sender}


@app.post("/api/v1/score")
def api_score(body: PaymentIn, request: Request, role: str = ANYONE_LOGGED_IN, engine: Live = Depends(get_live)):
    """Score one payment before it goes through. By default nothing is recorded until /api/v1/outcome says what happened.
    With record=true the payment counts as done, unless it was stopped.
    A user pays only from a demo person's account. A merchant can only bring in payments to its own shop."""
    if role == "user" and body.payer not in _persona_vpas():
        raise HTTPException(status_code=403, detail="This account can only pay from its own UPI ID.")
    if role == "merchant" and body.payee != engine.persona_shop():
        raise HTTPException(status_code=403, detail="This account can only receive payments to its own shop.")
    entry = engine.score_request(_txn_from(body), source="api", explain_always=body.explain)
    result, txn = entry["result"], entry["txn"]
    apply_reputation(result, body.payee)
    i18n.localise(result)
    result["stages"] = scan_stages(result, txn)
    _log_check(request, body.kind, body.payee, body.amount, body.note or "", result["score"], result["level"], result["action"], result["headline_en"], txn["txn_id"])
    if body.record:     # an app that only wants it recorded: warned payments go ahead, stopped ones do not
        engine.decide(txn["txn_id"], "cancelled" if result["stopped"] else "paid", source="api", skip_pause=True)
    return {**result, "txn_id": txn["txn_id"], "token": engine.pending.get(txn["txn_id"], {}).get("token")}


@app.post("/api/v1/outcome")
def api_outcome(body: DecisionIn, request: Request, _: str = ANYONE_LOGGED_IN, engine: Live = Depends(get_live)):
    """What the person did after seeing the result. 'reported' also counts as a complaint against the payee.
    A blocked payment cannot be paid, and a warned or held one only after its pause."""
    if not engine.token_ok(body.txn_id, body.token):
        raise HTTPException(status_code=404, detail="Unknown or already decided payment.")
    payee = engine.pending[body.txn_id]["txn"]["payee"]
    try:
        done = engine.decide(body.txn_id, body.decision)
    except PaymentRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if done is None:
        raise HTTPException(status_code=404, detail="Unknown or already decided payment.")
    if body.decision == "reported":
        store.add_report(payee, _reporter(request))
    store.set_check_outcome(body.txn_id, body.decision)
    return done


@app.post("/api/v1/sms")
def api_sms(body: SmsIn, request: Request, engine: Live = Depends(get_live)):
    """A message this user just received. It stays in memory for a day and can raise the risk of a payment that follows.
    From another device the pairing code is required, as it changes how someone else's payments are scored."""
    if not auth.role_of(request) and not is_local(request) and not _ingest_token_ok(request.headers.get("x-satark-token")):
        raise HTTPException(status_code=401, detail="Wrong or missing pairing code.")
    user = body.user.strip().lower()
    sig = engine.record_sms(user, body.text, body.sender or "")
    return {"score": sig["score"], "level": sig["level"], "category": sig["category"], "reasons": sig["reasons"]}


@app.get("/api/v1/graph")
def api_graph(vpa: str = Query(max_length=config.MAX_VPA_CHARS), _: str = ADMIN, engine: Live = Depends(get_live)):
    return engine.graph.around(vpa.strip().lower(), engine.world.directory, engine.reports_of)


# --- alerts --------------------------------------------------------------------------

@app.get("/api/v1/alerts")
def api_alerts(_: str = ADMIN, status: Literal["new", "confirmed_fraud", "false_alarm"] | None = None, limit: int = Query(default=50, ge=1, le=200)):
    return {"alerts": store.list_alerts(status, limit), "labelled": store.labelled_counts()}


@app.get("/api/v1/alerts/{alert_id}")
def api_alert(alert_id: int, _: str = ADMIN):
    alert = store.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    return alert


@app.patch("/api/v1/alerts/{alert_id}")
@app.post("/api/v1/alerts/{alert_id}")     # Android's HTTP client has no PATCH
def api_alert_update(alert_id: int, body: AlertUpdate, _: str = ADMIN, engine: Live = Depends(get_live)):
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
async def api_stream(request: Request, _: str = ADMIN, engine: Live = Depends(get_live)):
    channel = engine.subscribe_dashboard()
    return StreamingResponse(_events(request, channel, engine), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/api/v1/stream/user/{vpa}")
async def api_stream_user(vpa: str, request: Request, role: str = ANYONE_LOGGED_IN, engine: Live = Depends(get_live)):
    vpa = vpa.strip().lower()[: config.MAX_VPA_CHARS]
    if (role == "user" and vpa not in _persona_vpas()) or (role == "merchant" and vpa != engine.persona_shop()):
        raise HTTPException(status_code=403, detail="This account can only see its own payments.")
    channel = engine.subscribe_phone(vpa)
    for waiting in engine.phone_inbox.get(vpa, ()):     # requests that arrived before this phone connected
        from app.payments.live import _public_txn
        channel.put({"type": "incoming", "txn": _public_txn(waiting["txn"]), "result": waiting["result"]})
    return StreamingResponse(_events(request, channel, engine, vpa), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/api/v1/kpis")
def api_kpis(_: str = ADMIN, engine: Live = Depends(get_live)):
    return engine.snapshot()


@app.get("/api/v1/feed")
def api_feed(limit: int = Query(default=50, ge=1, le=200), _: str = ADMIN, engine: Live = Depends(get_live)):
    return {"rows": list(engine.feed)[-limit:]}


@app.get("/api/v1/merchant/payments")
def api_merchant_payments(request: Request, _: str = Depends(auth.require("merchant", "admin")), engine: Live = Depends(get_live)):
    """The shop's own payments, newest first. What really arrived is what counts, not a customer's screen."""
    totals = engine.shop_totals
    session = auth.session_of(request)
    name = session["n"] if session["r"] == "merchant" else auth.ACCOUNTS["merchant"]["name"]
    return {"shop": engine.persona_shop(), "name": name, "received_total": round(totals["received_total"], 2), "received": totals["received"],
            "not_received": totals["not_received"], "rows": [{k: r[k] for k in ("txn_id", "time", "payer", "amount", "status", "action")} for r in reversed(list(engine.shop_rows)[-50:])]}


# --- running the show (laptop only) ---------------------------------------------------

@app.post("/api/v1/sim/start")
def api_sim_start(_: str = ADMIN, engine: Live = Depends(get_live)):
    engine.running = True
    return {"running": True}


@app.post("/api/v1/sim/stop")
def api_sim_stop(_: str = ADMIN, engine: Live = Depends(get_live)):
    engine.running = False
    return {"running": False}


@app.post("/api/v1/sim/speed")
def api_sim_speed(body: SpeedIn, _: str = ADMIN, engine: Live = Depends(get_live)):
    if body.tps not in ALLOWED_TPS:
        raise HTTPException(status_code=422, detail=f"Speed must be one of {ALLOWED_TPS}.")
    engine.tps = body.tps
    return {"tps": engine.tps}


@app.post("/api/v1/sim/attack/{name}")
def api_sim_attack(name: str, _: str = ADMIN, engine: Live = Depends(get_live)):
    if name not in scenarios.ATTACKS:
        raise HTTPException(status_code=404, detail="Unknown attack.")
    return engine.launch(name)


@app.get("/api/v1/demo")
def api_demo(persona: Literal["sunita", "rahul", "priya"] = "sunita", _: str = ANYONE_LOGGED_IN, engine: Live = Depends(get_live)):
    """What the phone screen shows: who you are, ready-made payments and the attacks."""
    me = PERSONAS[persona]
    return {"persona": persona, "me": {**next(p for p in engine.persona_list() if p["key"] == persona), "device": engine.world.users[me["vpa"]].device},
            "personas": engine.persona_list(), "scenarios": [{**sc, **{f"title_{code}": i18n.translate(sc["title"], code) for code in i18n.LANGS}} for sc in scenarios.phone_scenarios(engine, persona)], "attacks": scenarios.ATTACKS,
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
def api_join(_: str = ADMIN):
    lan = _lan_address()
    return {"lan": lan, "pay_url": f"{lan}/pay" if lan else None}


@app.get("/api/v1/join.svg", include_in_schema=False)
def api_join_svg(_: str = ADMIN):
    lan = _lan_address()
    if not lan:
        raise HTTPException(status_code=404, detail="Start with ./run.sh wifi so that phones can join.")
    # A complete SVG file: an <img> cannot show the inline kind, which has no XML namespace.
    buf = io.BytesIO()
    segno.make(f"{lan}/pay", error="m").save(buf, kind="svg", scale=5, border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml")


# --- compatibility with the SatarkPay Android app and browser extension -----------

_seen_ingest: dict[str, dict] = {}
_last_link_logged: dict[str, float] = {}
MAX_SEEN_INGEST = 2000


def _ingest_token_ok(given: str | None) -> bool:
    expected = config.env("SATARK_TOKEN")
    return bool(expected and given and hmac.compare_digest(expected.encode(), given.encode()))


@app.get("/api/health")
def health():
    return {"status": "ok", "app": config.APP_NAME, "version": VERSION, "models": pay_models.ready()}


@app.get("/api/laptop-proof")
def laptop_proof(request: Request, nonce: str = Query(min_length=16, max_length=64)):
    """The phone looks for this laptop on its Wi-Fi or hotspot, and sends real messages to it, so the laptop proves it knows the pairing
    code without revealing it. Only its own address is signed, so another device cannot pass this answer on as its own."""
    code = config.env("SATARK_TOKEN")
    if not code or config.ON_VERCEL:
        raise HTTPException(status_code=404, detail="Not found.")
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    lan = _lan_address()
    if host not in {"127.0.0.1", lan.split("//")[1].rsplit(":", 1)[0] if lan else "127.0.0.1"}:
        raise HTTPException(status_code=403, detail="Not this laptop's address.")
    return {"proof": hmac.new(code.encode(), f"{nonce}:{host}".encode(), "sha256").hexdigest()}


@app.post("/api/ingest")
def api_ingest(body: IngestIn, request: Request, engine: Live = Depends(get_live)):
    """An SMS that arrived on the phone with SMS Guard. It is judged, and remembered as context for the phone's user.
    From another device the pairing code (header X-Satark-Token) is required."""
    if not auth.role_of(request) and not is_local(request) and not _ingest_token_ok(request.headers.get("x-satark-token")):
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
    _log_check(request, body.channel.upper(), (body.sender or "Unknown sender").strip()[:200], None, "", r["score"], r["level"], "WARN" if level_rank(r["level"]) >= level_rank(config.WARN_FROM_LEVEL) else "ALLOW", r.get("category") or "")     # the words themselves are not kept
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
def api_check_url(request: Request, u: str = Query(min_length=1, max_length=config.MAX_URL_CHARS), lookup: bool = False):
    url = normalise_url(u.replace("\\", "/"))     # browsers read a backslash as a slash: evil.com\@bank.com opens evil.com
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Only http and https links can be checked.")
    result = analyze_url(url, raw=u, lookup=lookup)
    result["needs_warning"] = level_rank(result["level"]) >= level_rank(config.WARN_FROM_LEVEL)
    # The extension checks every link on every page, so only a risky one is kept when nobody is logged in, and only once a minute.
    now = time.monotonic()
    worth = auth.session_of(request) is not None or (result["needs_warning"] and now - _last_link_logged.get(url, -1e9) > 60)
    if worth:
        _last_link_logged[url] = now
        while len(_last_link_logged) > MAX_SEEN_INGEST:
            _last_link_logged.pop(next(iter(_last_link_logged)))
    if worth:
        _log_check(request, "LINK CHECK", url, None, "", result["score"], result["level"], "WARN" if result["needs_warning"] else "ALLOW", result["factors"][0]["title"] if result.get("factors") else "")
    return result


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return JSONResponse(status_code=404, content={"detail": getattr(exc, "detail", "Not found")})


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
