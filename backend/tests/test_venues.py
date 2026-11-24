from conftest import drain_jobs, login, venue_headers
from factory import baseline_set, ensure_point, insert_window


def test_missing_venue_header_rejected(client):
    token = login(client, "operator")
    response = client.get("/patch", headers=token)
    assert response.status_code == 400
    assert "场地" in response.json()["detail"]


def test_invalid_venue_header_rejected(client):
    token = login(client, "operator")
    response = client.get("/patch", headers=venue_headers(token, "SITE-X"))
    assert response.status_code == 400


def test_venue_listing_requires_login(client):
    assert client.get("/venues").status_code == 401
    token = login(client, "viewer")
    body = client.get("/venues", headers=token).json()
    assert {item["code"] for item in body["venues"]} == {"SITE-A", "SITE-B"}


def test_same_code_capture_saved_per_venue(client):
    for venue in ("SITE-A", "SITE-B"):
        ensure_point(venue, "MIC-PAV", channel="BUS-A")
    token = login(client, "operator")
    payload = {"code": "WIN-SAME", "point": "MIC-PAV", "slot": 90, "frequency": 730,
               "peak_share": 0.2, "ring_index": 0.24, "level": 0.3, "self_echo": 0.15}
    first = client.post("/audio", json=payload, headers=venue_headers(token, "SITE-A"))
    second = client.post("/audio", json=payload, headers=venue_headers(token, "SITE-B"))
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    # 同一场再用同号会被复合主键挡住，另一场不受影响。
    clash = client.post("/audio", json=payload, headers=venue_headers(token, "SITE-A"))
    assert clash.status_code == 409
    for venue in ("SITE-A", "SITE-B"):
        rows = client.get("/audio", headers=venue_headers(token, venue)).json()
        assert [row["code"] for row in rows].count("WIN-SAME") == 1


def test_page_only_shows_current_venue_records(client):
    ensure_point("SITE-A", "MIC-PAV")
    ensure_point("SITE-B", "MIC-PAV")
    insert_window("SITE-A", "WIN-ONLY-A", "MIC-PAV", 10, 700)
    insert_window("SITE-B", "WIN-ONLY-B", "MIC-PAV", 10, 700)
    token = login(client, "viewer")
    a_codes = {row["code"] for row in
               client.get("/audio", headers=venue_headers(token, "SITE-A")).json()}
    b_codes = {row["code"] for row in
               client.get("/audio", headers=venue_headers(token, "SITE-B")).json()}
    assert "WIN-ONLY-A" in a_codes and "WIN-ONLY-B" not in a_codes
    assert "WIN-ONLY-B" in b_codes and "WIN-ONLY-A" not in b_codes


def test_baseline_is_scoped_per_venue(client, broker):
    ensure_point("SITE-A", "MIC-PAV")
    ensure_point("SITE-B", "MIC-PAV")
    # 只给 A 场铺基线。
    baseline_set("SITE-A", 217)
    insert_window("SITE-A", "WIN-LIVE-A", "MIC-PAV", 60, 800, (0.9, 0.9, 0.8, 0.8))
    insert_window("SITE-B", "WIN-LIVE-B", "MIC-PAV", 60, 800, (0.9, 0.9, 0.8, 0.8))
    token = login(client, "operator")
    ok = client.post("/feedback/diagnose", json={"window": "WIN-LIVE-A"},
                     headers=venue_headers(token, "SITE-A"))
    assert ok.status_code == 202, ok.text
    drain_jobs(broker)
    report = client.get(f"/compute/{ok.json()['token']}",
                        headers=venue_headers(token, "SITE-A")).json()
    assert report["status"] == "ready"
    # 回归保护：worker 回写结果时必须保留场地归属，否则本场也无法再用该凭证。
    assert report["venue"] == "SITE-A"
    assert report["result"]["reference_windows"] == 32
    # B 场基线不足，同刻度计算应被 worker 拒绝，证明基线按本场算。
    denied = client.post("/feedback/diagnose", json={"window": "WIN-LIVE-B"},
                         headers=venue_headers(token, "SITE-B"))
    drain_jobs(broker)
    report_b = client.get(f"/compute/{denied.json()['token']}",
                          headers=venue_headers(token, "SITE-B")).json()
    assert report_b["status"] == "rejected"
    assert "基线" in report_b["detail"]


