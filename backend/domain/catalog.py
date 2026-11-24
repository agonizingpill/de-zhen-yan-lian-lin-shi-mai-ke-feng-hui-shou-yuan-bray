from fastapi import HTTPException
from sqlalchemy import select
from core.db import transaction
from domain.interventions import findings,tickets
from domain.soundboard import points,windows


def one(conn,table,code,venue,lock=False):
    query=select(table).where(table.c.code==code,table.c.venue==venue)
    row=conn.execute(query.with_for_update() if lock else query).mappings().first()
    if row is None:
        raise HTTPException(404,f"本场没有编号为 {code} 的记录")
    return dict(row)


def query(conn,table,venue,*filters):
    stmt=select(table).where(table.c.venue==venue,*filters).order_by(table.c.code.desc()).limit(160)
    return [dict(row) for row in conn.execute(stmt).mappings()]


def calibration(conn,venue):
    return query(conn,windows,venue,windows.c.purpose=="baseline")


def same_slot(conn,venue,focus):
    return query(conn,windows,venue,windows.c.slot==focus["slot"],windows.c.purpose=="live")


def latest(conn,venue,point,purpose):
    stmt=select(windows).where(windows.c.venue==venue,windows.c.point==point["code"],
                               windows.c.revision==point["revision"],
                               windows.c.purpose==purpose).order_by(windows.c.slot.desc()).limit(1)
    row=conn.execute(stmt).mappings().first()
    return dict(row) if row else None


def patchboard(venue):
    with transaction() as conn:
        return {"points":query(conn,points,venue),"tickets":query(conn,tickets,venue)}


def audio(venue):
    with transaction() as conn:
        return query(conn,windows,venue,windows.c.purpose!="baseline")


def diagnosis(venue):
    with transaction() as conn:
        return query(conn,findings,venue)
