# Judging preparation

Questions a judge is likely to ask, with answers checked against the code and `models/metrics.json`. Facts about India are press-reported; sources are at the end.

## The problem

**Why is this hard?** Many UPI scams are authorised by the victim: right phone, right PIN, right person. A model that only sees numbers can see a normal payment. The give-away is often what the person was just told.

**How big is it?** Reported UPI fraud, Lok Sabha reply of 15 Dec 2025: FY24 ₹1,087 crore in 13.42 lakh incidents; FY25 ₹981 crore in 12.64 lakh; FY26 up to November ₹805 crore in 10.64 lakh. UPI handled about 185.8 billion transactions in FY25, so reported fraud is about 6.8 per million. Reports undercount the real amount.

**The problem statement says "fake collect requests", but didn't NPCI end those?** Yes for person-to-person: a circular of 29 July 2025 stopped P2P collect by 1 October 2025. Merchant collect continues. So the scam moved to merchant-style accounts, QR codes and payment links, and that is how we model it. A P2P collect that still arrives is a hard rule.

## The data

**You wrote the data yourself. Doesn't that make your score meaningless?** It limits what the score can prove, and we say so first. The simulator holds hard cases on purpose: genuine things that look like fraud, and careful scams that look normal. Test scammers are new accounts. A whole test world was untouched during tuning. We remove one scam type from training to test new scams. We also ran the recipe on public PaySim. Real-world performance is still unknown.

**Why not train only on a public dataset?** The PS allows either. Public data such as PaySim has no notes, links, devices or collect requests, so it cannot show R1 or R2. We use it as a check, not as the live model.

**What is in the simulator?** About 15,000 users and 2,000 shops over 45 days. Normal life by segment: student, salaried, gig worker, elder, shop owner. Seven scam types. Hard cases: trip pooling, shop owners on personal UPI IDs, first rent, new phones, travel, fairs, new shops, alarming bill reminders, parents sending fees. 40% of scams are careful, and 10% of scam accounts are unreported in training, because in real data they look genuine.

**Why was your first score so high?** The first PR-AUC was 0.99, and we treated it as a bug. Two leaks: payees under 30 days old were 0.000% of genuine payments and 57.5% of fraud, because no genuine account ever opened during the simulation; and mules jumped to a random city on every transfer. Both were fixed. XGBoost's PR-AUC is now 0.940 on the test set.

**What did you find in PaySim?** In 97.8% of its fraud rows the amount equals the sender's whole balance, against 0.0001% of genuine rows. With balance columns the PR-AUC is 0.998, without them 0.697. The second is the one to trust. Isolation Forest with no labels gets 0.328.

## The models

**Which algorithms?** XGBoost (supervised, known patterns), Isolation Forest (unsupervised, unusual payments), and the context engine (rules, a URL model and a text model) for the words. Hard rules state plain facts.

**Why both XGBoost and Isolation Forest?** XGBoost is strong on what it has seen and exactly explainable. Isolation Forest needs no labels. Honestly, the forest alone is weak: PR-AUC 0.209. And on known scams XGBoost alone is slightly better than the full system: 97% against 95% recall at 1% false alarms. The value appears on scams never seen: with no fake collects in training, XGBoost alone catches 7% and the full system 81%.

**What features?** 48, in four groups. Payer behaviour: amount against usual, new payee, new phone, jump in place, velocity. The account's own money moves: forwarding what just arrived. Payee signals: fan-in, first-time payers, pass-through, age, collects declined, reports. Context: note, link, UPI ID, recent SMS.

**How do features stay the same in training and live?** One class, `FeatureStore`, does both. A payment is scored first and recorded after, so it can never see itself or the future. Both are tested.

**How is the score calculated?** `risk = 1 - (1 - p)(1 - a)(1 - r1)(1 - r2)...`. More evidence never lowers it. The risk is then placed on 0 to 100 using bands measured on validation data, so that a level has a known meaning: 1% of genuine payments reach Medium.

**Why not an LLM?** Explanations must be exact and repeatable, work offline, and be impossible to talk out of. A scam note could carry instructions to a language model. Templates filled from SHAP values cannot invent a reason.

**How is the explanation exact?** XGBoost's TreeSHAP: base value + the sum of contributions = the model's output, tested. Contributions are added per reason group and ranked by real size. For the Isolation Forest, we describe which value is furthest beyond normal payments. That describes the payment, not the forest's internals, and the wording says so.

## New scams and clever scammers

**What about a scam you have never seen?** We measure it. Each row trains with no example of that scam, at a fixed 1% false-alarm budget.

| Left out of training | XGBoost alone | Full system |
|---|---|---|
| Fake collect request | 7% | 81% |
| Phishing link | 37% | 73% |
| "Scan to receive" QR | 27% | 66% |
| Payment to a mule | 84% | 83% |
| Mule moving money on | 79% | 73% |
| Account takeover | 59% | 81% |
| "Digital arrest" transfer | 94% | 90% |

