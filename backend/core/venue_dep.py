from fastapi import Header, HTTPException

from domain.venues import HEADER, VENUES


def venue_code(x_venue_code: str | None = Header(default=None, alias=HEADER)) -> str:
    """每个请求必须显式选择场地；所有读写与计算凭证都在该场地内隔离。"""
    if x_venue_code not in VENUES:
        raise HTTPException(400, f"缺少或非法的场地编号，请通过 {HEADER} 指定 {'/'.join(VENUES)}")
    return x_venue_code
