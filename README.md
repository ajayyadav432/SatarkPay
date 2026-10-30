<p align="center"><img src="docs/logo.svg" alt="SatarkPay logo: a shield with a watchful eye" width="110"></p>

# SatarkPay

Stops a scam UPI payment before the money is gone, and says why.
SPHINX'26, MNIT Jaipur. Problem statement 3.2: *Real-Time Fraud Detection for UPI and Digital Payments*.

Every payment is scored before it goes through. It gets a risk score from 0 to 100, a decision (Allow, Warn, Hold or Block) and the reasons
in plain English and Hindi. There is a live dashboard for analysts, an alert screen for the person paying, a view for small merchants and one API call for apps.
It runs offline on one laptop.

> **Everything here is simulated.** No real money, real accounts or real UPI connection. All UPI IDs end in `@sim...`, so that a simulated "mule" can never match a real person.
> The results are on synthetic data. **How it would do on real payments is unknown.**

<p align="center"><img src="docs/screen_phone.png" alt="The phone screen stopping a fake refund request, with the reasons" width="270"> <img src="docs/screen_dashboard.png" alt="The live dashboard during attacks: payments, alerts, the money network and the answer key" width="560"></p>

## Team

| Name | GitHub |
|---|---|
| Ajay Yadav | [@ajayyadav432](https://github.com/ajayyadav432) |
| Divyansh Shah | [@Divyanshshah01](https://github.com/Divyanshshah01) |
| manasvi15-git | [@manasvi15-git](https://github.com/manasvi15-git) |
| gauravpareek-web | [@gauravpareek-web](https://github.com/gauravpareek-web) |

## Run it

```bash
./run.sh            # start, then open http://localhost:8000
./run.sh wifi       # start so that phones on the same Wi-Fi or hotspot can join (a QR code appears on the dashboard)
./run.sh test       # run all tests
./run.sh train      # rebuild the simulated world and retrain both models
./run.sh evaluate   # measure everything again and write models/metrics.json
./run.sh paysim     # the public PaySim benchmark (downloads about 490 MB the first time)
./run.sh loadtest   # measure real latency and throughput (the app must not be running)
```

The first run builds the Python environment and needs internet once. After that, nothing needs the internet. It was built and tested with Python 3.13. Trained models are in the repo.

| Screen | For | What it does |
|---|---|---|
| `/` | Bank analyst, and the stage | Live payments, attacks to launch, alerts with reasons and SHAP, the money network, the answer key |
| `/pay` | The person paying | A demo payment app that stops the payment and says why. **Beat the model** lets you play the scammer |
| `/merchant` | A small shop | What really arrived, so a fake payment screenshot cannot fool the shopkeeper |
| `/how` | Judges | Every measured number, what each layer adds, and the known limits |

## One API call

```bash
curl -s http://localhost:8000/api/v1/score -H 'Content-Type: application/json' -d '{
  "payer": "sunita.sharma@simsbi", "payee": "refund-sbi@simybl", "amount": 2999,
  "kind": "COLLECT", "note": "Refund of Rs 2999 approve to receive"
}'
```

It returns the score, level, action, reasons in two languages, advice and the SHAP values. Nothing is recorded until `POST /api/v1/outcome`, with the `token` from that response, says what the person did. The schema is at `/openapi.json`.

## How each requirement is met

The left column is word for word from the problem statement. There is one automated test per row in `tests/test_acceptance.py`.

| # | Problem statement | How |
|---|---|---|
| R1 | "fake collect requests" | Every collect request is scored before the person approves it: the note, the payee, the blast pattern. NPCI ended P2P collect by 1 Oct 2025, so a P2P collect is a hard rule and fake collects are modelled as merchant-style accounts |
| R2 | "phishing links" | The link that opened the payment, and any scam SMS received just before, read by the SatarkAI engine |
| R3 | "mule accounts" | Many strangers paying in, money going straight out, young accounts, one phone with many accounts. A live network view |
| R4 | "users only realise after money is gone" | The decision comes before money moves. If a victim pays anyway, the mule's next transfer can still be held: **₹ still recoverable** |
| R5 | "Banks, fintech apps, small merchants, consumers" | Analyst console, REST API, merchant view with a measured false-alarm rate, alert screen |
| R6 | "Train an anomaly-detection model on a synthetic or public transaction dataset" | Isolation Forest (no labels) and XGBoost on a UPI simulator, with public PaySim as a check |
| R7 | "flag risky transactions with a live scoring API" | `POST /api/v1/score` |
| R8 | "and alert screen" | `/pay` |
| R9 | "Isolation Forest or XGBoost, FastAPI, Kafka or a simple stream simulator, a dashboard" | Both models, FastAPI, a stream simulator behind a small `Bus` class, a live dashboard |
| R10 | Bonus: "Explainable alerts that tell the user why a payment looks suspicious" | Exact TreeSHAP values turned into plain sentences with real numbers, in English and Hindi. No language model, so nothing can be invented |

## How it decides

```
risk = 1 - (1 - XGBoost) x (1 - Isolation Forest) x (1 - rule 1) x (1 - rule 2) ...
```

More evidence never lowers the risk. The risk is placed on a 0 to 100 scale using bands measured on validation data: at most 1% of genuine payments reach Medium (40), 0.2% reach High (60), 0.05% reach Critical (80).

| Decision | When | Meaning |
|---|---|---|
| Allow | Below 40 | Goes through |
| Warn | 40 and up | The person sees why and can continue after a pause |
| Hold | 60 and up, ₹200 or more | Paused for a cooling-off, in the analyst queue |
| Block | 80 and up, and two independent layers agree or a plain fact applies | Refused, with the reason and a way to appeal |

A model alone can never refuse a payment. The rules are in `app/payments/policy.py`.

## Measured results

Every number is written by `ml/evaluate.py`, `ml/paysim_benchmark.py` or `scripts/loadtest.py` to `models/metrics.json`, and the `/how` page reads that file. Test data is later in time than training data, and test scammers are accounts never seen in training. It covers 3,87,688 payments with 2,434 scams, including a whole new world that nothing was tuned on.

We never report accuracy. Reported UPI fraud is about 6.8 per million payments, so a model that never flags anything is 99.999% "accurate".

**The policy on the test set.** Scam payments flagged: **93%**. Stopped before the money moved: **84%**. Genuine payments flagged: **0.59%**. Stopped: **0.04%**. Obvious scams flagged: 99%. Careful scams, which try to look normal: 80%.

| Scam | In test | Flagged | Stopped |
|---|---|---|---|
| Fake collect request | 562 | 100% | 98% |
| Phishing link | 257 | 96% | 69% |
| "Scan to receive" QR | 96 | 77% | 66% |
| Payment to a mule | 374 | 94% | 83% |
| Mule moving money on | 996 | 91% | 83% |
| Account takeover | 63 | 89% | 63% |
| "Digital arrest" transfer | 86 | 87% | 73% |

**What each layer adds.** Recall is at the same budget, 1% of genuine payments flagged.

| Layers | PR-AUC | Recall |
|---|---|---|
| Payer behaviour only | 0.496 | 56% |
| + the account's own money moves | 0.516 | 58% |
| + payee signals (mules) | 0.898 | 95% |
| + SatarkAI context (note, link, UPI ID, SMS) | 0.940 | 97% |
| + Isolation Forest and hard rules (the full system) | 0.931 | 95% |
| Isolation Forest alone (no labels at all) | 0.209 | 39% |

On scams it has seen, XGBoost alone does slightly better than the full system. The other layers earn their place in the next test.

**Scams it has never seen.** Train with no example of one scam type, then see what still catches it, at the same budget.

| Left out of training | XGBoost alone | Full system |
|---|---|---|
| Fake collect request | 7% | 81% |
| Phishing link | 37% | 73% |
| "Scan to receive" QR | 27% | 66% |
| Payment to a mule | 84% | 83% |
| Mule moving money on | 79% | 73% |
| Account takeover | 59% | 81% |
| "Digital arrest" transfer | 94% | 90% |

**If scammers get smarter.** In a separate world where 90% of scams are careful, with no retraining: 76% flagged, 61% stopped, 0.63% of genuine payments flagged.

**Public data.** On PaySim, split by time, XGBoost scores PR-AUC 0.998 with the balance columns and 0.697 without. In 97.8% of PaySim's fraud rows the amount equals the sender's whole balance, against 0.0001% of genuine rows, so the first number mostly finds that shortcut. The number to trust is the second.

**Speed on this laptop.** One server process: p50 2.27 ms, p95 5.06 ms, p99 6.98 ms over HTTP, 483 requests per second with 4 clients at once.

## Known limits

- **Everything is synthetic.** Accuracy on real payments is unknown. We wrote the simulator, so the model may have learned the simulator. Hard cases, new worlds and leave-one-out tests reduce that risk. They do not remove it.
- **Precision here is flattering.** The simulation has about 923 times more fraud than reported reality, so that the model has examples. If real fraud is that rare and the model were this good, which is unproven, there would be about 929 false alarms per real scam at this budget. A bank would set a much tighter budget. The design assumes this: warnings are cheap, blocks are rare, and a person always has a way out.
- **Payee signals need a view across banks.** A single bank cannot see fan-in on another bank's account. That points to a deployment at the network level.
- **No real UPI integration.** A hackathon cannot get one. The integration point is one API call before the payment is sent.
- **Kafka is not built.** The problem statement allows a stream simulator, and a stream simulator keeps the demo on one laptop with nothing else to install. The `Bus` class is where Kafka would go. That has not been tested.
- **The scoring API has no login.** It is a demo for one local network. A real deployment needs authentication and rate limits.
- **SMS privacy.** In this demo the laptop reads the SMS. The production design scores it on the phone and sends only the score.
- **The Android app has been run on one real phone (Samsung SM-E366B, Android 17) over USB.** Connection and its built-in sample SMS worked against this server. A real incoming SMS has not been tested. The extension was run in Chromium against this server.
- **The "this looks like" label is a best guess.** It named the right scam for 80% of flagged scams in the test. The reasons are exact. The label is not.

## Built on SatarkAI

The team's earlier project [SatarkAI](https://github.com/ajayyadav432/SatarkAI) won IEEE-IGNITE 2026. SatarkPay reuses its detection engine, Android app and browser extension, unchanged. Everything to do with transactions is new. [docs/REUSED_FROM_SATARKAI.md](docs/REUSED_FROM_SATARKAI.md) lists exactly what came from where, and a test checks the checksums.

## Project layout

```
app/
  main.py            REST API, live stream, pages
  config.py          names, paths, limits
  payments/          features, context, rules, models, policy, explain, scorer, live, scenarios, graph, store
  analysis/, data/   the SatarkAI engine and rules, unchanged
  static/            dashboard, pay, merchant, how
ml/
  simulate.py        the UPI world: normal life, 7 scam types, hard cases
  dataset.py         replays a world through the live feature store
  train.py           XGBoost, Isolation Forest, score bands
  evaluate.py        everything on the model card
  paysim_benchmark.py
  satarkai/          SatarkAI's trained text and URL models, unchanged
models/              xgb.ubj, iforest.joblib, bundle.json, metrics.json
tests/               unit, parity, API, security, acceptance R1-R10, browser; engine/ holds SatarkAI's own tests
android/, extension/ SatarkAI SMS Guard and Link Guard, unchanged
docs/                demo script, judging Q&A, reuse record, pitch deck
plan.md              the plan, design decisions and the findings log
```

## Using the reused sensors

- **SMS Guard (Android).** Build with `cd android && ./gradlew assembleDebug`, or reuse an existing install. Start with `./run.sh wifi`. In the app, enter `http://<laptop-ip>:8000` and the printed pairing code. A real SMS then becomes context: a payment that follows it is scored with it.
- **Link Guard (Chrome or Edge).** Load `extension/` at `chrome://extensions` with *Developer mode* on. It marks risky links on any page and shows a warning before they open. The server must be running on this laptop.

## Data sources and facts

- **The UPI world:** written by the team (`ml/simulate.py`). Same seed, same data. Not stored in the repo.
- **PaySim:** Lopez-Rojas, Elmir, Axelsson (2016), downloaded from the Hugging Face mirror `theman10/paysim`. Not stored in the repo.
- **SatarkAI's text and URL models:** their own datasets are listed in the SatarkAI README.
- **Facts quoted in the app and the pitch:** [NPCI ends P2P collect](https://www.angelone.in/news/market-updates/npci-to-end-upi-person-to-person-collect-requests-from-october-to-curb-fraud), [UPI fraud figures, Lok Sabha, 15 Dec 2025](https://ianslive.in/upi-frauds-worth-rs-805-crore-witnessed-this-fiscal-so-far-minister--20251215175703), [UPI volume in FY25](https://www.business-standard.com/finance/news/upi-s-contribution-to-payments-ecosystem-volume-grows-to-83-4-in-fy25-125052900871_1.html), [Financial Fraud Risk Indicator](https://www.medianama.com/2025/05/223-dot-financial-fraud-risk-indicator-upi/). These are press-reported.
- **Inter font:** SIL Open Font License, `app/static/vendor/fonts/OFL.txt`.
