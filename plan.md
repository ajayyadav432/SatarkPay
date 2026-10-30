# SatarkPay: plan for SPHINX'26

**Problem statement 3.2: Real-Time Fraud Detection for UPI and Digital Payments**
(Domain 3, Emerging Tech in Finance. 24-hour hackathon, MNIT Jaipur, team of up to 4.)

> "SatarkPay" is a working name, set in one place (`app/config.py`). Satark = alert.

Status is tracked in section 16. Numbers marked **target** are goals, not results. A number only
counts as a result once a script has written it to `models/metrics.json`.

---

## 1. The problem statement, requirement by requirement

The middle column is copied word for word from `Hackathon_Problem_Statements.pdf`, page 7.

| # | PS 3.2 says | What we build |
|---|---|---|
| R1 | "fake collect requests" | Score every collect request before the user approves it; note, payee and blast pattern |
| R2 | "phishing links" | Score the link that opened the payment, and remember scam SMS with links received just before it |
| R3 | "mule accounts" | Payee-side signals: fan-in, money passing straight through, account age. A live mule-ring graph |
| R4 | "users only realise after money is gone" | A decision **before** money moves: ALLOW / WARN / HOLD / BLOCK. If the victim pays anyway, hold the mule's next hop |
| R5 | "Banks, fintech apps, small merchants, consumers" | Banks: analyst console. Fintech: REST API. Merchants: incoming-payments view and a measured false-alarm rate on shops. Consumers: alert screen |
| R6 | "Train an anomaly-detection model on a synthetic or public transaction dataset" | Isolation Forest on our UPI simulator, and a benchmark on public PaySim |
| R7 | "flag risky transactions with a live scoring API" | `POST /api/v1/score` (FastAPI) |
| R8 | "and alert screen" | `/pay`: phone screen that stops the payment and says why |
| R9 | "Isolation Forest or XGBoost, FastAPI, Kafka or a simple stream simulator, a dashboard" | Both models, FastAPI, stream simulator, live dashboard |
| R10 | Bonus twist: "Explainable alerts that tell the user why a payment looks suspicious" | Exact TreeSHAP turned into plain reasons with real numbers, in English and Hindi |

The PDF also says what wins: **"Judging favours originality, understanding of the problem and
viability, so pick one where you can show a live demo, not just slides."**

There is one automated acceptance test per requirement (`tests/test_acceptance.py`).

---

## 2. What the earlier project gives us (measured, 30 Oct 2026)

Checked on the local copy, which is the same commit as GitHub (`66b436a`). Its 340 non-browser tests
pass here.

| PS 3.2 needs | In the earlier project? | Evidence |
|---|---|---|
| Transaction model | No | 0 files mention `isolation`, `xgboost`, `anomal`, `mule`, `kafka` |
| Transaction scoring API | No | The API takes `text` and `sender` only. No amount, payee, device or history |
| Stream, alert screen for payments | No | Alerts are for messages, polled every 3 s |
| Phishing links | **Yes** | `sbi-kyc-update.xyz/pay?pa=refund@ybl` scores Critical 90; `irctc.co.in` scores Safe 0 |
| Explainable reasons | **Yes** | Exact SHAP on linear models, plain reasons, 3 languages |
| Speed | **Yes** | Median 0.34 ms, p95 2.82 ms per message |
| Scam wording in collect notes | Partly | "Enter UPI PIN to receive" High 78; "Refund of Rs 2999 approve to receive" only Low 30 |
| False alarms on payment notes | Problem | Genuine note "electricity bill oct" scores Medium 40 |
| Fake UPI IDs | Weak | `paytm.cashback.offer@okaxis` scores Safe 0: UPI IDs get no brand check |

**Conclusion.** the earlier project reads words. PS 3.2 is about money. We keep the engine as one input and build
everything transaction-related new. The engine's gaps above are not patched in the engine: a new layer
handles them (`app/payments/context.py`), and the model learns when a note matters ("electricity" is fine
when paid to a verified biller, not when paid to a 2-day-old stranger).