def test_cross_venue_compute_token_cannot_sign_finding(client, broker):
    for venue in ("SITE-A", "SITE-B"):
        ensure_point(venue, "MIC-PAV")
        baseline_set(venue, 217 if venue == "SITE-A" else 432)
    insert_window("SITE-A", "WIN-A", "MIC-PAV", 70, 800, (0.9, 0.9, 0.8, 0.8))
    insert_window("SITE-B", "WIN-B", "MIC-PAV", 70, 800, (0.2, 0.2, 0.3, 0.15))
    token = login(client, "operator")
    job_a = client.post("/feedback/diagnose", json={"window": "WIN-A"},
                        headers=venue_headers(token, "SITE-A")).json()
    drain_jobs(broker)
    # 凭证在原场可以查看。
    assert client.get(f"/compute/{job_a['token']}",
                      headers=venue_headers(token, "SITE-A")).json()["status"] == "ready"
    # 别场查看直接 403。
    cross_view = client.get(f"/compute/{job_a['token']}",
                            headers=venue_headers(token, "SITE-B"))
    assert cross_view.status_code == 403
    # 别场拿该凭证签发现，被场地校验挡住，不产生任何发现。
    cross_save = client.post("/feedback/save",
                             json={"code": "FD-CROSS", "token": job_a["token"]},
                             headers=venue_headers(token, "SITE-B"))
    assert cross_save.status_code == 403
    assert client.get("/feedback",
                      headers=venue_headers(token, "SITE-B")).json() == []
    # 原场可以正常签入。
    saved = client.post("/feedback/save",
                        json={"code": "FD-A", "token": job_a["token"]},
                        headers=venue_headers(token, "SITE-A"))
    assert saved.status_code == 201, saved.text


def test_backup_bus_occupation_scoped_per_venue(client):
    # 两场都有 MIC-HUB 占用 BUS-B；A 场隔离时仍可分配 BUS-C，且不看 B 场占用。
    ensure_point("SITE-A", "MIC-HUB", channel="BUS-B")
    ensure_point("SITE-A", "MIC-PAV", channel="BUS-A")
    ensure_point("SITE-B", "MIC-HUB", channel="BUS-B")
    insert_window("SITE-A", "WIN-FOCUS", "MIC-PAV", 50, 900, (0.9, 0.9, 0.8, 0.8))
    insert_window("SITE-A", "WIN-OLD", "MIC-HUB", 40, 900)
    # 直接构造一条 local 发现，聚焦验证备用路占用判定。
    from core.db import transaction
    from domain.interventions import findings
    with transaction() as conn:
        conn.execute(findings.insert().values(
            venue="SITE-A", code="FD-LOCAL", focus_window="WIN-FOCUS", category="local",
            score=-3.1, neighbors=8, shared_points=[], reviewed_by="operator@demo.test",
            compute_token="a" * 32))
    reviewer = login(client, "reviewer")
    # BUS-C 在 A 场空闲（B 场即使占 BUS-C 也不影响）；先在 B 场占掉 BUS-C。
    ensure_point("SITE-B", "MIC-INFO", channel="BUS-C")
    response = client.post("/patch/isolate",
                           json={"code": "ISO-A", "finding": "FD-LOCAL",
                                 "destination": "BUS-C"},
                           headers=venue_headers(reviewer, "SITE-A"))
    assert response.status_code == 201, response.text
    # A 场再隔离到已被本场占用的 BUS-C 必须拒绝。
    ensure_point("SITE-A", "MIC-WALK", channel="BUS-A")
    insert_window("SITE-A", "WIN-WALK", "MIC-WALK", 51, 900, (0.9, 0.9, 0.8, 0.8))
    with transaction() as conn:
        from domain.interventions import findings as f_table
        conn.execute(f_table.insert().values(
            venue="SITE-A", code="FD-LOCAL-2", focus_window="WIN-WALK", category="local",
            score=-3.1, neighbors=8, shared_points=[], reviewed_by="operator@demo.test",
            compute_token="b" * 32))
    busy = client.post("/patch/isolate",
                       json={"code": "ISO-BUSY", "finding": "FD-LOCAL-2",
                             "destination": "BUS-C"},
                       headers=venue_headers(reviewer, "SITE-A"))
    assert busy.status_code == 409


