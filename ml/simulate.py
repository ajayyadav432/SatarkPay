"""A small fake India: users, shops and scammers. It trains the models and feeds the live demo.

Everything is made up. Every UPI ID ends in @sim..., so a simulated "mule" can never match a real person.
The label of a payment (label, typology) is never shown to the models; only the training script reads it.

The world is a discrete-event simulation that can be resumed:

    world = World(WorldConfig(seed=42))
    while (ev := world.next_event()) is not None:
        ...                        # score it, if you want
        world.commit(ev)           # let it happen: moves money, may trigger a mule's next transfer

commit(ev, moved=False) means the payment was stopped, so the money stays where it was. That is how the live
demo shows a held mule transfer: the scammer's next hop simply never happens.
"""
from __future__ import annotations

import bisect
import heapq
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from app.payments.geo import CITIES, km_between  # noqa: F401  (km_between is re-exported for the tests)

IST = timezone(timedelta(hours=5, minutes=30))
START_TS = datetime(2026, 8, 15, tzinfo=IST).timestamp()
DAY = 86400.0
HOUR = 3600.0
MINUTE = 60.0
UPI_LIMIT = 100_000.0   # the usual per-transaction limit for a person-to-person UPI payment

HANDLES = ["simsbi", "simhdfc", "simicici", "simaxis", "simybl", "simpaytm", "simkotak", "simpnb"]

FIRST_NAMES = ("aarav vivaan aditya arjun rohan rahul amit ankit deepak suresh ramesh manoj vikas sanjay nitin karan "
               "harsh yash kunal mohit priya neha pooja anjali sunita kavita rekha meena shreya divya nisha ritu "
               "swati payal komal geeta lata asha sneha tanvi isha").split()
LAST_INITIALS = "a b c d g j k m n p r s t v y".split()

#            segment      share  rate/day  usual ₹  night share  monthly income ₹
SEGMENTS = [("student",    0.25,  0.95,     150,     0.10,        8_000),
            ("salaried",   0.35,  1.10,     450,     0.03,        55_000),
            ("gig",        0.15,  1.25,     200,     0.25,        22_000),
            ("elder",      0.12,  0.40,     350,     0.01,        30_000),
            ("shop_owner", 0.13,  0.45,     900,     0.02,        40_000)]

#                category    share  usual ₹  verified  collect  link  online  names
MERCHANT_KINDS = [("kirana",    0.30,   180,  0.25,  0.01, 0.01, False, ["kirana", "general.store", "provision", "supermart"]),
                  ("food",      0.22,   220,  0.40,  0.06, 0.06, False, ["cafe", "tiffin", "dhaba", "chaat", "bakery", "sweets"]),
                  ("pharmacy",  0.08,   300,  0.50,  0.00, 0.00, False, ["medical", "pharmacy", "chemist"]),
                  ("fuel",      0.05,   800,  0.80,  0.00, 0.00, False, ["petrol", "fuels"]),
                  ("services",  0.22,   500,  0.20,  0.08, 0.12, False, ["salon", "tailor", "repair", "tutor", "clinic", "laundry"]),
                  ("ecommerce", 0.06,  1200,  0.70,  0.40, 0.50, True,  ["shopkart", "bazaarone", "quickmart", "fashionhub"]),
                  ("biller",    0.02,   900,  1.00,  0.30, 0.30, True,  ["electricity.board", "gas.agency", "broadband", "water.board", "mobile.recharge"]),
                  ("travel",    0.03,  2500,  0.80,  0.30, 0.50, True,  ["rail.booking", "flights", "busbooking", "holidays"]),
                  ("education", 0.02,  3000,  0.60,  0.20, 0.30, True,  ["college.fees", "coaching", "school.fees"])]

# Real, official sites and real payment-gateway domains. A genuine merchant's link must not look like a scam.
GENUINE_LINKS = {
    "ecommerce": ["https://www.amazon.in/gp/buy/pay", "https://www.flipkart.com/checkout/pay", "https://rzp.io/l/{r}", "https://paytm.me/{r}"],
    "biller": ["https://www.airtel.in/pay", "https://www.jio.com/selfcare/pay", "https://www.bsesdelhi.com/pay/{r}"],
    "travel": ["https://www.irctc.co.in/nget/payment", "https://www.makemytrip.com/pay/{r}", "https://rzp.io/l/{r}"],
    "education": ["https://rzp.io/l/{r}", "https://payments.cashfree.com/forms/{r}"],
    "food": ["https://rzp.io/l/{r}"],
    "kirana": ["https://rzp.io/l/{r}", "https://paytm.me/{r}"],
    "services": ["https://rzp.io/l/{r}", "https://paytm.me/{r}"],
}

FRIEND_NOTES = ["dinner", "chai", "thanks", "movie", "lunch", "party share", "cab share", "return", "kharcha", "fees",
                "medicine", "gift", "recharge", "khana", "dawai", "udhaar wapas", "ghar ka kharcha", "petrol", "book"]
REFUND_NOTES = ["refund for dinner", "refund", "returning your money", "paisa wapas", "ticket refund"]
BILL_NOTES = ["electricity bill oct", "bijli bill", "gas bill", "broadband bill", "water bill", "mobile recharge"]
RENT_NOTES = ["rent", "kiraya", "room rent", "october rent", "pg rent", ""]
GENUINE_SMS = ["Your {biller} bill of Rs {a} is generated. Pay via the official app or {link} before the due date to avoid late fee.",
               "Reminder: your electricity bill of Rs {a} is due soon. Pay on the official app or website. Ignore if already paid."]

BRANDS = ["sbi", "hdfc", "icici", "paytm", "phonepe", "gpay", "axisbank", "kotak", "pnb", "amazon", "flipkart", "airtel", "jio"]
BRAND_NAMES = {"sbi": "SBI", "hdfc": "HDFC Bank", "icici": "ICICI", "paytm": "Paytm", "phonepe": "PhonePe", "gpay": "Google Pay",
               "axisbank": "Axis Bank", "kotak": "Kotak", "pnb": "PNB", "amazon": "Amazon", "flipkart": "Flipkart",
               "airtel": "Airtel", "jio": "Jio"}
LURE_VPAS = ["refund-{b}", "{b}.kyc.update", "{b}-refund.help", "{b}.cashback{n}", "kyc.verify.{b}", "prize.kbc{n}", "lucky.draw{n}",
             "electricity.bill.help", "bill.pay.center{n}", "customer.care.{b}", "cashback.offer{n}", "{b}.reward.points",
             "govt.subsidy{n}", "pm.kisan.help{n}", "loan.approval{n}"]
