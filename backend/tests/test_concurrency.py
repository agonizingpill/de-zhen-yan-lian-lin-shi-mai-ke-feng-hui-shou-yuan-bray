import threading

from conftest import login, venue_headers
from factory import ensure_point


def test_concurrent_same_slot_capture_across_venues(client):
    for venue in ("SITE-A", "SITE-B"):
        ensure_point(venue, "MIC-PAV", channel="BUS-A")
    token = login(client, "operator")
    payload = {"code": "WIN-RACE", "point": "MIC-PAV", "slot": 88, "frequency": 730,
               "peak_share": 0.2, "ring_index": 0.24, "level": 0.3, "self_echo": 0.15}
    results = {}

    def worker(venue):
        resp = client.post("/audio", json=payload,
                           headers=venue_headers(token, venue))
        results[venue] = resp.status_code

    threads = [threading.Thread(target=worker, args=(v,)) for v in ("SITE-A", "SITE-B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 两场并发同号同刻度都能各自落库，互不阻塞或覆盖。
    assert results == {"SITE-A": 201, "SITE-B": 201}
    for venue in ("SITE-A", "SITE-B"):
        rows = client.get("/audio", headers=venue_headers(token, venue)).json()
        match = [r for r in rows if r["code"] == "WIN-RACE" and r["slot"] == 88]
        assert len(match) == 1 and match[0]["venue"] == venue
