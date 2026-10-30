# Reused code

SatarkPay was built for SPHINX'26 on top of code from an earlier project, SatarkAI. This page says exactly what existed before and what is new, so that the organisers can judge it.

**The PDF of problem statements does not say whether code written before the event is allowed. Ask the organisers before relying on this project at the event.**

## Reused, unchanged

From [ajayyadav432/SatarkAI](https://github.com/ajayyadav432/SatarkAI), commit `66b436a7e08b18719386351b2c709568f974e801`.
72 files. Each one is byte for byte the same as in that commit. [`reused_manifest.json`](reused_manifest.json) records its SHA-256, and `tests/test_provenance.py` fails if any of them changes.

| Where | What | Files |
|---|---|---|
| `app/analysis` | Detection engine: extraction, link checks, rules, text and URL models | 13 |
| `app/data` | Rules and brand lists | 3 |
| `ml/engine` | Trained text and URL models | 5 |
| `tests/engine` | The engine's own tests | 7 |
| `android` | SMS Guard Android app, except the 10 files listed below | 23 |
| `extension` | Link Guard browser extension | 11 |
| `demo` | Demo web pages with fake scam links | 3 |
| `app/static` | Warning page script, theme script, favicon, logo, Inter font | 6 |
| `docs/logo.svg` | Logo | 1 |

The warning page's HTML (`app/static/go.html`) came from SatarkAI with the product name and file links changed. Some styles were rewritten. `app/config.py` keeps the setting names the engine reads.

## Reused, then changed

The Android app could only read SMS. It had no camera and never checked a payment, so UPI QR scanning and a new interface were added for SPHINX'26. These 10 files came from SatarkAI and were changed: `build.gradle.kts`, `AndroidManifest.xml`, `MainActivity.kt`, `SatarkClient.kt`, `Store.kt`, `Color.kt`, `Theme.kt`, `strings.xml`, `themes.xml`, `libs.versions.toml`. The SMS checking itself still works the same way. `UpiQr.kt`, `QrScanner.kt`, `PayScreens.kt`, `Ui.kt` and the tests are new.

## New for SPHINX'26

| What | Where |
|---|---|
| UPI world simulator with 7 scam types and hard cases | `ml/simulate.py` |
| Training, evaluation, PaySim benchmark, load test | `ml/`, `scripts/` |
| Feature store, including mule signals | `app/payments/features.py` |
| Payment knowledge the engine lacks: "act to receive" notes, UPI ID checks, payment gateways | `app/payments/context.py` |
| XGBoost and Isolation Forest models | `models/` |
| Hard rules, risk formula, policy, explanations in two languages | `app/payments/rules.py`, `models.py`, `policy.py`, `explain.py` |
| Live stream, attacks, money network, alert store | `app/payments/live.py`, `scenarios.py`, `graph.py`, `store.py` |
| Scoring API | `app/main.py` |
| Dashboard, alert screen, merchant view, model card | `app/static/` |
| Tests for all of the above | `tests/` (not `tests/engine/`) |

## Known bugs found in the reused engine, left unchanged

These were found while building SatarkPay, and are handled in `app/payments/context.py`, not in the engine.

- The lookalike check flags the name "Payal" as imitating PayPal. Fine for a website, wrong for a person.
- The real payment link `paytm.me` scores High 60.
- The genuine note "electricity bill oct" scores Medium 40.
- `https://evil.com\@sbi.co.in/` reads as the official site `sbi.co.in`, while a browser opens `evil.com`. Backslashes are now turned into slashes before the engine sees a link.
