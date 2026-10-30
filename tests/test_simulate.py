"""The simulator: repeatable, contains the scam types and hard cases the plan promises, and scams behave as described."""
from collections import Counter

import pytest

from ml.simulate import PERSONAS, START_TS, WorldConfig, World, km_between

SMALL = WorldConfig(seed=11, days=14, n_users=6000, n_merchants=800)


def run(cfg):
    world = World(cfg)
    events = []
    while (ev := world.next_event()) is not None:
        events.append(ev)
        world.commit(ev)
    return world, events


@pytest.fixture(scope="module")
def sim():
    return run(SMALL)


def test_same_seed_gives_the_same_world():
    cfg = WorldConfig(seed=5, days=4, n_users=400, n_merchants=80)
    _, a = run(cfg)
    _, b = run(cfg)
    assert len(a) == len(b)
    assert [e.get("txn_id") for e in a] == [e.get("txn_id") for e in b]
    assert [e.get("amount") for e in a] == [e.get("amount") for e in b]


def test_different_seed_gives_a_different_world():
    _, a = run(WorldConfig(seed=5, days=3, n_users=400, n_merchants=80))
    _, b = run(WorldConfig(seed=6, days=3, n_users=400, n_merchants=80))
    assert [e.get("amount") for e in a][:200] != [e.get("amount") for e in b][:200]


def test_events_come_in_time_order(sim):
    _, events = sim
    times = [e["ts"] for e in events]
    assert times == sorted(times)
    assert times[0] >= START_TS - 3600


def test_every_scam_type_appears(sim):
    _, events = sim
    types = Counter(e["typology"] for e in events if e["event"] == "txn" and e["label"])
    for t in ("fake_collect", "phishing_link", "qr_scam", "mule_inflow", "mule_layering", "account_takeover", "coached_transfer"):
        assert types[t] > 0, f"{t} is missing: {types}"


def test_hard_cases_are_present_and_are_never_labelled_fraud(sim):
    _, events = sim
    tags = Counter(e["tag"] for e in events if e["event"] == "txn" and e["tag"])
    for t in ("hn_trip_pool", "hn_fair", "hn_big_purchase", "hn_first_rent", "hn_big_known", "hn_bill_sms", "hn_shop"):
        assert tags[t] > 0, f"{t} is missing: {tags}"
    assert not [e for e in events if e["event"] == "txn" and e["tag"] and e["label"]]


def test_fraud_is_rare_but_not_absent(sim):
    _, events = sim
    txns = [e for e in events if e["event"] == "txn"]
    share = sum(e["label"] for e in txns) / len(txns)
    assert 0.001 < share < 0.03, share


def test_all_upi_ids_are_clearly_fictional(sim):
    world, events = sim
    for e in events:
        if e["event"] == "txn":
            assert e["payer"].split("@")[1].startswith("sim"), e["payer"]
            assert e["payee"].split("@")[1].startswith("sim"), e["payee"]
    assert all(v.split("@")[1].startswith("sim") for v in world.directory)


def test_a_mule_moves_the_money_on_and_stopping_it_keeps_the_money(sim):
    world = World(WorldConfig(seed=3, days=1, n_users=300, n_merchants=60, background_scams=False))
    victims = world.user_list[:6]
    for v in victims:
        world.balance[v.vpa] = 50_000.0
    info = world.launch_mule_inflow(START_TS + 3600, victims=victims, n=6, stealth=False, entries=1, fast=True)
    entry, moved_out, stopped_out = info["entries"][0], [], []
    stop_next = True
    while (ev := world.next_event()) is not None:
        if ev["event"] == "txn" and ev["payer"] == entry and stop_next:
            stopped_out.append(ev)
            stop_next = False
            world.commit(ev, moved=False)
            continue
        if ev["event"] == "txn" and ev["payer"] == entry:
            moved_out.append(ev)
        world.commit(ev)
    assert stopped_out, "the mule never tried to move the money"
    assert world.mules[entry].forwarded >= 1
    assert all(e["typology"] == "mule_layering" and e["label"] == 1 for e in stopped_out + moved_out)


def test_a_cancelled_collect_request_never_gets_an_outcome():
    world = World(WorldConfig(seed=4, days=1, n_users=200, n_merchants=40, background_scams=False))
    world.launch_fake_collect(START_TS + 100, victims=world.user_list[:3], n=3, stealth=False)
    cancelled, outcomes = set(), []
    while (ev := world.next_event()) is not None:
        if ev["event"] == "txn" and ev.get("typology") == "fake_collect":
            cancelled.add(ev["txn_id"])
            world.commit(ev, moved=False)
            continue
        if ev["event"] == "outcome" and ev["txn_id"] in cancelled:
            outcomes.append(ev)
        world.commit(ev)
    assert len(cancelled) == 3 and not outcomes


def test_fake_collects_come_from_merchant_style_ids_as_p2p_collect_has_ended():
    world = World(WorldConfig(seed=8, days=1, n_users=200, n_merchants=40, background_scams=False))
    info = world.launch_fake_collect(START_TS + 100, n=4, stealth=False)
    entry = world.directory[info["entry"]]
    assert entry["merchant"] is True and entry["verified"] is False


def test_personas_exist_and_have_stable_history():
    world = World(WorldConfig(seed=9, days=1, n_users=200, n_merchants=40))
    for p in PERSONAS.values():
        assert p["vpa"] in world.users
    sunita = world.users[PERSONAS["sunita"]["vpa"]]
    assert sunita.phone_change is None and sunita.trip is None and sunita.sms_sensor


def test_skipping_a_scam_type_removes_only_that_type_from_the_campaigns():
    cfg = WorldConfig(seed=2, days=10, n_users=6000, n_merchants=800, skip_typologies=("fake_collect",))
    _, events = run(cfg)
    types = {e["typology"] for e in events if e["event"] == "txn" and e["label"]}
    assert "fake_collect" not in types and "phishing_link" in types


def test_distance_between_cities():
    assert km_between(0, 0) == 0.0
    assert 200 < km_between(0, 1) < 320      # Jaipur to Delhi, about 240 km
