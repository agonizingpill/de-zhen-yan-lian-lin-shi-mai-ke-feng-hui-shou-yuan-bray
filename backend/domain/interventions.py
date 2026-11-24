from sqlalchemy import CheckConstraint,Column,Float,ForeignKeyConstraint,Integer,JSON,String,Table,UniqueConstraint
from core.db import metadata
from domain.venues import VENUES

findings = Table(
    "feedback_findings",metadata,
    Column("venue",String(12),primary_key=True),
    Column("code",String(24),primary_key=True),
    Column("focus_window",String(24),nullable=False),
    Column("category",String(16),nullable=False),
    Column("score",Float,nullable=False),
    Column("neighbors",Integer,nullable=False),
    Column("shared_points",JSON,nullable=False),
    Column("reviewed_by",String(80),nullable=False),
    Column("compute_token",String(32),nullable=False),
    ForeignKeyConstraint(("venue","focus_window"),["sound_windows.venue","sound_windows.code"],
                         name="fk_findings_window"),
    UniqueConstraint("venue","focus_window",name="uq_findings_venue_window"),
    UniqueConstraint("venue","compute_token",name="uq_findings_venue_token"),
    CheckConstraint("category IN ('local','coordinated','normal')"),
    CheckConstraint(f"venue IN {VENUES}", name="chk_venue_legit"),
)

tickets = Table(
    "channel_tickets",metadata,
    Column("venue",String(12),primary_key=True),
    Column("code",String(24),primary_key=True),
    Column("point",String(20),nullable=False),
    Column("finding",String(24),nullable=False),
    Column("old_channel",String(12),nullable=False),
    Column("new_channel",String(12),nullable=False),
    Column("reline_window",String(24)),
    Column("test_score",Float),
    Column("state",String(16),nullable=False),
    Column("isolated_by",String(80),nullable=False),
    Column("restored_by",String(80)),
    ForeignKeyConstraint(("venue","point"),["microphone_points.venue","microphone_points.code"],
                         name="fk_tickets_point"),
    ForeignKeyConstraint(("venue","finding"),["feedback_findings.venue","feedback_findings.code"],
                         name="fk_tickets_finding"),
    ForeignKeyConstraint(("venue","reline_window"),["sound_windows.venue","sound_windows.code"],
                         name="fk_tickets_reline"),
    UniqueConstraint("venue","finding",name="uq_tickets_venue_finding"),
    UniqueConstraint("venue","reline_window",name="uq_tickets_venue_reline"),
    CheckConstraint("old_channel <> new_channel"),
    CheckConstraint("state IN ('isolated','restored')"),
    CheckConstraint(f"venue IN {VENUES}", name="chk_venue_legit"),
)