---

## 3. The idea, and why it can win

Many UPI scams are authorised by the victim: right phone, right PIN, right person. To a model that only
sees numbers, many of these look normal. So:

**SatarkPay combines how the money moves with what the victim was just told.**

| Judging point | What we show |
|---|---|
| **Originality** | (1) Payment plus context: a scam SMS two minutes ago, a lure note, a link, a UPI ID imitating a bank. This is the part other teams would have to build from zero. (2) A **second chance**: if the victim pays anyway, the mule's outgoing transfer is held and the dashboard shows "₹ still recoverable". (3) **Beat the model**: a judge plays the scammer live and tries to fool it |
| **Understanding of the problem** | P2P collect ended on 1 Oct 2025, so fake collects now need merchant-style accounts (section 5). Fraud is about 7 in a million, so accuracy means nothing and hard blocks must be rare. Genuine people look like mules too: a student pooling trip money, a shopkeeper on a personal UPI ID |
| **Viability** | A bank or app calls one API before sending the payment. Runs offline on one laptop, no GPU. Measured latency. Honest limits |
| **Live demo** | Judges use their own phones. Press "attack", watch it get caught, report it, and watch the next victim get protected by that report |

---

## 4. Decisions

| Decision | Choice | Why |
|---|---|---|
| Project | New repo `SatarkPay`, in this folder | Your choice. an earlier hackathon repo stays untouched |
| Reuse | Copy the engine unchanged, as well as the Android app and the extension | Your choice: "new repo with existing code" |
| Model | **Both** XGBoost and Isolation Forest | XGBoost learns known scams and is exactly explainable. Isolation Forest needs no labels, for scams never seen |
| Data | Our UPI simulator, plus PaySim as a public benchmark | PaySim has no notes, links, devices or collect requests, so it cannot show R1 or R2. The PS allows either |
| Stream | Simple simulator behind a small `Bus` class, not Kafka | The PS allows it, and a stream simulator keeps the demo on one laptop with nothing else to install. Kafka is named as the production path and is **not** built or tested |
| Explanations | Templates filled from SHAP values and real numbers, no LLM | Exact and repeatable, works offline, cannot invent a reason |
| Front end | Plain HTML, CSS, JS, Chart.js stored locally. No build step | Same as the earlier project, works with no internet on stage |
| Hosting | Runs on the laptop; phones join over Wi-Fi or hotspot | Live streaming and in-memory state do not fit serverless hosting such as Vercel |
| Fake UPI IDs | All simulated IDs end in `@sim…` (`rahul.k482@simsbi`) | A simulated "mule" must never match a real person's UPI ID |

---

## 5. Facts a judge can test