def test_reline_full_flow_and_cross_venue_restore_blocked(client, broker):
    ensure_point("SITE-A", "MIC-PAV", channel="BUS-A")
    ensure_point("SITE-B", "MIC-PAV", channel="BUS-A")
    baseline_set("SITE-A", 217)
    insert_window("SITE-A", "WIN-FAULT", "MIC-PAV", 40, 900, (0.9, 0.9, 0.8, 0.8))
    from core.db import transaction
    from domain.interventions import findings, tickets
    with transaction() as conn:
        conn.execute(findings.insert().values(
            venue="SITE-A", code="FD-1", focus_window="WIN-FAULT", category="local",
            score=-3.1, neighbors=8, shared_points=[], reviewed_by="operator@demo.test",
            compute_token="c" * 32))
    reviewer = login(client, "reviewer")
    isolated = client.post("/patch/isolate",
                           json={"code": "ISO-1", "finding": "FD-1", "destination": "BUS-C"},
                           headers=venue_headers(reviewer, "SITE-A"))
    assert isolated.status_code == 201, isolated.text
    operator = login(client, "operator")
    # 隔离后采集的窗口自动归为复线试音。
    reline_payload = {"code": "WIN-REL-1", "point": "MIC-PAV", "slot": 55, "frequency": 730,
                      "peak_share": 0.2, "ring_index": 0.2, "level": 0.3, "self_echo": 0.15}
    saved = client.post("/audio", json=reline_payload,
                        headers=venue_headers(operator, "SITE-A"))
    assert saved.status_code == 201 and saved.json()["purpose"] == "reline"
    job = client.post("/patch/ISO-1/probe", json={"window": "WIN-REL-1"},
                      headers=venue_headers(operator, "SITE-A"))
    assert job.status_code == 202, job.text
    drain_jobs(broker)
    ready = client.get(f"/compute/{job.json()['token']}",
                       headers=venue_headers(operator, "SITE-A")).json()
    assert ready["status"] == "ready"
    # 作业员无权复位。
    forbidden = client.post("/patch/ISO-1/restore",
                            json={"token": job.json()["token"]},
                            headers=venue_headers(operator, "SITE-A"))
    assert forbidden.status_code == 403
    # 拿 A 场凭证到 B 场复位：凭证场地不符。
    cross = client.post("/patch/ISO-1/restore",
                        json={"token": job.json()["token"]},
                        headers=venue_headers(reviewer, "SITE-B"))
    assert cross.status_code == 403
    # 复核员在本场签复位成功。
    restored = client.post("/patch/ISO-1/restore",
                           json={"token": job.json()["token"]},
                           headers=venue_headers(reviewer, "SITE-A"))
    assert restored.status_code == 200, restored.text
    assert restored.json()["state"] == "restored"
    with transaction() as conn:
        from sqlalchemy import select
        from domain.soundboard import points
        row = conn.execute(select(points).where(
            points.c.venue == "SITE-A", points.c.code == "MIC-PAV")).mappings().one()
        assert row["patch"] == "live"
        assert conn.execute(select(tickets.c.reline_window).where(
            tickets.c.venue == "SITE-A", tickets.c.code == "ISO-1")).scalar() == "WIN-REL-1"


def test_viewer_cannot_capture(client):
    ensure_point("SITE-A", "MIC-PAV")
    viewer = login(client, "viewer")
    payload = {"code": "WIN-X", "point": "MIC-PAV", "slot": 1, "frequency": 730,
               "peak_share": 0.2, "ring_index": 0.24, "level": 0.3, "self_echo": 0.15}
    assert client.post("/audio", json=payload,
                       headers=venue_headers(viewer, "SITE-A")).status_code == 403
