from sqlalchemy import select

from core.db import transaction
from domain.soundboard import points, windows
from domain.states import FEATURES


def ensure_point(venue, code, channel="BUS-A", location="测试麦位", mic_tag=None,
                 revision=1, patch="live"):
    with transaction() as conn:
        exists = conn.execute(select(points.c.code).where(
            points.c.venue == venue, points.c.code == code)).first()
        if not exists:
            conn.execute(points.insert().values(
                venue=venue, code=code, location=location,
                mic_tag=mic_tag or f"TAG-{venue}-{code}", channel=channel,
                revision=revision, patch=patch))


def insert_window(venue, code, point, slot, frequency, features=None, purpose="live",
                  channel=None, revision=1):
    values = dict(zip(FEATURES, features or (0.2, 0.24, 0.3, 0.15), strict=True))
    with transaction() as conn:
        if channel is None:
            row = conn.execute(select(points).where(
                points.c.venue == venue, points.c.code == point)).mappings().first()
            channel = row["channel"]
            revision = row["revision"]
        conn.execute(windows.insert().values(
            venue=venue, code=code, point=point, channel=channel, revision=revision,
            slot=slot, frequency=frequency, purpose=purpose, **values))


def baseline_set(venue, seed):
    """每个场地至少 12 个基线窗，worker 的 LOF 才能计算。"""
    from random import Random
    rng = Random(seed)
    for index in range(32):
        insert_window(
            venue, f"REF-{index + 1:02}", "MIC-PAV", index + 1, 550 + index * 13,
            [max(0.03, min(0.42, rng.gauss(center, 0.033)))
             for center in (0.20, 0.24, 0.30, 0.15)], purpose="baseline")
