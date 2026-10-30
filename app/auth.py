"""Three logins: user, merchant and admin. The server decides what each may do; hiding a screen would not stop anyone.

One demo account per role. Only salted hashes are stored, in .env, which is never committed.
    python -m app.auth           create the accounts that are missing and print their passwords
    python -m app.auth --reset   make new passwords for all three
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sys
import threading
import time

from fastapi import HTTPException, Request

from app import config

ACCOUNTS = {
    "user": {"username": "sunita", "name": "Sunita Sharma", "home": "/pay", "env": "SATARK_PASS_USER"},
    "merchant": {"username": "ramesh", "name": "Ramesh Kirana Store", "home": "/merchant", "env": "SATARK_PASS_MERCHANT"},
    "admin": {"username": "admin", "name": "Fraud analyst", "home": "/", "env": "SATARK_PASS_ADMIN"},
}
COOKIE = "satarkpay_session"
SESSION_SECONDS = 12 * 3600
MAX_SESSIONS = 2000
MAX_FAILS = 5
LOCK_SECONDS = 60

_lock = threading.Lock()
_sessions: dict[str, dict] = {}     # keyed by the token's hash, so a memory dump holds no usable token
_fails: dict[str, tuple[int, float]] = {}


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


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(role: str, username: str, password: str) -> str:
    """A new session token. The same message for every failure, so it does not say which part was wrong."""
    account = ACCOUNTS[role]
    with _lock:
        count, until = _fails.get(role, (0, 0.0))
    if count >= MAX_FAILS and time.monotonic() < until:
        raise HTTPException(status_code=429, detail="Too many wrong tries. Wait a minute and try again.")
    ok = check_password(password, config.env(account["env"]))      # always hashed, so a wrong name takes as long as a wrong password
    if not ok or not hmac.compare_digest(username.strip().lower().encode(), account["username"].encode()):
        with _lock:
            count = 1 if time.monotonic() >= until else count + 1
            _fails[role] = (count, time.monotonic() + LOCK_SECONDS)
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _lock:
        _fails.pop(role, None)
        for key in [k for k, s in _sessions.items() if s["expires"] <= now]:
            del _sessions[key]
        while len(_sessions) >= MAX_SESSIONS:
            del _sessions[next(iter(_sessions))]
        _sessions[_token_key(token)] = {"role": role, "expires": now + SESSION_SECONDS}
    return token


def logout(token: str | None) -> None:
    if token:
        with _lock:
            _sessions.pop(_token_key(token), None)


def _token_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE)


def role_of(request: Request) -> str | None:
    token = _token_from(request)
    if not token:
        return None
    with _lock:
        session = _sessions.get(_token_key(token))
        if session is None:
            return None
        if session["expires"] <= time.monotonic():
            del _sessions[_token_key(token)]
            return None
        return session["role"]


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
