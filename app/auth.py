"""Three logins: user, merchant and admin. The server decides what each may do; hiding a screen would not stop anyone.

One demo account per role. Only salted hashes are stored, in .env, which is never committed.
    python -m app.auth           create the accounts that are missing and print their passwords
    python -m app.auth --reset   make new passwords for all three
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sys
import threading
import time

from fastapi import HTTPException, Request

from app import config
from app.payments import store

ACCOUNTS = {
    "user": {"username": "sunita", "name": "Sunita Sharma", "home": "/pay", "env": "SATARK_PASS_USER"},
    "merchant": {"username": "ramesh", "name": "Ramesh Kirana Store", "home": "/merchant", "env": "SATARK_PASS_MERCHANT"},
    "admin": {"username": "admin", "name": "Fraud analyst", "home": "/", "env": "SATARK_PASS_ADMIN"},
}
COOKIE = "satarkpay_session"
SIGN_UP_ROLES = ("user", "merchant")
SESSION_SECONDS = 12 * 3600
MAX_FAILS = 5
LOCK_SECONDS = 60
MIN_PASSWORD = 8
_USERNAME = re.compile(r"^[a-z0-9._-]{3,30}$")

_lock = threading.Lock()
_ended: dict[str, float] = {}     # logged-out session ids until they would have expired anyway
_fails: dict[str, tuple[int, float]] = {}
_fallback_secret = secrets.token_bytes(32)


def _secret() -> bytes:
    """Sessions are signed, not stored, so they survive a restart when this secret is set (needed on Vercel, where instances come and go)."""
    configured = config.env("SATARK_SESSION_SECRET")
    return configured.encode() if configured else _fallback_secret


def test_logins_on() -> bool:
    return config.env("SATARKPAY_TEST_LOGINS", "1") == "1"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt." + base64.urlsafe_b64encode(salt).decode() + "." + base64.urlsafe_b64encode(digest).decode()


def check_password(password: str, stored: str | None) -> bool:
    try:
        kind, salt, digest = (stored or "").split(".")
        if kind != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(digest)
        return hmac.compare_digest(hashlib.scrypt(password.encode(), salt=base64.urlsafe_b64decode(salt), n=2**14, r=8, p=1), expected)
    except ValueError:
        return False


_DUMMY = hash_password(secrets.token_hex(8))


def new_session(role: str, name: str, username: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"r": role, "n": name, "u": username, "x": int(time.time()) + SESSION_SECONDS, "j": secrets.token_hex(8)}).encode()).decode()
    signature = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + signature


def _read(token: str | None) -> dict | None:
    try:
        body, signature = (token or "").split(".")
        if not hmac.compare_digest(signature, hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()):
            return None
        session = json.loads(base64.urlsafe_b64decode(body))
    except (ValueError, TypeError):
        return None
    if session["x"] <= time.time() or session["r"] not in ACCOUNTS:
        return None
    with _lock:
        return None if session["j"] in _ended else session


def _known_password(role: str, username: str) -> tuple[str | None, str | None]:
    """The stored hash and display name for this login, from the demo accounts or from sign-ups."""
    account = ACCOUNTS[role]
    if username == account["username"]:
        return config.env(account["env"]), account["name"]
    row = store.get_account(role, username)
    return (row["password_hash"], row["name"]) if row else (None, None)


def login(role: str, username: str, password: str) -> str:
    """A new session token. The same message for every failure, so it does not say which part was wrong."""
    username = username.strip().lower()
    key = role + ":" + username      # per account, so one person's typos cannot lock out everyone else
    with _lock:
        count, until = _fails.get(key, (0, 0.0))
    if count >= MAX_FAILS and time.monotonic() < until:
        raise HTTPException(status_code=429, detail="Too many wrong tries. Wait a minute and try again.")
    stored, name = _known_password(role, username)
    if not check_password(password, stored or _DUMMY):      # always hashed, so a wrong name takes as long as a wrong password
        with _lock:
            count = 1 if time.monotonic() >= until else count + 1
            while len(_fails) >= 5000:
                del _fails[next(iter(_fails))]
            _fails[key] = (count, time.monotonic() + LOCK_SECONDS)
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    if stored is None:
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    with _lock:
        _fails.pop(key, None)
    return new_session(role, name, username)


def sign_up(role: str, username: str, password: str, name: str) -> str:
    """Users and merchants can create an account. An admin account can never be created this way."""
    username = username.strip().lower()
    name = name.strip()
    if role not in SIGN_UP_ROLES:
        raise HTTPException(status_code=403, detail="Admin accounts cannot be created here.")
    if not _USERNAME.match(username):
        raise HTTPException(status_code=422, detail="Username: 3 to 30 letters, numbers, dots, dashes or underscores.")
    if len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=422, detail=f"Password: at least {MIN_PASSWORD} characters.")
    if not 2 <= len(name) <= 60:
        raise HTTPException(status_code=422, detail="Enter your name or your shop's name.")
    taken = username == ACCOUNTS[role]["username"] or not store.add_account(role, username, hash_password(password), name)
    if taken:
        raise HTTPException(status_code=409, detail="That username is taken.")
    return new_session(role, name, username)


def test_login(role: str) -> str:
    """One click for judges. It opens the shared demo account, on simulated data only."""
    if not test_logins_on():
        raise HTTPException(status_code=403, detail="Test logins are switched off.")
    return new_session(role, ACCOUNTS[role]["name"], ACCOUNTS[role]["username"])


def logout(token: str | None) -> None:
    session = _read(token)
    if session:
        now = time.time()
        with _lock:
            for key in [k for k, x in _ended.items() if x <= now]:
                del _ended[key]
            _ended[session["j"]] = session["x"]


def _token_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE)


def session_of(request: Request) -> dict | None:
    return _read(_token_from(request))


def role_of(request: Request) -> str | None:
    session = session_of(request)
    return session["r"] if session else None


def token_of(request: Request) -> str | None:
    return _token_from(request)


def require(*roles: str):
    """A route dependency: the caller must be logged in with one of these roles. Returns the role."""
    def check(request: Request) -> str:
        role = role_of(request)
        if role is None:
            raise HTTPException(status_code=401, detail="Please log in.")
        if role not in roles:
            raise HTTPException(status_code=403, detail="This account cannot do that.")
        return role
    return check


def _write_hashes(new: dict[str, str]) -> None:
    path = config.ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() not in new]
    lines += [f"{k}={v}" for k, v in new.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main(reset: bool) -> None:
    new, shown = {}, []
    for role, account in ACCOUNTS.items():
        if reset or not config.env(account["env"]):
            password = secrets.token_urlsafe(6)
            new[account["env"]] = hash_password(password)
            shown.append(f"  {role:<9} username: {account['username']:<8} password: {password}")
    if new:
        _write_hashes(new)
        print("SatarkPay logins. These passwords are shown only now. ./run.sh accounts makes new ones:")
        print("\n".join(shown))


if __name__ == "__main__":
    main("--reset" in sys.argv)