PLAIN_SHOPS = ["rk.traders{n}", "shree.enterprises{n}", "mahadev.store{n}", "a1.services{n}", "om.sai.agency{n}", "new.india.mart{n}",
               "balaji.traders{n}", "krishna.stores{n}"]

COLLECT_LURES = ["Refund of Rs {a} approve to receive", "Approve to get cashback Rs {a}", "KBC prize claim fee", "Electricity bill pending pay now",
                 "KYC update fee", "Aapka refund {a} approve karein", "Enter UPI PIN to receive Rs {a}", "Cashback Rs {a} approve now",
                 "Lucky draw winner processing fee", "Pending challan Rs {a}", "Accept to receive money", "Bijli bill baki hai turant bhugtan karein",
                 "रिफंड पाने के लिए स्वीकार करें", "Your account will be blocked pay KYC fee"]
NEUTRAL_NOTES = ["payment", "invoice {n}", "order {n}", "bill", "", "", "", "advance", "charges"]
SMS_SCAMS = ["Dear customer, your {B} account will be blocked today. Update your KYC immediately: {link}",
             "{B}: Your KYC has expired. Complete it here {link} or your account will be suspended.",
             "Your electricity connection will be cut tonight. Pay pending bill of Rs {a}: {link}",
             "India Post: your parcel is held due to incomplete address. Pay Rs {a} redelivery fee: {link}",
             "Congratulations! You won Rs 25,00,000 in KBC lucky draw. Pay processing fee: {link}",
             "आपका {B} खाता आज बंद हो जाएगा। तुरंत KYC अपडेट करें: {link}",
             "Aapka {B} account band ho jayega. Turant KYC update karo: {link}",
             "Your {B} reward points worth Rs {a} expire today. Redeem now: {link}"]
SMS_STEALTH = ["Hi, payment link for your order: {link}", "Your pending payment of Rs {a}: {link}", "Please complete the balance payment here {link}"]
PHISH_WORDS = ["kyc-update", "secure-verify", "reward-points", "netbanking-login", "pay-bill", "account-verify", "refund-claim"]
PHISH_TLDS = ["xyz", "top", "click", "online", "site", "info", "in", "com", "co.in"]
LINK_NOTES = ["KYC fee", "verification", "redelivery charge", "", "processing fee", "bill payment", ""]
QR_NOTES = ["", "", "scan to receive", "receive payment", "OLX payment", "advance", "Scan karo paise milenge"]
OFFPLATFORM_NOTES = ["", "", "", "task", "deposit", "joining fee", "investment", "loan fee", "trading", "registration"]
COACHED_NOTES = ["", "", "", "verification", "legal", "security deposit", "RBI safe account"]

PERSONAS = {
    "sunita": {"vpa": "sunita.sharma@simsbi", "segment": "elder", "city": 0, "median": 400.0, "rate": 0.7, "balance": 240_000.0},
    "rahul": {"vpa": "rahul.k482@simhdfc", "segment": "student", "city": 0, "median": 150.0, "rate": 1.2, "balance": 9_000.0},
    "priya": {"vpa": "priya.nair77@simicici", "segment": "salaried", "city": 3, "median": 500.0, "rate": 1.2, "balance": 85_000.0},
}
PERSONA_SHOP = "ramesh.kirana@simaxis"


@dataclass
class WorldConfig:
    seed: int = 42
    days: int = 45
    n_users: int = 15_000
    n_merchants: int = 2_000
    stealth: float = 0.40           # share of scams that try to look normal
    late_joiners: float = 0.08      # genuine users and shops that open their account during the simulation
    sms_sensor_share: float = 0.50  # users with the SMS app; nobody else's messages are visible
    balance_known_share: float = 0.85  # a bank knows the balance; a third-party app may not
    # Scam campaigns per day, for 15,000 users (scaled with n_users)
    rate_fake_collect: float = 0.45
    rate_phishing: float = 0.90
    rate_qr: float = 0.35
    rate_mule_inflow: float = 0.50
    rate_takeover: float = 1.20
    rate_coached: float = 0.60
    background_scams: bool = True   # False: a calm world for the live demo's quiet start
    skip_typologies: tuple = ()     # used to test what happens when a scam type is new


@dataclass
class User:
    vpa: str
    segment: str
    city: int
    device: str
    rate: float
    median: float
    hours: list
    friends: list = field(default_factory=list)
    shops: list = field(default_factory=list)
    online: list = field(default_factory=list)
    informal: list = field(default_factory=list)
    landlord: str | None = None
    rent: float = 0.0
    rent_day: int = 0
    income: float = 0.0
    income_day: int = 0
    sms_sensor: bool = False
    balance_known: bool = True
    phone_change: float | None = None
    new_device: str | None = None
    trip: tuple | None = None


@dataclass
class Merchant:
    vpa: str
    category: str
    city: int
    median: float
    verified: bool
    collect_p: float
    link_p: float
    online: bool
    popularity: float


@dataclass
class Mule:
    vpa: str
    layer: int
    next_hops: list
    stealth: bool
    device: str
    city: int = 0
    pool: float = 0.0
    pending: bool = False
    forwarded: int = 0