Where the words give it away, the other layers save it. Where only behaviour does, XGBoost still generalises, and the other layers add little or cost a few points. Mule transfers and "digital arrest" are the cases where the full system is a little worse.

**What if scammers get smarter?** In a world where 90% of scams are careful, with no retraining: 76% flagged, 61% stopped. It degrades, and it does not collapse. Careful scams are our weakest area.

**What gets through?** Small amounts with innocent notes to accounts that look ordinary. Careful mules on older rented accounts. Retraining on analyst labels is the answer to the rest.

**Can a scammer read your rules and avoid them?** They can avoid the words. They cannot easily avoid how the money moves: to get paid, an account must receive money from strangers and move it on.

## False alarms

**How many genuine payments get flagged?** 0.59% flagged, 0.04% stopped, on the test set.

| Situation | Payments | Flagged | Stopped |
|---|---|---|---|
| Large emergency transfer to a known person | 284 | 14.79% | 3.52% |
| First rent payment to a new person | 320 | 13.44% | 0.94% |
| Pooling money for a trip, then paying once | 1,078 | 10.39% | 0.83% |
| Parent sends money, student pays the fee an hour later | 2,258 | 6.24% | 0.40% |
| First big purchase at a new merchant | 522 | 4.60% | 0.00% |
| Travelling to another city | 923 | 2.60% | 0.00% |
| A genuine note saying refund | 2,254 | 2.17% | 0.35% |
| A newly opened shop | 3,037 | 2.11% | 0.00% |
| A shop's very busy day at a fair | 3,520 | 0.60% | 0.00% |
| Shop owner on a personal UPI ID | 16,864 | 0.46% | 0.01% |
| All payments to merchants | 2,77,286 | 0.34% | 0.00% |
| New phone | 330 | 0.30% | 0.30% |
| Small unverified merchants | 1,68,375 | 0.29% | 0.00% |
| Alarming bill reminder, then the real bill payment | 1,123 | 0.18% | 0.00% |

**Isn't a shop full of first-time customers just like a mule?** That is why those cases are in the simulator. Shops and shop owners on personal IDs have older accounts, repeat customers and money that does not leave at once. See the table.

**What does real-world false-alarm cost look like?** If real fraud is 6.8 per million and the model were this good, which is unproven: about 929 false alarms per real scam for any alert, and 70 for a hold. That is why a warning is cheap, why blocks need two layers, and why a person always has a way out. A bank would tighten the budget:

| Budget: genuine payments flagged | Recall, full system | Recall, XGBoost alone |
|---|---|---|
| 0.01% | 79% | 77% |
| 0.10% | 89% | 89% |
| 0.50% | 93% | 95% |
| 1.00% | 95% | 97% |

**What if we wrongly stop someone?** The screen says why and gives a way to appeal: the bank can review and release. MediaNama reported this as the worry with FRI: being blocked "with no explanation or recourse". Analyst decisions become labels for the next training. Blocked genuine payments in the test: 1, which is too few to be precise.

**Why not just block everything suspicious?** Because most alerts would be false. See above.

## Mules

**How do you spot a mule?** As a payee: many strangers paying in, young account, money leaving quickly. As a payer: forwarding what just arrived, several accounts on one phone.

**What is the "second chance"?** If a victim pays anyway, the mule's next transfer is scored too. If it is held, the money can still be recovered. The simulator really stops that transfer: the next account never receives it.

**A single bank can't see other banks' accounts. How does this work?** It cannot, and we state that as a limit. Payee signals need a view across banks, which points to a deployment at the network level. The first row of the layer table shows what is left without them: PR-AUC 0.496.

## Engineering

**Does the phone app scan real UPI QR codes?** Yes, it reads the QR on the phone and checks the payment on the laptop. It does not pay. A real UPI ID has no history here, so only the ID, the amount and the note are checked, and the app tells the person that this is not a guarantee.

**How good is it on QR codes?** Weaker than the headline numbers, and we measured that separately. On a hand-written set, it flagged 13 of 20 scam QRs and stopped 7, and flagged 1 of 20 safe ones. It misses prize and lottery wording and plain payments with no words. Do not quote the main numbers for QR scans.

**Does it pay real money?** It never moves money itself. For a real UPI ID it can open the person's own UPI app, and they approve with their PIN there. Say whether you have tested this: UPI apps can refuse requests from other apps.

**Why is the test login open to anyone?** So judges can try each portal in one click. It only reaches simulated data, and one setting turns it off.

**Who can see what?** Three logins: user, merchant and admin. The server checks every request, so a user who calls the admin API directly gets refused. They are demo accounts: one for each role, with hashed passwords.

