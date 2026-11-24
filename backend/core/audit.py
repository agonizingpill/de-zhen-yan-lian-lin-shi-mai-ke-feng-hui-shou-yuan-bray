from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Table

from core.db import metadata

audit = Table('audit_trail', metadata, Column('id', Integer, primary_key=True, autoincrement=True),
              Column('venue', String(12), nullable=False),
              Column('actor', String(100), nullable=False), Column('operation', String(100), nullable=False),
              Column('at', DateTime, nullable=False))

def record(conn, user, venue, operation):
    conn.execute(audit.insert().values(venue=venue, actor=user['sub'], operation=operation,
                                       at=datetime.now(timezone.utc)))