class World:
    def __init__(self, cfg: WorldConfig | None = None):
        self.cfg = cfg or WorldConfig()
        self.rng = np.random.default_rng(self.cfg.seed)
        self._heap: list = []
        self._seq = 0
        self._txn_no = 0
        self._next_day = 0
        self._scale = self.cfg.n_users / 15_000
        self.directory: dict[str, dict] = {}
        self.users: dict[str, User] = {}
        self.user_list: list[User] = []
        self.merchants: list[Merchant] = []
        self.balance: dict[str, float] = {}
        self.mules: dict[str, Mule] = {}
        self._used_as_mule: set[str] = set()
        self._cancelled: set[str] = set()
        self._vpa_seen: set[str] = set()
        self._build()

    # --- small random helpers ------------------------------------------------------

    def _pick(self, items):
        return items[int(self.rng.random() * len(items))]

    def _chance(self, p: float) -> bool:
        return self.rng.random() < p

    def _lognormal(self, median: float, sigma: float) -> float:
        return float(median * math.exp(sigma * self.rng.standard_normal()))

    def _rand_id(self, n: int = 6) -> str:
        return "".join(self._pick("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(n))

    def _new_vpa(self, local: str | None = None, handle: str | None = None) -> str:
        while True:
            if local is None:
                base = f"{self._pick(FIRST_NAMES)}.{self._pick(LAST_INITIALS)}{int(self.rng.integers(10, 9999))}"
            else:
                base = local
            vpa = f"{base}@{handle or self._pick(HANDLES)}"
            if vpa not in self._vpa_seen:
                self._vpa_seen.add(vpa)
                return vpa
            local = None if local is None else f"{local}{int(self.rng.integers(10, 99))}"

    def _hour_table(self, night_share: float) -> list:
        day = np.array([0.2, 0.1, 0.05, 0.05, 0.1, 0.3, 0.8, 1.6, 2.6, 3.4, 4.0, 4.4, 4.8, 4.4, 3.8, 3.6, 3.8, 4.4, 5.4, 6.4, 6.6, 5.4, 3.2, 1.2])
        night = np.array([4.0, 4.0, 3.5, 3.0, 2.5, 1.5, 0.8, 0.6, 0.6, 0.8, 1.0, 1.2, 1.4, 1.4, 1.4, 1.5, 1.6, 2.0, 2.4, 2.8, 3.2, 3.6, 4.0, 4.2])
        mix = day / day.sum() * (1 - night_share) + night / night.sum() * night_share
        return np.cumsum(mix / mix.sum()).tolist()

    # --- building the world ----------------------------------------------------------

    def _build(self) -> None:
        cfg, rng = self.cfg, self.rng
        shares = np.array([m[1] for m in MERCHANT_KINDS])
        cats = rng.choice(len(MERCHANT_KINDS), size=cfg.n_merchants, p=shares / shares.sum())
        for k in cats:
            cat, _, med, ver, coll, link, online, names = MERCHANT_KINDS[int(k)]
            vpa = self._new_vpa(f"{self._pick(names)}.{self._pick(FIRST_NAMES)}{int(rng.integers(1, 999))}")
            m = Merchant(vpa, cat, int(rng.integers(len(CITIES))), self._lognormal(med, 0.5), self._chance(ver), coll, link, online,
                         float(rng.pareto(1.3) + 0.2))
            self.merchants.append(m)
            self.directory[vpa] = {"created": self._created_ts(30, 3000), "merchant": True, "verified": m.verified, "category": cat}
        shop = Merchant(PERSONA_SHOP, "kirana", 0, 180.0, False, 0.0, 0.0, False, 6.0)
        self.merchants.append(shop)
        self._vpa_seen.add(PERSONA_SHOP)
        self.directory[PERSONA_SHOP] = {"created": START_TS - 900 * DAY, "merchant": True, "verified": False, "category": "kirana"}
        self.persona_shop = shop

        self._local_by_city: dict[int, list[Merchant]] = {c: [] for c in range(len(CITIES))}
        self._online = [m for m in self.merchants if m.online]
        self._billers = [m for m in self.merchants if m.category == "biller"] or self._online
        self._travel = [m for m in self.merchants if m.category == "travel"] or self._online
        for m in self.merchants:
            if not m.online:
                self._local_by_city[m.city].append(m)

        seg_p = np.array([s[1] for s in SEGMENTS])
        seg_idx = rng.choice(len(SEGMENTS), size=cfg.n_users, p=seg_p / seg_p.sum())
        tables = {}
        for persona in PERSONAS.values():
            seg = next(s for s in SEGMENTS if s[0] == persona["segment"])
            u = self._new_user(seg, persona["vpa"], persona["city"], persona["median"], persona["rate"], tables)
            u.sms_sensor, u.balance_known = True, True
            self.balance[u.vpa] = persona["balance"]
        for i in seg_idx:
            self._new_user(SEGMENTS[int(i)], None, int(rng.integers(len(CITIES))), None, None, tables)

        by_city: dict[int, list[User]] = {c: [] for c in range(len(CITIES))}
        for u in self.user_list:
            by_city[u.city].append(u)
        self._users_by_city = by_city
        self._shop_owners = [u for u in self.user_list if u.segment == "shop_owner"]
        self._shop_owners_by_city = {c: [u for u in us if u.segment == "shop_owner"] for c, us in by_city.items()}

        for u in self.user_list:
            local = self._local_by_city[u.city]
            pop = [m.popularity for m in local]
            if local:
                k = min(len(local), int(rng.integers(5, 16)))
                u.shops = [local[i] for i in rng.choice(len(local), size=k, replace=False, p=np.array(pop) / sum(pop))]
            u.online = [self._pick(self._online) for _ in range(int(rng.integers(1, 4)))]
            n_friends = int(rng.integers(3, 12))
            for _ in range(n_friends):
                pool = by_city[u.city] if self._chance(0.75) and len(by_city[u.city]) > 2 else self.user_list
                f = self._pick(pool)
                if f.vpa != u.vpa:
                    u.friends.append(f.vpa)
            owners = self._shop_owners_by_city[u.city]
            if owners and self._chance(0.45):
                u.informal = [self._pick(owners).vpa for _ in range(int(rng.integers(1, 4)))]
            if u.segment in ("salaried", "student") and self._chance(0.40):
                u.landlord = self._pick(self.user_list).vpa
                u.rent = float(round(self._lognormal(11_000 if u.segment == "salaried" else 6_000, 0.4), -2))
                u.rent_day = int(rng.integers(0, 8))
            if self._chance(0.03):
                u.phone_change = START_TS + float(rng.uniform(0, cfg.days)) * DAY
                u.new_device = "dev-" + self._rand_id(8)
            if self._chance(0.08):
                start = START_TS + float(rng.uniform(0, cfg.days)) * DAY
                u.trip = (start, start + float(rng.uniform(2, 7)) * DAY, int(rng.integers(len(CITIES))))
        rahul = self.users[PERSONAS["rahul"]["vpa"]]
        sunita = self.users[PERSONAS["sunita"]["vpa"]]
        sunita.shops = [shop] + sunita.shops[:7]
        rahul.shops = [shop] + rahul.shops[:7]
        for persona in (sunita, rahul):      # the demo must not depend on a chance phone change or trip
            persona.phone_change, persona.new_device, persona.trip = None, None, None

    def _new_user(self, seg, vpa, city, median, rate, tables) -> User:
        name, _, seg_rate, seg_med, night, income = seg
        rng = self.rng
        night = night if self._chance(0.5) else night * 0.2
        key = round(night, 3)
        hours = tables.setdefault(key, self._hour_table(night))
        if vpa is None:
            vpa = self._new_vpa()
        else:
            self._vpa_seen.add(vpa)
        u = User(vpa=vpa, segment=name, city=city, device="dev-" + self._rand_id(8),
                 rate=rate if rate is not None else float(seg_rate * rng.gamma(4.0, 0.25)),
                 median=median if median is not None else self._lognormal(seg_med, 0.5), hours=hours,
                 income=self._lognormal(income, 0.35), income_day=int(rng.integers(0, 30)),
                 sms_sensor=self._chance(self.cfg.sms_sensor_share), balance_known=self._chance(self.cfg.balance_known_share))
        self.users[vpa] = u
        self.user_list.append(u)
        savings = 12.0 if name == "elder" else 2.0
        self.balance[vpa] = self._lognormal(u.income * savings * 0.25 + 500, 0.6)
        self.directory[vpa] = {"created": self._created_ts(60, 2500), "merchant": False, "verified": False, "category": name}
        return u

    def _created_ts(self, oldest_low: float, oldest_high: float) -> float:
        """Most accounts are old. Some open during the simulation, so a young account is not a scam by itself."""
        if self._chance(self.cfg.late_joiners):
            return START_TS + float(self.rng.uniform(-30, self.cfg.days - 1)) * DAY
        return START_TS - float(self.rng.uniform(oldest_low, oldest_high)) * DAY

    def _exists(self, vpa: str, ts: float) -> bool:
        d = self.directory.get(vpa)
        return d is None or d["created"] <= ts

    # --- the event queue -------------------------------------------------------------

    def _push(self, ts: float, ev: dict) -> None:
        self._seq += 1
        ev["ts"] = ts
        heapq.heappush(self._heap, (ts, self._seq, ev))

    def _txn(self, ts, payer, payee, amount, kind, device, city, note="", link=None, label=0, typology=None, tag=None, stealth=False, **extra) -> dict:
        self._txn_no += 1
        ev = {"event": "txn", "txn_id": f"T{self.cfg.seed}-{self._txn_no}", "payer": payer, "payee": payee, "amount": float(amount),
              "kind": kind, "device": device, "city": city, "note": note, "link": link, "label": label, "typology": typology, "tag": tag, "stealth": stealth}
        ev.update(extra)
        self._push(ts, ev)
        return ev

    def _day_start(self, day: int) -> float:
        return START_TS + day * DAY

    def next_event(self) -> dict | None:
        """The next event in time order. Fills in the payer's balance as it stands at that moment."""
        while True:
            while self._next_day < self.cfg.days and (not self._heap or self._heap[0][0] >= self._day_start(self._next_day)):
                self._schedule_day(self._next_day)
                self._next_day += 1
            if not self._heap:
                return None
            _, _, ev = heapq.heappop(self._heap)
            kind = ev["event"]
            if kind == "forward":
                ev = self._make_forward(ev)
                if ev is None:
                    continue
                return ev
            if kind == "outcome" and ev["txn_id"] in self._cancelled:
                self._cancelled.discard(ev["txn_id"])
                continue
            if kind == "txn":
                self._fill_amount(ev)
                if ev["amount"] < 1:
                    continue
            return ev

    def _fill_amount(self, ev: dict) -> None:
        payer = ev["payer"]
        bal = self.balance.get(payer, 0.0)
        drain = ev.pop("drain", None)
        if drain is not None:
            ev["amount"] = float(min(UPI_LIMIT, max(ev.get("min_amount", 100.0), bal * drain)))
        if ev["label"]:
            if ev["amount"] > bal:          # a scam cannot take more than is there
                ev["amount"] = float(bal)
        elif ev["amount"] > bal:            # genuine life: money came in that this small world did not simulate
            bal = ev["amount"] * float(self.rng.uniform(1.05, 4.0))
            self.balance[payer] = bal
        user = self.users.get(payer)
        known = user.balance_known if user else True
        ev["balance"] = round(bal, 2) if known else None

    def commit(self, ev: dict, moved: bool = True) -> None:
        """Let the event happen. moved=False: the payment was stopped, so no money moves."""
        kind = ev["event"]
        if kind == "txn":
            if ev["kind"] == "COLLECT":
                if not moved:
                    self._cancelled.add(ev["txn_id"])
                return
            if moved:
                self._move(ev["payer"], ev["payee"], ev["amount"], ev["ts"], ev)
        elif kind == "outcome":
            if ev["approved"] and moved:
                self._move(ev["payer"], ev["payee"], ev["amount"], ev["ts"], ev)
            elif not ev["approved"] and ev.get("label") and self._chance(0.05):
                self._push(ev["ts"] + float(self.rng.uniform(5, 120)) * MINUTE, {"event": "report", "payee": ev["payee"], "label": 1})

    def _move(self, payer: str, payee: str, amount: float, ts: float, ev: dict) -> None:
        self.balance[payer] = max(0.0, self.balance.get(payer, 0.0) - amount)
        self.balance[payee] = self.balance.get(payee, 0.0) + amount
        mule = self.mules.get(payee)
        if mule is not None:
            mule.pool += amount
            if not mule.pending and mule.next_hops and mule.pool >= 1000:   # a mule moves money in batches
                mule.pending = True
                low, high = (6 * HOUR, 48 * HOUR) if mule.stealth else (20 * MINUTE, 4 * HOUR)
                self._push(ts + float(self.rng.uniform(low, high)), {"event": "forward", "mule": mule.vpa})
        if ev.get("label") and ev.get("typology") not in ("mule_layering",) and self._chance(0.30):
            self._push(ts + float(self.rng.lognormal(math.log(2 * HOUR), 1.0)), {"event": "report", "payee": payee, "label": 1})

    def _make_forward(self, ev: dict) -> dict | None:
        mule = self.mules[ev["mule"]]
        mule.pending = False
        if mule.pool < 100:
            return None
        share = float(self.rng.uniform(0.45, 0.8)) if mule.stealth else float(self.rng.uniform(0.85, 0.99))
        amount = min(UPI_LIMIT, mule.pool * share)
        mule.pool -= amount
        mule.forwarded += 1
        self._seq += 1
        self._txn_no += 1
        out = {"event": "txn", "txn_id": f"T{self.cfg.seed}-{self._txn_no}", "payer": mule.vpa, "payee": self._pick(mule.next_hops),
               "amount": float(amount), "kind": "PAY", "device": mule.device, "city": mule.city,
               "note": "" if self._chance(0.8) else self._pick(NEUTRAL_NOTES).format(n=int(self.rng.integers(100, 9999))), "link": None,
               "label": 1, "typology": "mule_layering", "tag": None, "stealth": mule.stealth, "ts": ev["ts"]}
        self.balance[mule.vpa] = max(self.balance.get(mule.vpa, 0.0), amount * 1.02)
        out["balance"] = round(self.balance[mule.vpa], 2)
        if mule.pool >= 5000 and mule.next_hops:   # a large remainder goes later
            mule.pending = True
            self._push(ev["ts"] + float(self.rng.uniform(1 * HOUR, 6 * HOUR)), {"event": "forward", "mule": mule.vpa})
        return out

    # --- normal life ----------------------------------------------------------------

    def _device_at(self, u: User, ts: float) -> tuple[str, str | None]:
        if u.phone_change is not None and ts >= u.phone_change:
            return u.new_device, ("hn_new_phone" if ts < u.phone_change + DAY else None)
        return u.device, None

    def _city_at(self, u: User, ts: float) -> tuple[int, str | None]:
        if u.trip is not None and u.trip[0] <= ts < u.trip[1]:
            return u.trip[2], ("hn_travel" if ts < u.trip[0] + DAY else None)
        return u.city, None

    def _user_day(self, u: User, day: int) -> None:
        start = self._day_start(day)
        rng = self.rng
        if day % 30 == u.income_day:
            self.balance[u.vpa] = self.balance.get(u.vpa, 0.0) + u.income
        if u.landlord and day % 30 == u.rent_day:
            ts = start + float(rng.uniform(8, 22)) * HOUR
            device, tag1 = self._device_at(u, ts)
            city, tag2 = self._city_at(u, ts)
            self._txn(ts, u.vpa, u.landlord, u.rent, "PAY", device, city, note=self._pick(RENT_NOTES), tag=tag1 or tag2 or "rent")
        for _ in range(int(rng.poisson(u.rate))):
            hour = bisect.bisect(u.hours, rng.random())
            ts = start + min(hour, 23) * HOUR + float(rng.random()) * HOUR
            if self._exists(u.vpa, ts):
                self._normal_payment(u, ts)

    def _normal_payment(self, u: User, ts: float) -> None:
        rng = self.rng
        device, tag1 = self._device_at(u, ts)
        city, tag2 = self._city_at(u, ts)
        tag = tag1 or tag2
        r = rng.random()
        if r < 0.50 and u.shops and city == u.city:
            self._merchant_payment(u, self._pick(u.shops), ts, device, city, tag)
        elif r < 0.60 and u.online:
            self._merchant_payment(u, self._pick(u.online), ts, device, city, tag)
        elif r < 0.76 and u.friends:
            amount = self._lognormal(u.median * 1.2, 0.95)
            amount = max(10.0, round(amount, -1)) if self._chance(0.7) else max(5.0, round(amount))
            roll = rng.random()
            note = "" if roll < 0.6 else self._pick(REFUND_NOTES) if roll < 0.64 else self._pick(FRIEND_NOTES)
            friend = self._pick(u.friends)
            if self._exists(friend, ts):
                self._txn(ts, u.vpa, friend, amount, "PAY", device, city, note=note, tag=tag or ("hn_note" if note in REFUND_NOTES else None))
        elif r < 0.87:
            local = self._local_by_city[city]
            if local:
                self._merchant_payment(u, self._pick(local), ts, device, city, tag or None)
        elif r < 0.91 and u.informal:
            amount = max(10.0, self._lognormal(250, 0.8))
            self._txn(ts, u.vpa, self._pick(u.informal), round(amount), "QR" if self._chance(0.7) else "PAY", device, city, tag=tag or "hn_shop")
        else:
            other = self._pick(self.user_list)
            if other.vpa != u.vpa and self._exists(other.vpa, ts):
                amount = max(10.0, round(self._lognormal(u.median * 1.5, 0.9), -1))
                self._txn(ts, u.vpa, other.vpa, amount, "QR" if self._chance(0.5) else "PAY", device, city,
                          note="" if self._chance(0.7) else self._pick(FRIEND_NOTES), tag=tag)

    def _merchant_payment(self, u: User, m: Merchant, ts, device, city, tag, amount=None, kind=None) -> None:
        if not self._exists(m.vpa, ts):
            return
        if amount is None:
            amount = max(5.0, round(self._lognormal(m.median * (u.median / 400) ** 0.3, 0.75)))
            if m.online and self._chance(0.5):        # online prices end in 99, the same amounts scammers like
                amount = max(99.0, round(amount, -2) - 1.0)
        note, link = "", None
        if kind is None:
            if self._chance(m.collect_p):
                kind = "COLLECT"
            elif self._chance(m.link_p):
                kind = "LINK"
            elif m.online:
                kind = "PAY"
            else:
                kind = "QR" if self._chance(0.8) else "PAY"
        if m.category == "biller":
            note = self._pick(BILL_NOTES)
        elif kind in ("COLLECT", "LINK") or self._chance(0.2):
            note = f"Order {int(self.rng.integers(10000, 99999))}"
        if kind == "LINK":
            options = GENUINE_LINKS.get(m.category)
            link = self._pick(options).format(r=self._rand_id()) if options else f"https://rzp.io/l/{self._rand_id()}"
        if kind == "COLLECT":
            ev = self._txn(ts, u.vpa, m.vpa, amount, "COLLECT", device, city, note=note, tag=tag)
            self._outcome(ev, ts + float(self.rng.uniform(5, 120)), self._chance(0.94))
        else:
            self._txn(ts, u.vpa, m.vpa, amount, kind, device, city, note=note, link=link, tag=tag)

    def _outcome(self, ev: dict, ts: float, approved: bool) -> None:
        self._push(ts, {"event": "outcome", "txn_id": ev["txn_id"], "payer": ev["payer"], "payee": ev["payee"], "amount": ev["amount"],
                        "approved": approved, "label": ev["label"], "typology": ev["typology"]})

    def _hard_cases(self, day: int) -> None:
        """Genuine things that look like fraud. Without these the model would only learn our scam generator."""
        rng, start = self.rng, self._day_start(day)
        s = self._scale
        for _ in range(int(rng.poisson(2.0 * s))):      # a student pools money for a trip, then pays once
            org = self._pick(self.user_list)
            friends = org.friends or [self._pick(self.user_list).vpa]
            t0 = start + float(rng.uniform(9, 21)) * HOUR
            n = int(rng.integers(8, 26))
            share = float(round(self._lognormal(2000, 0.5), -2))
            for _i in range(n):
                who = self.users.get(self._pick(friends)) if self._chance(0.8) else self._pick(self.user_list)
                if who is None or who.vpa == org.vpa:
                    continue
                ts = t0 + float(rng.uniform(0, 36)) * HOUR
                self._txn(ts, who.vpa, org.vpa, share, "PAY", *self._dev_city(who, ts), note=self._pick(["trip share", "trip", "goa trip", "tour money", ""]), tag="hn_trip_pool")
            ts = t0 + float(rng.uniform(36, 60)) * HOUR
            self._merchant_payment(org, self._pick(self._travel), ts, *self._dev_city(org, ts), "hn_trip_pool", amount=share * n * float(rng.uniform(0.7, 0.95)), kind="LINK")
        for _ in range(int(rng.poisson(40 * s))):       # a parent sends money and the student pays the fee an hour later
            parent, student = self._pick(self.user_list), self._pick(self.user_list)
            if parent.vpa != student.vpa and self._exists(student.vpa, start):
                ts = start + float(rng.uniform(9, 20)) * HOUR
                fee = float(round(self._lognormal(8000, 0.6), -2))
                self._txn(ts, parent.vpa, student.vpa, fee * float(rng.uniform(1.0, 1.15)), "PAY", *self._dev_city(parent, ts), note=self._pick(["fees", "for you", ""]), tag="hn_forward")
                t2 = ts + float(rng.uniform(10, 90)) * MINUTE
                self._merchant_payment(student, self._pick(self._online), t2, *self._dev_city(student, t2), "hn_forward", amount=fee, kind=self._pick(["PAY", "LINK", "COLLECT"]))
        young = [m for m in self.merchants if not m.online and 0 <= start - self.directory[m.vpa]["created"] < 3 * DAY]
        for m in young[:int(rng.poisson(2.0 * s)) + 1]:     # a shop that just opened: every customer is a first-time customer
            nearby = self._users_by_city[m.city]
            for _i in range(int(rng.integers(15, 50)) if nearby else 0):
                who = self._pick(nearby)
                ts = start + float(rng.uniform(9, 22)) * HOUR
                self._txn(ts, who.vpa, m.vpa, max(10.0, round(self._lognormal(m.median, 0.6))), "QR", *self._dev_city(who, ts), tag="hn_new_shop")
        for _ in range(int(rng.poisson(1.0 * s))):      # a shop has a very good day at a fair: many first-time customers
            local = self._local_by_city[int(rng.integers(len(CITIES)))]
            if not local:
                continue
            m = self._pick(local)
            nearby = self._users_by_city[m.city]
            if not nearby:
                continue
            t0 = start + float(rng.uniform(10, 16)) * HOUR
            for _i in range(int(rng.integers(60, 180))):
                who = self._pick(nearby)
                ts = t0 + float(rng.uniform(0, 6)) * HOUR
                self._txn(ts, who.vpa, m.vpa, max(10.0, round(self._lognormal(m.median, 0.5))), "QR", *self._dev_city(who, ts), tag="hn_fair")
        for _ in range(int(rng.poisson(20 * s))):       # a first big purchase at a new, genuine merchant
            who = self._pick(self.user_list)
            ts = start + float(rng.uniform(9, 23)) * HOUR
            m = self._pick(self._online)
            self._merchant_payment(who, m, ts, *self._dev_city(who, ts), "hn_big_purchase", amount=round(self._lognormal(18_000, 0.7)))
        for _ in range(int(rng.poisson(12 * s))):       # a first rent payment or a deposit to a new landlord
            who = self._pick(self.user_list)
            other = self._pick(self.user_list)
            ts = start + float(rng.uniform(9, 22)) * HOUR
            if other.vpa != who.vpa:
                self._txn(ts, who.vpa, other.vpa, round(self._lognormal(15_000, 0.5), -2), "PAY", *self._dev_city(who, ts), note=self._pick(RENT_NOTES), tag="hn_first_rent")
        for _ in range(int(rng.poisson(12 * s))):       # a parent sends a large amount to a child in an emergency
            who = self._pick(self.user_list)
            if who.friends:
                ts = start + float(rng.uniform(0, 24)) * HOUR
                self._txn(ts, who.vpa, self._pick(who.friends), round(self._lognormal(25_000, 0.6), -2), "PAY", *self._dev_city(who, ts), note=self._pick(["urgent", "emergency", "hospital", ""]), tag="hn_big_known")
        for _ in range(int(rng.poisson(40 * s))):       # a bill reminder that sounds alarming, then the genuine bill payment
            who = self._pick(self.user_list)
            biller = self._pick(self._billers)
            ts = start + float(rng.uniform(8, 21)) * HOUR
            amount = max(99.0, round(self._lognormal(900, 0.5)))
            if who.sms_sensor:
                text = self._pick(GENUINE_SMS).format(biller=biller.vpa.split(".")[0].title(), a=int(amount), link="https://www.airtel.in/pay")
                self._push(ts - float(rng.uniform(1, 12)) * MINUTE, {"event": "sms", "user": who.vpa, "sender": "JD-BILLER", "text": text, "label": 0})
            self._merchant_payment(who, biller, ts, *self._dev_city(who, ts), "hn_bill_sms", amount=amount)
        if s:
            for _ in range(int(rng.poisson(3 * s))):    # complaints against honest accounts also exist
                target = self._pick(self.merchants).vpa if self._chance(0.6) else self._pick(self.user_list).vpa
                self._push(start + float(rng.uniform(0, 24)) * HOUR, {"event": "report", "payee": target, "label": 0})
        # Shop owners on a personal UPI ID buy stock from a wholesaler: looks like a mule moving money on.
        for u in self._shop_owners:
            if self._chance(0.2):
                ts = start + float(rng.uniform(9, 19)) * HOUR
                m = self._pick(u.shops) if u.shops else self._pick(self._online)
                self._merchant_payment(u, m, ts, *self._dev_city(u, ts), "hn_shop", amount=round(self._lognormal(6000, 0.6)), kind="PAY")

    def _dev_city(self, u: User, ts: float) -> tuple[str, int]:
        return self._device_at(u, ts)[0], self._city_at(u, ts)[0]

    # --- scams ------------------------------------------------------------------------

    def _new_mule(self, layer: int, next_hops: list, stealth: bool, merchant_style=False, local=None, device=None) -> Mule:
        rented = stealth and not merchant_style and self._chance(0.6)
        if rented:                      # an ordinary person who rented out their account
            u = self._pick(self.user_list)
            for _ in range(20):
                if u.vpa not in self._used_as_mule and u.vpa not in {p["vpa"] for p in PERSONAS.values()}:
                    break
                u = self._pick(self.user_list)
            self._used_as_mule.add(u.vpa)
            m = Mule(u.vpa, layer, next_hops, stealth, u.device, u.city)
        else:
            vpa = self._new_vpa(local)
            age = float(self.rng.uniform(30, 400)) if stealth else float(self.rng.uniform(0.5, 25))
            m = Mule(vpa, layer, next_hops, stealth, device or "dev-" + self._rand_id(8), int(self.rng.integers(len(CITIES))))
            # A careful scammer rents a sub-merchant through a payment aggregator, which arrives verified.
            verified = merchant_style and stealth and self._chance(0.25)
            self.directory[vpa] = {"created": self._now_hint - age * DAY, "merchant": merchant_style, "verified": verified,
                                   "category": "shop" if merchant_style else "person"}
            self.balance[vpa] = float(self.rng.uniform(50, 800))
        self.mules[m.vpa] = m
        return m

    def _new_ring(self, stealth: bool, entries=1, merchant_style=False, local=None) -> list[Mule]:
        """Money goes entry -> second layer -> cash-out. Scammers often run several accounts on one phone."""
        shared = "dev-" + self._rand_id(8) if not stealth and self._chance(0.5) else None
        cash = self._new_mule(3, [], stealth, device=shared)
        second = [self._new_mule(2, [cash.vpa], stealth, device=shared) for _ in range(int(self.rng.integers(1, 4)))]
        hops = [m.vpa for m in second]
        first = [self._new_mule(1, hops, stealth, merchant_style, local if i == 0 else None, device=shared) for i in range(entries)]
        return first

    def _stealthy(self) -> bool:
        return self._chance(self.cfg.stealth)

    def _victim(self, elder_bias: float = 0.0) -> User:
        if elder_bias and self._chance(elder_bias):
            for _ in range(30):
                u = self._pick(self.user_list)
                if u.segment == "elder":
                    return u
        return self._pick(self.user_list)

    def _lure_local(self) -> str:
        return self._pick(LURE_VPAS).format(b=self._pick(BRANDS), n=int(self.rng.integers(10, 999)))

    def _plain_local(self) -> str:
        return self._pick(PLAIN_SHOPS).format(n=int(self.rng.integers(10, 999)))

    def launch_fake_collect(self, ts: float, victims=None, n=None, stealth=None, local=None, amount=None, note=None) -> dict:
        """A new unverified merchant-style ID blasts collect requests. P2P collect ended on 1 Oct 2025, so the
        scammer now needs a merchant-style account. Most people decline."""
        rng = self.rng
        self._now_hint = ts
        stealth = self._stealthy() if stealth is None else stealth
        local = local or (self._plain_local() if stealth or self._chance(0.4) else self._lure_local())
        mule = self._new_ring(stealth, 1, merchant_style=True, local=local)[0]
        n = n if n is not None else (int(rng.integers(5, 26)) if stealth else int(rng.integers(20, 120)))
        base = amount or self._pick([499, 999, 1499, 1999, 2499, 2999, 4999, 7500, 9999])
        lure = note if note is not None else (self._pick(NEUTRAL_NOTES) if stealth and self._chance(0.7) else self._pick(COLLECT_LURES))
        spread = float(rng.uniform(1, 6)) * HOUR
        requests = []
        for i in range(n):
            u = victims[i] if victims and i < len(victims) else self._victim(0.25)
            t = ts + float(rng.exponential(spread / 3))
            a = float(base if not stealth else max(99, round(base * rng.uniform(0.4, 1.3))))
            text = lure.format(a=int(a), n=int(rng.integers(1000, 9999)))
            ev = self._txn(t, u.vpa, mule.vpa, a, "COLLECT", *self._dev_city(u, t), note=text, label=1, typology="fake_collect", stealth=stealth)
            p = 0.15 if u.segment == "elder" else 0.05
            self._outcome(ev, t + float(rng.lognormal(math.log(4 * MINUTE), 1.0)), self._chance(p))
            requests.append(ev)
        return {"scenario": "fake_collect", "entry": mule.vpa, "ring": self._ring_of(mule), "first_request": requests[0] if requests else None}

    def _phish_domain(self, brand: str, stealth: bool) -> tuple[str, str]:
        rng = self.rng
        if stealth:
            roll = rng.random()
            if roll < 0.4:
                host = f"securepay{int(rng.integers(100, 9999))}.{self._pick(['com', 'in'])}"
            elif roll < 0.7:
                host = f"pay-{int(rng.integers(1000, 99999))}.in"
            else:
                return "https", "bit.ly/" + self._rand_id(7)
            return "https", host
        return self._pick(["http", "https"]), f"{brand}-{self._pick(PHISH_WORDS)}.{self._pick(PHISH_TLDS)}"

    def launch_phishing(self, ts: float, victims=None, recipients=None, stealth=None, brand=None) -> dict:
        """A scam SMS with a link goes out. A few people open it and pay on the fake page."""
        rng = self.rng
        self._now_hint = ts
        stealth = self._stealthy() if stealth is None else stealth
        brand = brand or self._pick(BRANDS)
        scheme, host = self._phish_domain(brand, stealth)
        link = f"{scheme}://{host}/{self._rand_id(5)}"
        mule = self._new_ring(stealth, 1, merchant_style=self._chance(0.5))[0]
        template = self._pick(SMS_STEALTH if stealth else SMS_SCAMS)
        count = recipients if recipients is not None else int(rng.integers(60, 300))
        fee = int(self._pick([10, 25, 49, 99, 199, 499, 999, 1499, 2999]))
        text = template.format(B=BRAND_NAMES[brand], link=link, a=fee)
        chosen = list(victims or [])
        payers = list(chosen)
        for _ in range(count):
            u = self._victim(0.15)
            if self._chance(0.05):
                payers.append(u)
            elif u.sms_sensor:
                self._push(ts + float(rng.uniform(0, 3)) * HOUR, {"event": "sms", "user": u.vpa, "sender": self._sms_sender(), "text": text, "label": 1})
        first = None
        for u in payers:
            t0 = ts + float(rng.uniform(0, 3)) * HOUR
            if u.sms_sensor:
                self._push(t0, {"event": "sms", "user": u.vpa, "sender": self._sms_sender(), "text": text, "label": 1})
            t = t0 + float(rng.uniform(1, 30)) * MINUTE
            amount = float(fee if self._chance(0.7) else max(fee, round(self._lognormal(1500, 1.0))))
            for hop in range(1 if self._chance(0.7) else int(rng.integers(2, 4))):
                ev = self._txn(t, u.vpa, mule.vpa, min(amount, UPI_LIMIT), "LINK", *self._dev_city(u, t), note=self._pick(LINK_NOTES),
                               link=f"{link}?pa={mule.vpa}&am={int(amount)}", label=1, typology="phishing_link", stealth=stealth)
                first = first or ev
                t += float(rng.uniform(1, 12)) * MINUTE
                amount = float(round(amount * rng.uniform(1.5, 5)))
        return {"scenario": "phishing_link", "entry": mule.vpa, "ring": self._ring_of(mule), "sms": text, "link": link, "first_request": first}

    def _sms_sender(self) -> str:
        return self._pick([f"9{int(self.rng.integers(100000000, 999999999))}", "VM-ALERTS", "AD-BANKIN", "JD-UPDATE"])

    def launch_qr(self, ts: float, victims=None, n=None, stealth=None) -> dict:
        """'Scan this QR to receive the money for your OLX item.' Scanning sends money instead."""
        rng = self.rng
        self._now_hint = ts
        stealth = self._stealthy() if stealth is None else stealth
        mule = self._new_ring(stealth, 1)[0]
        n = n if n is not None else (int(rng.integers(2, 9)) if stealth else int(rng.integers(5, 26)))
        for i in range(n):
            u = victims[i] if victims and i < len(victims) else self._victim()
            t = ts + float(rng.uniform(0, 12)) * HOUR
            amount = float(round(self._lognormal(6000 if not stealth else 1500, 0.8), -1))
            self._txn(t, u.vpa, mule.vpa, min(amount, UPI_LIMIT), "QR", *self._dev_city(u, t), note=self._pick(QR_NOTES), label=1, typology="qr_scam", stealth=stealth)
        return {"scenario": "qr_scam", "entry": mule.vpa, "ring": self._ring_of(mule)}

    def launch_mule_inflow(self, ts: float, victims=None, n=None, stealth=None, entries=None, fast=False) -> dict:
        """Job, task and investment scam victims pay a mule directly. There is no note or link to read."""
        rng = self.rng
        self._now_hint = ts
        stealth = self._stealthy() if stealth is None else stealth
        ring = self._new_ring(stealth, entries or int(rng.integers(1, 5)))
        n = n if n is not None else (int(rng.integers(2, 10)) if stealth else int(rng.integers(5, 31)))
        for i in range(n):
            u = victims[i] if victims and i < len(victims) else self._victim(0.1)
            mule = self._pick(ring)
            t = ts + (float(rng.uniform(0, 1.5)) * HOUR if fast else float(rng.uniform(0, 48)) * HOUR)
            amount = float(max(100, round(u.median * rng.uniform(0.5, 3)))) if stealth else float(round(self._lognormal(5000, 0.9), -1))
            note = self._pick(OFFPLATFORM_NOTES)
            for _hop in range(1 if fast else int(rng.integers(1, 5))):
                self._txn(t, u.vpa, mule.vpa, min(amount, UPI_LIMIT), "PAY", *self._dev_city(u, t), note=note, label=1, typology="mule_inflow", stealth=stealth)
                t += float(rng.uniform(2, 48)) * HOUR
                amount = float(round(amount * rng.uniform(1.2, 2.5)))
        return {"scenario": "mule_inflow", "entry": ring[0].vpa, "entries": [m.vpa for m in ring], "ring": self._rings_of(ring)}

    def launch_takeover(self, ts: float, victim: User | None = None, stealth=None) -> dict:
        """SIM swap: a new phone, often in another city, at night, and quick payments. The stealth version is a
        remote-access app: same phone, same place."""
        rng = self.rng
        self._now_hint = ts
        stealth = self._stealthy() if stealth is None else stealth
        u = victim or self._victim(0.15)
        ring = self._new_ring(stealth, int(rng.integers(1, 4)))
        if stealth:
            device, city = self._dev_city(u, ts)
        else:
            device = "dev-" + self._rand_id(8)
            city = int(rng.integers(len(CITIES))) if self._chance(0.75) else u.city
        t = ts
        for _ in range(int(rng.integers(1, 7))):
            self._txn(t, u.vpa, self._pick(ring).vpa, 0.0, "PAY", device, city, label=1, typology="account_takeover", stealth=stealth,
                      drain=float(rng.uniform(0.15, 0.7)), min_amount=500.0)
            t += float(rng.uniform(1, 9)) * MINUTE
        return {"scenario": "account_takeover", "entry": ring[0].vpa, "entries": [m.vpa for m in ring], "ring": self._rings_of(ring), "device": device}

    def launch_coached(self, ts: float, victim: User | None = None, stealth=None, fast=False) -> dict:
        """'Digital arrest': a scared person sends large amounts from their own phone, at home, in daylight."""
        rng = self.rng
        self._now_hint = ts
        stealth = self._stealthy() if stealth is None else stealth
        u = victim or self._victim(0.7)
        ring = self._new_ring(stealth, int(rng.integers(1, 4)))
        day_start = START_TS + math.floor((ts - START_TS) / DAY) * DAY
        t = ts if fast else day_start + float(rng.uniform(10, 18)) * HOUR
        if t < ts:
            t += DAY
        for _ in range(int(rng.integers(1, 9)) if not fast else 3):
            self._txn(t, u.vpa, self._pick(ring).vpa, 0.0, "PAY", *self._dev_city(u, t), note=self._pick(COACHED_NOTES), label=1, typology="coached_transfer", stealth=stealth,
                      drain=float(rng.uniform(0.1, 0.35) if stealth else rng.uniform(0.3, 0.9)), min_amount=2000.0)
            t += (float(rng.uniform(5, 25)) * MINUTE if fast else float(rng.uniform(0.5, 30)) * HOUR)
        return {"scenario": "coached_transfer", "entry": ring[0].vpa, "entries": [m.vpa for m in ring], "ring": self._rings_of(ring)}

    def _ring_of(self, entry: Mule) -> list[str]:
        out, stack = [], [entry.vpa]
        while stack:
            v = stack.pop()
            if v not in out:
                out.append(v)
                m = self.mules.get(v)
                if m:
                    stack.extend(m.next_hops)
        return out

    def _rings_of(self, entries: list[Mule]) -> list[str]:
        out: list[str] = []
        for m in entries:
            out.extend(v for v in self._ring_of(m) if v not in out)
        return out

    def _schedule_day(self, day: int) -> None:
        for u in self.user_list:
            self._user_day(u, day)
        self._hard_cases(day)
        if not self.cfg.background_scams:
            return
        rng, start, s = self.rng, self._day_start(day), self._scale
        plan = [("fake_collect", self.cfg.rate_fake_collect, self.launch_fake_collect),
                ("phishing_link", self.cfg.rate_phishing, self.launch_phishing),
                ("qr_scam", self.cfg.rate_qr, self.launch_qr),
                ("mule_inflow", self.cfg.rate_mule_inflow, self.launch_mule_inflow),
                ("account_takeover", self.cfg.rate_takeover, self.launch_takeover),
                ("coached_transfer", self.cfg.rate_coached, self.launch_coached)]
        for name, rate, launch in plan:
            if name in self.cfg.skip_typologies:
                continue
            for _ in range(int(rng.poisson(rate * s))):
                launch(start + float(rng.uniform(0, 24)) * HOUR)
