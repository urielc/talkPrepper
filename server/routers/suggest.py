"""Topic suggestions: talks and manual pages for a topic and audience."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import suggest as sg
from ..ai import get_provider
from ..ai.base import ProviderError
from ..auth import rate_limit
from ..deps import get_conn, get_engine, get_user
from ..settings import get_settings

router = APIRouter(tags=["suggest"])

Audience = Literal["children", "youth", "adults"]
Gender = Literal["any", "male", "female"]


class SuggestBody(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    audience: Audience = "adults"
    gender: Gender = "any"
    limit: int = Field(20, ge=1, le=40)


class RefineBody(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    audience: Audience = "adults"
    gender: Gender = "any"
    talk_ids: list[str] = Field(min_length=1, max_length=sg.MAX_REFINE)


@router.post("/suggest")
def suggest(body: SuggestBody, conn=Depends(get_conn), engine=Depends(get_engine), _user=Depends(get_user)):
    return sg.suggest(conn, engine, body.topic.strip(), body.audience, body.gender, body.limit)


@router.post("/suggest/refine")
def refine(body: RefineBody, conn=Depends(get_conn), user=Depends(get_user)):
    rate_limit(f"refine:{user['id']}", limit=20, window_s=600)
    try:
        provider = get_provider(get_settings(conn))
        return sg.refine(conn, provider, body.topic.strip(), body.audience, body.gender, body.talk_ids)
    except ProviderError as e:
        raise HTTPException(400, str(e))