**Why no Kafka?** The PS allows a simple stream simulator, and a stream simulator keeps the demo on one laptop with nothing else to install. A small `Bus` class is where Kafka would go. That has not been tested, and we do not claim it.

**How fast is it?** On this laptop, one server process: p50 2.27 ms, p95 5.06 ms, p99 6.98 ms over HTTP; 483 requests per second with 4 clients. Alerts take longer because they compute SHAP (p95 7.36 ms). It says nothing about a bank's production load.

**Is the demo real?** The models, scoring, stream and decisions are real. The payments are simulated. Stopping a payment really changes what happens next in the simulation.

**Privacy?** Everything runs on one laptop. In this demo the laptop reads the SMS. The production design scores it on the phone and sends only the score.

**Security?** Text from notes is always shown as plain text, tested with a script in a note. There is a strict content security policy. Only the laptop can run attacks or label alerts. Phones need a pairing code to send SMS. A real deployment would need authentication on the scoring API: this demo leaves it open on purpose, on a local network.

**How do you test it?** Over 400 automated tests: unit, feature parity, API, security, one acceptance test per requirement, and real-browser tests of the whole story. `./run.sh test`.

## Viability

**Who would use it?** A bank or an app, one API call before sending the payment. Banks get the analyst console. Small merchants see what really arrived. Consumers get the alert.

**How does it differ from FRI and MuleHunter?** The DoT's Financial Fraud Risk Indicator rates phone numbers. RBI's MuleHunter.AI finds mule accounts. SatarkPay decides on one payment and tells the person why. Both could be inputs. Do not claim nobody else does this.

**What would you need next?** Consented real data, to learn how good it is. A view across banks. A pilot in warn-only mode, to measure false alarms before stopping anything.

## Community and languages

**Can a group get an honest shop blocked by reporting it?** No. Reports from 3 accounts only add a warning that says the reports are not verified. Only an admin can block. One account counts once. Fake accounts could still raise a warning, which is a known limit: sign-up has no identity check.

**Are the posts in the feed real?** No. An empty feed starts with 6 made-up posts, each marked Sample, with invented IDs. We say so.

**Why do you hide part of the UPI ID in the feed?** A report is an accusation nobody has checked, and a UPI ID often contains a phone number.

**Why no cashback or offers comparison?** Our focus is security. We have no real offer data and would not invent any. It could come later, using offers published by the apps.

**Do you send SMS to the cloud?** No. Incoming SMS go only to the team's laptop. In online mode they are not sent anywhere, and a person can paste a message to check it.

**Are the translations checked?** Not yet by native speakers. All numbers and names in a reason come from the same real values as the English.

## Who answers what

Everyone should know the one-sentence pitch, the formula, why no LLM, and that the data is synthetic.

| Person | Owns | Read these | Must explain without notes |
|---|---|---|---|
| Ajay Yadav | Story, architecture, policy | `app/payments/scorer.py`, `policy.py`, `rules.py`, `app/main.py` | The formula; why a model alone cannot block; the real-world false-alarm number |
| To assign | Simulator, models, evaluation | `ml/simulate.py`, `train.py`, `evaluate.py`, `app/payments/features.py`, `models.py` | The two leaks; leave-one-out; PaySim's shortcut; why XGBoost beats the full system on known scams |
| To assign | Dashboard, alert screen | `app/static/`, `app/payments/explain.py` | What each part of the screen means; how a reason is built from SHAP; why no text can run code |
| To assign | Stream, sensors, running the demo | `app/payments/live.py`, `scenarios.py`, `graph.py`, `android/`, `extension/` | How stopping a payment changes the simulation; the failure plan; why no Kafka |

## Sources

- [Angel One: NPCI to end P2P collect](https://www.angelone.in/news/market-updates/npci-to-end-upi-person-to-person-collect-requests-from-october-to-curb-fraud)
- [Business Standard: what changes with collect requests](https://www.business-standard.com/finance/personal-finance/upi-collect-requests-to-end-from-october-here-s-how-it-changes-payments-125081500767_1.html)
- [IANS: UPI fraud figures, Lok Sabha, 15 Dec 2025](https://ianslive.in/upi-frauds-worth-rs-805-crore-witnessed-this-fiscal-so-far-minister--20251215175703)
- [Business Standard: UPI volume in FY25](https://www.business-standard.com/finance/news/upi-s-contribution-to-payments-ecosystem-volume-grows-to-83-4-in-fy25-125052900871_1.html)
- [MediaNama: Financial Fraud Risk Indicator](https://www.medianama.com/2025/05/223-dot-financial-fraud-risk-indicator-upi/)
- [Business Standard: MuleHunter.AI](https://www.business-standard.com/finance/personal-finance/explained-rbi-is-using-an-ai-tool-mulehunter-ai-to-cut-down-digital-frauds-124120900250_1.html)
