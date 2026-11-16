"""Topic suggestions: talks and manual pages for a topic and audience."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import suggest as sg
from ..ai import get_provider
from ..ai.base import ProviderError
from ..audience import CLASSES, DEFAULT_KEY
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
    audience: str = "adults"         # an age group, or a full audience key such as "adults-female" or "sacrament"
    gender: Gender = "any"
    talk_ids: list[str] = Field(min_length=1, max_length=sg.MAX_REFINE)


class RefineItem(BaseModel):
    ref: str = Field(min_length=1, max_length=300)
    title: str = Field("", max_length=400)
    subtitle: str = Field("", max_length=400)
    snippet: str = Field("", max_length=1500)


class GroupRefineBody(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    audience: str = DEFAULT_KEY
    group: str
    items: list[RefineItem] = Field(max_length=sg.MAX_REFINE)


class TopicBody(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    audience: str = DEFAULT_KEY


@router.post("/topic-search")
def topic_search(body: TopicBody, conn=Depends(get_conn), engine=Depends(get_engine), _user=Depends(get_user)):
    if body.audience not in CLASSES:
        raise HTTPException(422, f"unknown audience {body.audience!r}")
    return sg.topic_search(conn, engine, body.topic.strip(), body.audience)


@router.post("/suggest")
def suggest(body: SuggestBody, conn=Depends(get_conn), engine=Depends(get_engine), _user=Depends(get_user)):
    return sg.suggest(conn, engine, body.topic.strip(), body.audience, body.gender, body.limit)


@router.post("/suggest/refine")
def refine(body: RefineBody, conn=Depends(get_conn), user=Depends(get_user)):
    if body.audience not in CLASSES and body.audience not in ("children", "youth", "adults"):
        raise HTTPException(422, f"unknown audience {body.audience!r}")
    rate_limit(f"refine:{user['id']}", limit=20, window_s=600)
    try:
        provider = get_provider(get_settings(conn))
        return sg.refine(conn, provider, body.topic.strip(), body.audience, body.gender, body.talk_ids)
    except ProviderError as e:
        raise HTTPException(400, str(e))


@router.post("/topic-search/refine")
def refine_group(body: GroupRefineBody, conn=Depends(get_conn), user=Depends(get_user)):
    """Refine with AI for any group on the topic page (talks, manual pages, songs, scriptures, Josephus, Apocrypha)."""
    if body.audience not in CLASSES:
        raise HTTPException(422, f"unknown audience {body.audience!r}")
    if body.group not in sg.REFINE_GROUPS:
        raise HTTPException(422, f"unknown group {body.group!r}")
    rate_limit(f"refine:{user['id']}", limit=20, window_s=600)
    try:
        provider = get_provider(get_settings(conn))
        return sg.refine_group(conn, provider, body.topic.strip(), body.audience, body.group,
                               [i.model_dump() for i in body.items])
    except ProviderError as e:
        raise HTTPException(400, str(e))
