"""Real latency and throughput, on this machine, over real HTTP. The numbers go into models/metrics.json.

    ./run.sh loadtest       (the app must not be running: this starts its own copy on another port)

The server runs in its own process, as it would in real use. In one process, clients and server would fight over Python's
global lock and the result would say more about the test than the system. Traffic comes from many different people, with
about one payment in ten risky: hammering a few accounts would only measure the velocity alerts.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SATARKPAY_DB"] = str(Path(tempfile.mkdtemp(prefix="satarkpay-load-")) / "load.db")
os.environ["SATARKPAY_AUTOSTART"] = "0"

import httpx      # noqa: E402

from app import auth  # noqa: E402

LOAD_PASSWORD = "load-test-only"

from app import config                 # noqa: E402
from app.payments import store         # noqa: E402
from app.payments.live import Live     # noqa: E402

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"
ONE_CLIENT_REQUESTS = 3000
CLIENT_PROCESSES = 4
REQUESTS_PER_PROCESS = 1000
ENGINE_EVENTS = 30000


def pct(values, q):
    s = sorted(values)
    return round(s[min(len(s) - 1, int(len(s) * q))], 2)


def users_and_shops() -> tuple[list, list]:
    """The same world the server builds, so the payers and shops are ones it knows."""
    live = Live(warmup_days=0)
    users = [(u.vpa, u.device, u.city) for u in live.world.user_list[:1500]]
    shops = [m.vpa for m in live.world.merchants if not m.online][:200]
    return users, shops


def payload(i: int, users: list, shops: list) -> dict:
    vpa, device, city = users[i % len(users)]
    if i % 10 == 0:     # the slower path: an alert with its full explanation
        return {"payer": vpa, "payee": f"load.fake.refund{i}@simybl", "amount": 2999, "kind": "COLLECT", "note": "Refund of Rs 2999 approve to receive", "device": device, "city": city, "record": True}
    return {"payer": vpa, "payee": shops[i % len(shops)], "amount": 50 + i % 700, "kind": "QR", "device": device, "city": city, "record": True}


def run_client(args: tuple) -> list[tuple[float, bool]]:
    start, count, users, shops = args
    out = []
    with httpx.Client(timeout=15) as c:
        assert c.post(URL + "/api/v1/auth/login", json={"role": "admin", "username": "admin", "password": LOAD_PASSWORD}).status_code == 200
        for i in range(start, start + count):
            t0 = time.perf_counter()
            r = c.post(URL + "/api/v1/score", json=payload(i, users, shops))
            ms = (time.perf_counter() - t0) * 1000
            assert r.status_code == 200, r.text
            out.append((ms, r.json()["alert"]))
    return out


def main_load() -> None:
    store.init()
    engine = Live()
    started = time.perf_counter()
    before = engine.kpis["scored"]
    engine.step(ENGINE_EVENTS)
    seconds = time.perf_counter() - started
    scored = engine.kpis["scored"] - before
    engine_lat = list(engine.latencies)
    print(f"Engine: {scored:,} payments in {seconds:.1f} s = {scored / seconds:,.0f} per second, scoring p95 {pct(engine_lat, 0.95)} ms", flush=True)
    users, shops = users_and_shops()

    env = dict(os.environ, SATARK_PORT=str(PORT), SATARK_PASS_ADMIN=auth.hash_password(LOAD_PASSWORD))
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        for _ in range(240):
            try:
                urllib.request.urlopen(URL + "/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        one = run_client((0, ONE_CLIENT_REQUESTS, users, shops))
        times = [m for m, _ in one]
        alerts = [m for m, a in one if a]
        print(f"HTTP, one client: p50 {pct(times, .5)} ms, p95 {pct(times, .95)} ms, p99 {pct(times, .99)} ms ({len(alerts)} alerts, alert p95 {pct(alerts, .95)} ms)", flush=True)
        t0 = time.perf_counter()
        with ProcessPoolExecutor(CLIENT_PROCESSES) as pool:
            results = list(pool.map(run_client, [(100_000 * (n + 1), REQUESTS_PER_PROCESS, users, shops) for n in range(CLIENT_PROCESSES)]))
        wall = time.perf_counter() - t0
        many = [m for part in results for m, _ in part]
        print(f"HTTP, {CLIENT_PROCESSES} client processes: {len(many) / wall:,.0f} requests per second, p50 {pct(many, .5)} ms, p95 {pct(many, .95)} ms, p99 {pct(many, .99)} ms", flush=True)
    finally:
        server.terminate()
        server.wait(timeout=10)

    metrics = json.loads(config.METRICS_FILE.read_text(encoding="utf-8")) if config.METRICS_FILE.exists() else {}
    metrics["latency"] = {
        "note": f"Measured on the team's laptop ({os.cpu_count()} logical cores) with one server process, about one payment in ten being risky. It says nothing about a bank's production load.",
        "engine": {"events": scored, "per_second": scored / seconds, "p50_ms": pct(engine_lat, .5), "p95_ms": pct(engine_lat, .95), "p99_ms": pct(engine_lat, .99), "mean_ms": round(statistics.mean(engine_lat), 2)},
        "http": {"requests": ONE_CLIENT_REQUESTS, "p50_ms": pct(times, .5), "p95_ms": pct(times, .95), "p99_ms": pct(times, .99), "alert_share": len(alerts) / len(times), "alert_p95_ms": pct(alerts, .95)},
        "concurrent": {"client_processes": CLIENT_PROCESSES, "per_second": len(many) / wall, "p50_ms": pct(many, .5), "p95_ms": pct(many, .95), "p99_ms": pct(many, .99)},
    }
    config.METRICS_FILE.write_text(json.dumps(metrics, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Added to {config.METRICS_FILE}")


if __name__ == "__main__":
    main_load()
