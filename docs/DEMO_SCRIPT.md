# Demo script: about 5 minutes

For the team on stage. The dashboard goes on the projector. One person runs the laptop, one holds the phone, one talks.

Live numbers change with every run, so read them off the screen. Do not memorise them.

## Before you go up

- [ ] `./run.sh wifi` is running. Note the phone address and the pairing code it prints.
- [ ] Dashboard open on the projector at `http://127.0.0.1:8000`. The QR code appears at the bottom.
- [ ] Phone on the same Wi-Fi or hotspot, at `http://<laptop-ip>:8000/pay`, showing Sunita ji, in Hindi if the room would like that.
- [ ] A second tab on the laptop at `/how`.
- [ ] Restart the server just before going up, so the numbers on screen start from zero.
- [ ] Log in with the test login buttons: Admin on the laptop, User on the phone.
- [ ] Practise this script 3 times, with a timer, including one run where you use the backups below.
- [ ] Scan a test QR with the live camera today, so you know it works in that room's light.
- [ ] Optional: the SatarkPay app on an Android phone, with `http://localhost:8000/qr` open on the laptop. Scan "Scan to receive" to show a scam stopped live.
- [ ] Optional: the same app, paired, with SMS allowed, and a teammate ready to send a scam SMS.

## The script

**0:00 The story (Ajay).** "Sunita ji is a retired teacher in Jaipur. She is fictional, but this happens every day. A request appears on her phone: *Refund of ₹2,999, approve to receive*. It sounds like money coming in. If she enters her PIN, it goes out. In 2024-25 India reported ₹981 crore lost to UPI fraud, in 12.64 lakh incidents. And people find out after the money has gone."

**0:30 The insight (Ajay).** "Many of these scams are authorised by the victim: right phone, right PIN, right person. To a model that only reads the numbers, many look normal. So we read the money *and* the words."

**0:50 Attack 1: fake collect (one person clicks, another holds the phone).**
1. Click **Launch** on *Fake collect request*.
2. The feed and alerts react. The phone changes by itself. Hold it up.
3. Read the reasons aloud. Tap **हिंदी**. Read one in Hindi.
4. Say: "NPCI ended P2P collect requests by October 2025. Scammers now need merchant-style accounts, so a fake collect looks like this. Understanding that matters."
5. Tap **Do not pay and report it**. "That report now counts against this account for the next person."

**1:50 Why this alert (Ajay).** Click the alert on the dashboard. "These are not guesses. The bars are the model's exact SHAP values, and they add up to its output. The sentences are filled from them with the real numbers. No language model is involved, so nothing can be invented."

**2:20 Attack 2: mule ring (one person clicks).**
1. Click **Launch** on *Mule ring*.
2. "There is no note and no link to read. Only the money's behaviour gives it away."
3. Point at *Where the money went*: people on the left, the mule in the middle, the next hop on the right.
4. Point at the red next-hop line and the **Still recoverable** tile. "Some victims paid anyway. But the mule's next transfer is held, so that money can still go back. That is the second chance."

**3:00 Beat the model (hand it to the judges).** "Scan this QR code and play the scammer. Write the note, pick the UPI ID, choose the amount." Then let them try. Small amounts with innocent notes do get through, for example ₹30 by QR. Say so calmly: "Yes, that gets through, and that is deliberate. Stopping a ₹30 payment costs more trust than it saves."

**3:40 The honest numbers.** Switch to `/how`.
- "Everything is synthetic, and we wrote the simulator. How it does on real payments is unknown. We say that first."
- *Scams it has never seen*: "We trained with no fake collects at all. XGBoost alone caught 7%. The full system caught 81%. That is why there are four layers."
- *Why accuracy is the wrong number*: "A model that never flags anything is 99.999% accurate. So we measure recall at a fixed false-alarm budget."
- "Our first score was 0.99. We treated that as a bug and found two leaks in our own data. On public PaySim the score drops from 0.998 to 0.697 when you remove a shortcut in the data, and we report the lower one."

**4:20 Viability (Ajay).** "A bank or an app makes one API call before sending the payment. p95 is 5.06 ms on this laptop. It needs real data to prove itself, and a view across banks. FRI rates phone numbers and MuleHunter rates accounts. We decide on one payment and tell the person why, and we could use both as inputs."

**4:50 Close (Ajay).** "SatarkPay gives every Indian a second opinion before they pay."

## If something goes wrong

| What | Do |
|---|---|
| Phone cannot reach the laptop | Use a phone hotspot with the laptop on it. Otherwise open `/pay` on the laptop in a narrow window |
| The request does not reach the phone | Tap *A "refund" request* on the phone instead. It shows the same screen |
| Nothing moves on the dashboard | Check it says *Live*. Press **Start**. Check speed is 25 per second |
| A judge finds a miss | Good. "That is a real limit." Note it. Never argue |
| The laptop dies | Second laptop, set up beforehand. Otherwise the deck has screenshots of the same story |
| No internet | The laptop demo does not need it. Only the Vercel copy does |
| The camera will not read the QR | Use **From photo** with a screenshot of the QR saved on the phone beforehand. Save one now |
| The phone app cannot reach the laptop | Run `adb reverse tcp:8000 tcp:8000`, or use the app's address `https://satarkpay.vercel.app` under *Laptop connection* |
| The laptop's server fails | Open `https://satarkpay.vercel.app` and use the test logins. Say that it is the test copy, whose numbers can reset |
| Screen timeout during the demo | Set the phone's screen to stay on before going up |
| An attack is too quiet | Launch it again. Each launch is a new set of accounts |

## Things never to say

- "99% accurate." We do not report accuracy.
- "Nobody else does this." FRI, MuleHunter and the UPI apps' own checks exist.
- "It works on real UPI." It has not been connected to real UPI.
