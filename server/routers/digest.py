"""Per-talk digest: essence, key quotes, discussion questions (AI-generated, cached)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..ai.base import ProviderError
from ..ai.digest import delete_digest, generate_digest, load_digest
from ..deps import get_conn
from .talks import talk_detail

router = APIRouter(tags=["digest"])


@router.get("/talks/{talk_id:path}/digest")
def get_digest(talk_id: str, conn=Depends(get_conn)):
    talk_detail(talk_id, conn)  # 404 for unknown talks
    return load_digest(conn, talk_id)


@router.post("/talks/{talk_id:path}/digest")
def create_digest(talk_id: str, conn=Depends(get_conn)):
    talk = talk_detail(talk_id, conn)
    try:
        return generate_digest(conn, talk, talk["paragraphs"])
    except ProviderError as e:
        raise HTTPException(400, str(e))


@router.delete("/talks/{talk_id:path}/digest")
def remove_digest(talk_id: str, conn=Depends(get_conn)):
    delete_digest(conn, talk_id)
    return {"ok": True}
