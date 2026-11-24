import os
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import (Column, DateTime, Float, ForeignKey, Integer, JSON, MetaData, String,
                        Table, create_engine, inspect, select, text)


def _build_legacy_database(url):
    """复刻改造前的单场地表结构（含单列主键与单列唯一约束）。"""
    legacy = MetaData()
    points = Table(
        "microphone_points", legacy,
        Column("code", String(20), primary_key=True),
        Column("location", String(64), nullable=False),
        Column("mic_tag", String(20), nullable=False, unique=True),
        Column("channel", String(12), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("patch", String(14), nullable=False),
    )
    windows = Table(
        "sound_windows", legacy,
        Column("code", String(24), primary_key=True),
        Column("point", String(20), ForeignKey("microphone_points.code"), nullable=False),
        Column("channel", String(12), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("slot", Integer, nullable=False),
        Column("frequency", Integer, nullable=False),
        Column("peak_share", Float), Column("ring_index", Float),
        Column("level", Float), Column("self_echo", Float),
        Column("purpose", String(12), nullable=False),
    )
    windows.append_constraint(
        __import__("sqlalchemy").UniqueConstraint("point", "slot", "revision",
                                                  name="uq_legacy_window"))
    findings = Table(
        "feedback_findings", legacy,
        Column("code", String(24), primary_key=True),
        Column("focus_window", String(24), ForeignKey("sound_windows.code"),
               nullable=False, unique=True),
        Column("category", String(16), nullable=False),
        Column("score", Float, nullable=False),
        Column("neighbors", Integer, nullable=False),
        Column("shared_points", JSON, nullable=False),
        Column("reviewed_by", String(80), nullable=False),
        Column("compute_token", String(32), nullable=False, unique=True),
    )
    tickets = Table(
        "channel_tickets", legacy,
        Column("code", String(24), primary_key=True),
        Column("point", String(20), ForeignKey("microphone_points.code"), nullable=False),
        Column("finding", String(24), ForeignKey("feedback_findings.code"),
               nullable=False, unique=True),
        Column("old_channel", String(12), nullable=False),
        Column("new_channel", String(12), nullable=False),
        Column("reline_window", String(24), ForeignKey("sound_windows.code"), unique=True),
        Column("test_score", Float),
        Column("state", String(16), nullable=False),
        Column("isolated_by", String(80), nullable=False),
        Column("restored_by", String(80)),
    )
    Table("patch_serial", legacy, Column("code", Integer, primary_key=True))
    audit_legacy = Table(
        "audit_trail", legacy,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("actor", String(100), nullable=False),
        Column("operation", String(100), nullable=False),
        Column("at", DateTime, nullable=False),
    )
    engine = create_engine(url)
    legacy.create_all(engine)
    with engine.begin() as conn:
        conn.execute(points.insert(), [
            {"code": "MIC-PAV", "location": "东门棚台", "mic_tag": "TAG-E01",
             "channel": "BUS-A", "revision": 1, "patch": "isolated"},
        ])
        conn.execute(windows.insert(), [
            {"code": "WIN-FAULT", "point": "MIC-PAV", "channel": "BUS-A", "revision": 1,
             "slot": 40, "frequency": 900, "peak_share": .9, "ring_index": .9, "level": .8,
             "self_echo": .8, "purpose": "live"},
            {"code": "WIN-REL", "point": "MIC-PAV", "channel": "BUS-C", "revision": 2,
             "slot": 55, "frequency": 730, "peak_share": .2, "ring_index": .2, "level": .3,
             "self_echo": .15, "purpose": "reline"},
        ])
        conn.execute(findings.insert(), [{
            "code": "FD-1", "focus_window": "WIN-FAULT", "category": "local", "score": -3.1,
            "neighbors": 8, "shared_points": [], "reviewed_by": "operator@demo.test",
            "compute_token": "c" * 32,
        }])
        conn.execute(tickets.insert(), [{
            "code": "ISO-1", "point": "MIC-PAV", "finding": "FD-1", "old_channel": "BUS-A",
            "new_channel": "BUS-C", "reline_window": "WIN-REL", "test_score": -0.4,
            "state": "restored", "isolated_by": "reviewer@demo.test",
            "restored_by": "reviewer@demo.test",
        }])
        conn.execute(text("INSERT INTO patch_serial (code) VALUES (1)"))
        conn.execute(audit_legacy.insert(), [
            {"actor": "reviewer@demo.test", "operation": "reline:ISO-1:WIN-REL",
             "at": datetime(2026, 11, 24, 9, 22, 0)},
        ])
    return engine


def test_legacy_upgrade_preserves_relationships_and_is_idempotent(monkeypatch):
    fd, path = tempfile.mkstemp(prefix="legacy-", suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"
    legacy_engine = _build_legacy_database(url)

    # 把应用全局引擎指向旧库后再迁移。
    import core.db as db_module
    import core.migrate as migrate_module
    fresh = create_engine(url)
    monkeypatch.setattr(db_module, "engine", fresh)
    monkeypatch.setattr(migrate_module, "engine", fresh)

    migrate_module.migrate()

    inspector = inspect(fresh)
    for table in ("microphone_points", "sound_windows", "feedback_findings",
                  "channel_tickets", "patch_serial"):
        assert "venue" in {col["name"] for col in inspector.get_columns(table)}
        pk = inspector.get_pk_constraint(table)["constrained_columns"]
        assert pk == ["venue", "code"], table
    # 审计表加 venue 但保留自增 id 主键。
    audit_cols = {col["name"] for col in inspector.get_columns("audit_trail")}
    assert "venue" in audit_cols
    assert inspector.get_pk_constraint("audit_trail")["constrained_columns"] == ["id"]

    with fresh.begin() as conn:
        # 旧数据全部归入原场 SITE-A，声检、诊断、隔离的对应关系保留。
        assert conn.execute(text(
            "SELECT venue FROM microphone_points WHERE code='MIC-PAV'")).scalar() == "SITE-A"
        count_windows = conn.execute(text(
            "SELECT COUNT(*) FROM sound_windows WHERE venue='SITE-A'")).scalar()
        assert count_windows == 2
        linked = conn.execute(text(
            "SELECT t.code, f.focus_window, t.reline_window "
            "FROM channel_tickets t JOIN feedback_findings f "
            "ON t.venue=f.venue AND t.finding=f.code "
            "WHERE t.venue='SITE-A'")).one()
        assert tuple(linked) == ("ISO-1", "WIN-FAULT", "WIN-REL")
        assert conn.execute(text(
            "SELECT patch FROM microphone_points WHERE venue='SITE-A' AND code='MIC-PAV'"
        )).scalar() == "isolated"
        assert conn.execute(text(
            "SELECT venue FROM patch_serial WHERE code=1")).scalar() == "SITE-A"
        # 旧审计记录归入原场且内容保留。
        audit_row = conn.execute(text(
            "SELECT venue, operation FROM audit_trail WHERE actor='reviewer@demo.test'"
        )).one()
        assert tuple(audit_row) == ("SITE-A", "reline:ISO-1:WIN-REL")

    # 重跑迁移不重复入档、不报错。
    migrate_module.migrate()
    with fresh.begin() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM sound_windows WHERE venue='SITE-A'")).scalar() == 2

    # 旧单列唯一约束已被复合约束取代：两场可重用同号与同一 mic_tag。
    from domain.soundboard import points as points_table
    with fresh.begin() as conn:
        conn.execute(points_table.insert().values(
            venue="SITE-B", code="MIC-PAV", location="二号场棚台", mic_tag="TAG-E01",
            channel="BUS-A", revision=1, patch="live"))
        row = conn.execute(select(points_table).where(
            points_table.c.venue == "SITE-B", points_table.c.code == "MIC-PAV")).mappings().one()
        assert row["mic_tag"] == "TAG-E01"
        # 两场同号麦位各自独立存在。
        assert conn.execute(text(
            "SELECT COUNT(*) FROM microphone_points WHERE code='MIC-PAV'")).scalar() == 2

    legacy_engine.dispose()
    fresh.dispose()