| Fact | Source |
|---|---|
| NPCI circular of 29 Jul 2025: P2P collect requests stop being processed by 1 Oct 2025. **Merchant collect continues.** Before this, P2P collect was capped at ₹2,000 per transaction | [Angel One](https://www.angelone.in/news/market-updates/npci-to-end-upi-person-to-person-collect-requests-from-october-to-curb-fraud), [Business Standard](https://www.business-standard.com/finance/personal-finance/upi-collect-requests-to-end-from-october-here-s-how-it-changes-payments-125081500767_1.html) |
| UPI fraud, Lok Sabha reply by MoS Finance Pankaj Chaudhary, 15 Dec 2025: FY24 ₹1,087 crore, 13.42 lakh incidents. FY25 ₹981 crore, 12.64 lakh. FY26 to November ₹805 crore, 10.64 lakh | [IANS](https://ianslive.in/upi-frauds-worth-rs-805-crore-witnessed-this-fiscal-so-far-minister--20251215175703) |
| UPI volume FY25: about 185.8 billion transactions, ₹260.56 lakh crore | [Business Standard](https://www.business-standard.com/finance/news/upi-s-contribution-to-payments-ecosystem-volume-grows-to-83-4-in-fy25-125052900871_1.html), [IANS](https://ianslive.in/upi-share-surges-to-837-pc-in-digital-transactions-for-fy25--20250530153004) |
| DoT's Financial Fraud Risk Indicator rates **phone numbers** Medium / High / Very High. PhonePe blocks "Very High". Concern reported: legitimate users could be blocked "with no explanation or recourse" | [MediaNama](https://www.medianama.com/2025/05/223-dot-financial-fraud-risk-indicator-upi/) |
| RBI's MuleHunter.AI finds mule **accounts**, piloted with two large public sector banks. We found no published accuracy figures | [Business Standard](https://www.business-standard.com/finance/personal-finance/explained-rbi-is-using-an-ai-tool-mulehunter-ai-to-cut-down-digital-frauds-124120900250_1.html) |

Worked out from the above, for FY25:

- Reported fraud is 12.64 lakh out of 185.8 billion transactions: **about 7 in a million**. By value about 0.0038%.
- A model that never flags anything is therefore 99.999% "accurate". We never quote accuracy.
- Even with 80% recall and only 0.1% false alarms, about 184 alerts would be false for each real fraud
  at that rate. This is why a warning must be cheap and a block must be rare, and why several layers must
  agree before a hard block. Reported fraud undercounts real fraud, so the true rate is higher.

These are press-reported figures. We say that if asked.

How we position against FRI and MuleHunter: they rate a number or an account. SatarkPay decides on one
payment and tells the person why. FRI could become one more input. Do not claim "nobody does this".

---

## 6. Architecture

```
 SOURCES                        SATARKPAY SERVER (one FastAPI process)                      SCREENS
 ───────                        ──────────────────────────────────────                      ───────
 Stream simulator ──┐
 (fresh synthetic   │    ┌────────────────────────────────────────────────────────────┐
  day + attacks)    │    │ Feature store (same code in training and live)             │
                    ├─Bus┤  payer: usual amount, new payee, new device, jump in place │
 Phone screen /pay ─┤    │  payee: fan-in, money passing through, age, reports        │
 (judge's phone)    │    ├────────────────────────────────────────────────────────────┤
                    │    │ 1 XGBoost            known scam patterns, exact TreeSHAP   │ ┌▶ /pay alert screen
 Bank / fintech ────┤    │ 2 Isolation Forest   unusual, needs no labels              │ │   (why, in EN and HI)
 POST /api/v1/score │    │ 3 the earlier project engine    note, link, UPI ID, SMS (reused)      │ │
                    │    │ 4 Hard rules         e.g. P2P collect, "PIN to receive"    │─┼▶ / live dashboard
 Android SMS Guard ─┤    ├────────────────────────────────────────────────────────────┤ │   (feed, alerts, graph)
 (real SMS, reused) │    │ risk = 1 - (1-p)(1-a)(1-r1)(1-r2)...   → score 0-100       │ │
                    │    │ Policy: ALLOW / WARN / HOLD / BLOCK                        │ ├▶ /merchant
 Chrome Link Guard ─┘    │ Explain: top SHAP reasons → plain English and Hindi        │ │
 (reused)                └───────────────┬────────────────────────────────────────────┘ └▶ /how model card
                                         ▼
                              SQLite: alerts, analyst labels, reports ──▶ reports feed back into the payee's score
```

One payment end to end, about the time target below:

`/pay` sends the payment → features looked up → two models + context engine + rules → risk → policy →
reasons → alert on the phone and on the dashboard. **Target: p95 under 50 ms on this laptop. Measured: p95 4.96 ms over HTTP** (`scripts/loadtest.py`).

---

## 7. Data

### The UPI world simulator (`ml/simulate.py`)

A small fake India: about 15,000 users, 2,000 merchants, 35 days. Same seed, same data.

**Normal life.** Segments (student, salaried, gig worker, elder, shop owner) with their own amounts, hours,
payees, device and city.

**Scams, labelled by type:**

| Typology | How it looks | PS |
|---|---|---|
| `fake_collect` | New unverified merchant-style ID blasts collect requests with a lure note. Most people decline | R1 |
| `phishing_link` | Scam SMS with a link, then a link-opened payment to a new payee minutes later | R2 |
| `qr_scam` | "Scan to receive money": a QR payment to a new person | R1 |
| `mule_inflow` | Victim of an off-platform scam pays a mule. No note, no link: only payee signals can help | R3 |
| `mule_layering` | The mule moves the money out within minutes to hours | R3 |
| `account_takeover` | SIM swap: new phone, new city, night, quick payments that drain the account | extra |
| `coached_transfer` | "Digital arrest": large transfers by a scared person, on their own phone, at home | extra |

**Hard cases on purpose, or the model only learns our generator:**

- *Genuine but looks like fraud:* first big rent payment, a student pooling trip money then paying once
  (looks like a mule), a shop owner on a personal UPI ID (looks like a mule), a new phone, travel, night-shift
  workers, a genuine note saying "refund for dinner", a real biller's electricity note.
- *Fraud that looks genuine:* small amounts, older rented mule accounts, neutral notes such as "payment", no
  SMS seen. Only some users have the SMS sensor.

**Fraud rate is oversampled** to about 0.6% so the model has examples, about 923 times the reported rate.
So precision on our test set overstates real life. We publish a corrected estimate (section 11).

### PaySim (public benchmark, not the live model)

Downloaded from the Hugging Face mirror `theman10/paysim` (493 MB). Original: *PaySim*, Lopez-Rojas et al.
Not stored in the repo. Used only to run the same training recipe on data we did not write. We check it for
shortcuts, as the earlier project did with PhiUSIIL: fraud in PaySim empties the account, so balance columns may give
the label away. Results are reported with and without them.

---

## 8. Features (48)

Computed by one class, `FeatureStore`, used for both training replay and live scoring, so the two cannot
drift apart. Only events earlier than the payment are visible. Both are tested.

| Group | Features |
|---|---|
| **Payer** | amount, amount vs usual, amount vs largest ever, how rare this hour is for them, payments in 1 h and 24 h, sum in 1 h and 24 h, new payee, new payees in 1 h, new device, device age, km and km/h since last payment, how the payment started (typed, QR, link, collect), history length |
| **Payee (mule signals)** | account age, merchant, verified, payments in, distinct payers in 24 h, share of first-time payers, money in and out, share passed through within 1 h, collects sent, share of collects declined, reports |
| **Context (the earlier project)** | note risk, link risk, UPI ID imitating a brand or containing scam words, SMS risk in the last 15 min, SMS mentions this payee or this link's domain |

---

## 9. Models and decision

- **XGBoost** on all features. Probability `p`. Exact SHAP from `pred_contribs`, no extra library in serving.
- **Isolation Forest** on behaviour and payee features only, **no labels**. Its score is converted to a
  percentile `a`.
- **Hard rules** `r`: high-precision facts, for example a P2P collect request (not allowed on UPI since 1 Oct 2025)
  or a note asking for a PIN to *receive* money.
- **Fusion**, the same noisy-OR formula as the earlier project, so one line explains it:
  `risk = 1 - (1-p)(1-a)(1-r1)(1-r2)...`. More evidence never lowers the risk.
- **Policy**, `decide_action(risk, amount, signals)` in `app/payments/policy.py`:

| Action | Meaning | Rough rule (thresholds set on validation data) |
|---|---|---|
| ALLOW | Goes through | Low risk |
| WARN | Show reasons; the user can continue after a short wait | Medium risk, or anomaly alone |
| HOLD | Paused for a cooling-off; analyst queue | High risk and enough money at stake |
| BLOCK | Refused, with the reason and a way to appeal | Very high risk **and** two independent layers agree, or a hard rule |

A model alone cannot block: same idea as the earlier project's rule that High needs a non-model indicator. This is the
direct answer to the base-rate problem in section 5.

**Ajay's decision:** the first version of `decide_action()` is a working default. It is the most
business-critical logic in the system and the first thing a judge will question, so the team should own it.

---

## 10. Explanations (the bonus twist)

1. XGBoost's SHAP values are summed per **reason group** ("money passes straight through" covers 3 features).
2. Top positive groups become reasons, ranked by real SHAP size, filled with real values.
3. Hard rules and the the earlier project engine add their own reasons with the exact words that triggered them.
4. If the anomaly model fired, the page shows what is most unusual, for example "higher than 99.9% of normal
   payments". That describes the payment, not the forest's internals, and the page words it that way.

Example of the target output:

> **Stop. This looks like a fake refund request.**
> • You have never paid `refund-sbi@simybl` before
> • This account is 3 days old and is not a verified merchant
> • The note says "approve to receive". Entering your PIN always sends money, it never receives it
> • 41 people got a request from this account today; 38 declined

The same reasons appear in Hindi. An analyst also sees the full SHAP waterfall.

---

## 11. Honesty rules and evaluation

the earlier project won partly by being honest about its numbers. Same rules here:

1. Every number in the app, deck and docs comes from `models/metrics.json`, written by a script. None typed by hand.
2. Test data is **later in time** than training data, and test scammers are **new accounts**.
3. We never report accuracy. We report PR-AUC, recall at a fixed false-alarm rate, money-weighted recall.
4. Synthetic data is stated on the model card, in the pitch and in the README.
5. If a result looks too good, it is treated as a bug until explained.

**What gets measured (`ml/evaluate.py`):**

| Test | Question it answers |
|---|---|
| Time split, held-out test | How good is it, per scam type, at the chosen alert budget? |
| **Layer table** | What does each layer add? Behaviour only → + payee → + context → + anomaly |
| **Leave one scam out** | Train without one scam type, then test on it. How much do the anomaly model and rules recover? This is our measure for "new scams" |
| **Stealth drift** | A separate world where scammers got smarter. How much does it degrade? |
| **False alarms by group** | Rent, trip pooling, shop owners, travel, new phone, merchants |
| **Real-world correction** | Precision if fraud were 7 in a million, from our measured rates |
| **PaySim** | Same recipe on public data, with and without the shortcut |
| **Latency** | p50, p95, p99 over real HTTP calls, and sustained payments per second |

---

## 12. Screens

| Screen | For | Shows |
|---|---|---|
| `/` Dashboard | Bank analyst, and the stage | Live feed, KPIs (scored, payments/s, p95, alerts, ₹ stopped, ₹ still recoverable), ground truth panel, attack buttons, alert queue with reasons and SHAP, confirm or false alarm, mule graph, charts, QR code to open `/pay` |
| `/pay` | Consumer, and the judge's phone | Demo payment app, clearly marked "no real money". Scenario chips, **Beat the model** form, alert screen in English and Hindi, Decline and report, Call 1930, Continue after a wait |
| `/merchant` | Small merchant | Incoming payments, and warnings about flagged payments |
| `/how` | Judges | Model card, every table from section 11, known limits |

Message and note text is always rendered as plain text, so a scam note can never run code in the page.

---

## 13. API

| Method and path | Purpose |
|---|---|
| `POST /api/v1/score` | Score one payment. Risk, action, reasons, timing |
| `POST /api/v1/outcome` | The user approved or declined |
| `POST /api/v1/feedback` | An analyst or a victim labels a payment; reports feed back into the payee's score |
| `POST /api/v1/sms` | Remember a message the user received (context) |
| `GET /api/v1/stream` | Live feed for the dashboard (server-sent events) |
| `GET /api/v1/stream/user/{vpa}` | Live feed for one phone |
| `GET /api/v1/alerts`, `GET`/`PATCH /api/v1/alerts/{id}` | Alert queue |
| `GET /api/v1/graph` | Network around an account |
| `POST /api/v1/sim/...` | Start, stop, speed, launch an attack (only from the laptop) |
| `GET /api/v1/metrics` | Model card numbers |
| `GET /api/health`, `POST /api/ingest`, `GET /api/check-url`, `POST /api/check-urls`, `GET /go` | **Kept compatible with the earlier project**, so the existing Android app and extension work without changes |

---

## 14. Folder layout

```
plan.md  README.md  run.sh  requirements.txt  requirements-dev.txt  pytest.ini
app/
  main.py  config.py
  analysis/     the earlier project engine, unchanged
  data/         the earlier project rules and brand lists, unchanged
  payments/     schema, features, context, models, explain, policy, scorer, stream, scenarios, graph, store
  static/       dashboard, pay, merchant, how; vendor/ (Chart.js, Inter)
ml/             simulate, dataset, train, evaluate, paysim_benchmark
ml/engine/    the earlier project's text and URL models, unchanged
models/         xgb, iforest, bundle, metrics.json
scripts/        loadtest
tests/          unit, parity, API, security, acceptance R1-R10, browser
android/        Phone app: the earlier project SMS Guard, plus UPI QR scanning added later
extension/      the earlier project Link Guard, unchanged
demo/           the earlier project's demo pages with fake scam links, unchanged
docs/           DEMO_SCRIPT.md, JUDGING_QA.md, REUSED_CODE.md, reused_manifest.json, SatarkPay_Pitch.pptx
```

---

## 15. What was pre-built (for disclosure)

The PDF does not say whether code written before the event is allowed. **Check with the organisers.** The
screening PDF's contact is Manasa Paulson (`2025ucp1929@mnit.ac.in`). This table is what you would show them.
`docs/REUSED_CODE.md` lists the exact files and checksums.

| From the earlier project (commit `66b436a`, made for an earlier hackathon) | New for SPHINX |
|---|---|
| Text and URL detection engine, rules, brand list | UPI simulator, PaySim benchmark |
| Trained text and URL models | XGBoost and Isolation Forest models |
| Android SMS Guard, Chrome Link Guard | Feature store, mule signals, scoring API, policy, explanations |
| Chart.js, Inter font, visual style | Stream, dashboard, alert screen, merchant view, model card |

---

## 16. Build checklist

Every box is ticked only after it has been run and checked. Never ticked on the basis of "should work".

- [x] **M0 Skeleton.** venv, pinned requirements, copy engine, data, models, vendor files; the engine's own tests pass here
- [x] **M1 Simulator.** Normal life, 7 scam types, hard cases; deterministic; unit tests
- [x] **M2 Features.** Feature store, context layer with UPI ID check; no-future-leak and training/serving parity tests
- [x] **M3 Models.** Train XGBoost and Isolation Forest; inspect for leaks; `metrics.json`
- [x] **M4 Evaluation.** Layer table, leave-one-out, drift, false alarms by group, real-world correction, PaySim
- [x] **M5 Scorer.** Fusion, policy, explanations in English and Hindi; SHAP additivity test
- [x] **M6 API and stream.** REST API, Bus, simulator task, SSE, attack scenarios, SQLite, compatibility routes; tests
- [x] **M7 Alert screen.** `/pay`, scenarios, Beat the model, Hindi, report loop
- [x] **M8 Dashboard.** Load `dataviz` skill first. Feed, KPIs, alerts, SHAP, mule graph, attack buttons, QR
- [x] **M9 Other screens.** `/merchant`, `/how`
- [x] **M10 Verify for real.** Load `run` skill. Drive the actual app in a browser, screenshots, phone width, dark mode, no internet
- [x] **M11 Load test.** Real latency and throughput into `metrics.json`
- [x] **M12 Reused sensors.** Copy Android and extension; contract tests against the routes they call
- [x] **M13 Acceptance.** One test per R1-R10; full suite green
- [x] **M14 Docs.** README, DEMO_SCRIPT, JUDGING_QA, REUSED_CODE; every number checked against `metrics.json`
- [x] **M15 Deck.** Load `pptx` skill. Short deck from measured results
- [x] **M16 Review.** `code-review`, `security-review`, secret scan of everything to be published
- [x] **M17 Publish.** New public repo `ajayyadav432/SatarkPay`, push

---

## 17. Test plan

| Group | Checks |
|---|---|
| Engine (copied tests) | The reused engine behaves here exactly as in the earlier project |
| Simulator | Same seed gives same data; scam mix as configured; hard cases present |
| Feature store | Hand-computed windows; **no future data**; training replay equals live scoring |
| Context | `paytm.cashback.offer@okaxis` flagged, `rahul.sharma98@okhdfcbank` not, real biller note not punished |
| Models | Load, metrics above a floor, base value + SHAP = model output |
| Policy | Higher risk never gives a softer action; a model alone cannot block |
| Explanations | Reasons follow real SHAP order and quote real values; Hindi present for every reason |
| API | Valid, invalid, too long, unknown fields |
| Security | Script in a note cannot run; CSP; simulator controls refused from other devices; pairing code |
| Compatibility | The exact requests the Android app and extension send |
| Acceptance | One per requirement R1-R10 |
| Browser | Playwright: pay flow, alert, report loop, dashboard |

---

## 18. Demo (about 3 minutes)

Full script in `docs/DEMO_SCRIPT.md`.

1. **Story.** Sunita ji (fictional) gets a collect request: "Refund ₹2,999, approve to receive".
2. **Attack.** Press the button. The feed reacts. Her phone stops the payment and says why, in Hindi.
3. **The loop.** She reports it. The next victim's score rises because of her report.
4. **Mule.** Launch a ring. The graph lights up. A victim ignored the warning, but the mule's next hop is held:
   "₹ still recoverable".
5. **Beat the model.** A judge plays the scammer on their own phone.
6. **Honesty.** `/how`: what each layer adds, what it misses, and that it is synthetic data.

---

## 19. Team (roles still to be assigned)

| Person | Owns | Presents |
|---|---|---|
| Ajay Yadav | Scorer, policy (`decide_action`), API | Story, architecture, why |
| To assign (Abhimanyu2211 or SaloniTrivedi11) | Simulator, models, evaluation | Model card, honest numbers |
| To assign | Dashboard, alert screen | Product walk-through |
| To assign | Stream, phone and extension link | Runs the live demo |

---

## 20. Using the 24 hours at the event

| Hours | Do |
|---|---|
| 0 to 1 | Run `./run.sh test` on the venue laptop and network. Rehearse the failure plan |
| 1 to 8 | Each owner reads their code until they can explain it without notes (`docs/JUDGING_QA.md`) |
| 8 to 14 | Random-challenge rounds. Keep one person free. Add anything the judges ask for |
| 14 to 20 | Rehearse the demo at least 3 times, each person swapping to the backup role |
| 20 to 24 | Freeze the code. Rest. Keep the app running |

The PDF mentions "random-challenge rounds" but not what they contain, so we cannot prepare for them directly.
The layers are separate modules so that a new rule, feature or screen is a small change.

**Failure plan:** no venue Wi-Fi → laptop hotspot. Hotspot fails → phone frame in the laptop browser. Laptop
dies → a second laptop set up beforehand. Nothing in the demo needs the internet.

---

## 21. Risks

| Risk | Answer |
|---|---|
| "You generated the data, so your score means nothing" | Agree openly. Hard cases, time split, leave-one-out, drift, PaySim. Say what is unknown |
| Real UPI cannot be integrated in a hackathon | Say so. Everything is simulated; `/pay` says so on screen. The integration point is one API call |
| Organisers do not allow pre-built code | Section 15. Ask before the event |
| Isolation Forest may add little | Measured. Alone it is weak (PR-AUC 0.209), and on known scams XGBoost alone is slightly better than the full system. Its value, with the rules, is on scams never seen. We say all of this |
| Other teams also use XGBoost + FastAPI | The difference is context, second chance and honest evaluation |
| SMS privacy | In this demo the laptop sees the SMS. Production design: the phone scores it and sends only the score. Stated as a limit |

---

## 22. Open questions

1. **Are pre-built components allowed?** Unknown. Only the organisers can answer (section 15).
2. **What are the random-challenge rounds?** Unknown (section 20).
3. **Team:** Ajay Yadav, Abhimanyu2211 and SaloniTrivedi11, confirmed by Ajay. Roles still to be assigned (section 19).

---

## 23. Findings log

Every finding that changes the design goes here, with its evidence.

- **30 Oct 2026.** P2P collect ended by NPCI order; the PS still lists "fake collect requests". We model them as
  merchant-style collects from unverified IDs and treat a P2P collect as a hard rule.
- **30 Oct 2026.** the earlier project gives "electricity bill oct" Medium 40 and `paytm.cashback.offer@okaxis` Safe 0.
  The engine stays unchanged; a new context layer and the model's learned interactions handle these.
- **30 Oct 2026.** First model scored PR-AUC 0.99: treated as a bug, and it was. Payees under 30 days old were 0.000% of genuine
  payments and 57.5% of fraud (no genuine account ever opened during the simulation), and mules jumped to a random city on every
  transfer. Fixed: accounts now open throughout the simulation, mules stay put, paying new people is common, small shops also use
  collect and links, careful scams are smaller, and 10% of scams are unreported in training. XGBoost fell to about 0.90.
- **30 Oct 2026.** The name "Payal" was flagged as imitating PayPal (one letter away), and the surname Kotak as Kotak Bank. This comes
  from the earlier project's lookalike check, which suits websites but not people's names. In a UPI ID only a swapped character now counts.
  the earlier project also gives the real payment link `paytm.me` High 60; known payment gateways are now neutral in a payment.
- **30 Oct 2026.** One or two complaints reach 1.9% of genuine payments at 5% precision: removed as a rule. The anomaly weight was
  chosen by leaving each scam type out of training, on validation data: 0.15 keeps nearly all the benefit on scams never seen and costs
  little on known ones. Results come from two new worlds (seeds 3003 and 4004) that nothing was tuned on.
- **30 Oct 2026.** Final results, on a world nothing was tuned on: 93% of scam payments flagged, 83% stopped, 0.61% of genuine payments flagged. On known scams XGBoost alone beats the full
  system (97% against 95% recall at 1% false alarms). On scams left out of training the full system wins where words give the scam away (fake collect 10% to 81%),
  and loses a few points on mule transfers and "digital arrest". We keep the full system and report this openly: new scams are what the problem statement fears.
- **30 Oct 2026.** PaySim: 97.8% of fraud rows have an amount equal to the whole balance, against 0.0001% of genuine rows. PR-AUC 0.998 with balance columns, 0.697 without. We report the lower one.
- **30 Oct 2026.** Real fraud is about 6.8 per million, so at this budget about 965 alerts would be false per real scam. A bank would tighten the budget. This is why warnings are cheap and a model alone cannot block.
- **30 Oct 2026.** Security review: DNS rebinding could reach laptop-only controls (hostnames are now refused), any device could plant an SMS for someone else (`/api/v1/sms` now needs the pairing code, and an SMS sent with a payment counts for that payment only), and any device could answer for another person's payment (a secret token is now required, clients cannot choose payment numbers, one person's reports count once). A backslash could disguise a link as official (now normalised). The scoring API still has no login: stated as a limit.
- **30 Oct 2026.** Stream simulator, not Kafka. Correction: this first said the laptop had no Docker or Java. That check ran inside the VS Code Flatpak sandbox; the host has both. Kafka still has not been run or tested.
- **30 Oct 2026.** `ml/engine/` was moved to `ml/engine/` from outside the build session and `docs/` was removed. The
  move was kept and the config points there. Without its models the engine still answers, only worse (Critical 90 became
  High 78), and its copied tests skip silently. A new test fails loudly in that case, and training refuses to start.
- **30 Oct 2026.** The reused Android app could not scan or check a UPI payment, which is the point of the problem statement. Added QR scanning with CameraX and ML Kit. Seven reused files changed and left the manifest. A real UPI ID has no history here, so the app hides model reasons for it and never says it is safe.
- **30 Oct 2026.** Added user, merchant and admin logins, enforced by the server for the website and the phone app. This replaces the old rule that only the laptop could run the show, and closes the scoring API that had no login.
