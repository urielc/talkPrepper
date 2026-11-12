"""Who a lesson is for: the class named in the AI prompts, and talk audience tags.

An audience key is ``<audience>`` or ``<audience>-<gender>``: ``adults-male``,
``adults-female``, ``adults``, ``youth-male``, ``youth-female``, ``youth``,
``children``. A lesson without one is an elders quorum lesson (``adults-male``),
which is what the app was built for.
"""

from __future__ import annotations

import re

AUDIENCES = ("children", "youth", "adults")
GENDERS = ("male", "female")
DEFAULT_KEY = "adults-male"

# key -> (class named in the prompt, who is in it)
CLASSES: dict[str, tuple[str, str]] = {
    "adults-male": ("an elders quorum", "a quorum of adult men"),
    "adults-female": ("a Relief Society", "a Relief Society class of adult women"),
    "adults": ("an adult Sunday School class", "an adult Sunday School class of men and women"),
    "youth-male": ("an Aaronic Priesthood quorum", "an Aaronic Priesthood quorum of young men aged 11 to 18"),
    "youth-female": ("a Young Women class", "a Young Women class of young women aged 11 to 18"),
    "youth": ("a youth Sunday School class", "a youth Sunday School class of young men and young women aged 11 to 18"),
    "children": ("a Primary class", "a Primary class of children aged 3 to 11"),
}

# Extra guidance for the discussion questions, by age group.
QUESTION_STYLE = {
    "adults": "Connect the teaching to their week, families, callings and ministering.",
    "youth": "Use plain words and situations from school, friends, phones, family and seminary; "
             "invite them to share experiences and to act on what they learn.",
    "children": "Keep each question short and concrete, in words a child knows. Favor questions a child can "
                "answer from their own life, and ideas for simple activities (drawing, acting out, singing).",
}


def audience_key(audience: str | None, gender: str | None = None) -> str:
    """Normalize a (audience, gender) choice to a key. Unknown input gives the default."""
    a = (audience or "").strip().lower()
    g = (gender or "").strip().lower()
    if a not in AUDIENCES:
        return DEFAULT_KEY
    if a == "children" or g not in GENDERS:
        return a
    return f"{a}-{g}"


def parse_key(key: str | None) -> tuple[str, str | None]:
    """'youth-female' -> ('youth', 'female'); unknown -> the default."""
    if key not in CLASSES:
        key = DEFAULT_KEY
    a, _, g = key.partition("-")
    return a, (g or None)


def class_name(key: str | None) -> str:
    return CLASSES.get(key or DEFAULT_KEY, CLASSES[DEFAULT_KEY])[0]


def class_members(key: str | None) -> str:
    return CLASSES.get(key or DEFAULT_KEY, CLASSES[DEFAULT_KEY])[1]


def question_style(key: str | None) -> str:
    return QUESTION_STYLE[parse_key(key)[0]]


def label(key: str | None) -> str:
    """Short UI label: 'Relief Society', 'Young Women', 'Primary', …"""
    name = class_name(key)
    return re.sub(r"^an? ", "", name)


# ---------------------------------------------------------------- talk audience tags

_CALLING_RE = re.compile(
    r"^(?:(?:First|Second)\s+)?(?:Counselor in the |Assistant to the )?.{0,60}"
    r"(?:Presidency|President|Bishopric|Bishop|Seventy|Twelve|Apostles|Church|Patriarch|Secretary|Director|"
    r"Committee|Department|Member|Presiding)",
)


def parse_calling(paragraphs: list[str]) -> str:
    """The speaker's calling, from the line after "By …" at the top of a talk."""
    for i, p in enumerate(paragraphs[:3]):
        if re.match(r"(?:Presented by|By)\s", p) and i + 1 < len(paragraphs):
            nxt = paragraphs[i + 1].strip()
            if len(nxt) <= 120 and not nxt.endswith((".", "?", "!", "”")) and _CALLING_RE.match(nxt):
                return nxt
            return ""
    return ""


# Session business (sustainings, reports) names every auxiliary but is for no one in particular.
_BUSINESS = re.compile(r"\b(?:Sustaining|Statistical Report|Audit(?:ing)?|Solemn Assembly)\b", re.IGNORECASE)


def _count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, re.IGNORECASE))


def talk_audience_tags(title: str, speaker: str, calling: str, body: str) -> list[str]:
    """Soft audience signals for one talk.

    Conference sessions are not scraped, so these come from the speaker's calling
    and from who the talk addresses: a priesthood-session talk keeps saying
    "brethren", a women's-session talk "sisters", a youth talk "young women" and
    "young men", a talk for Primary children "boys and girls"."""
    if _BUSINESS.search(title):
        return []
    tags: set[str] = set()
    c = calling.lower()
    if "primary" in c:
        tags.add("children")
    if "young women" in c:
        tags |= {"youth", "female"}
    if "young men" in c:
        tags |= {"youth", "male"}
    if "relief society" in c:
        tags.add("female")

    text = f"{title}\n{body}"
    words = max(len(body.split()), 1)
    per_k = 1000 / words
    sisters = _count(r"\b(?:my )?(?:dear )?sisters\b", text)
    brethren = _count(r"\bbrethren\b", text)
    youth = (_count(r"\byoung women\b", text) + _count(r"\byoung men\b", text) + _count(r"\byouth\b", text)
             + _count(r"\b(?:deacons?|teachers quorum|priests quorum|Aaronic Priesthood)\b", text)
             + _count(r"\bteenagers?\b", text))
    children = (_count(r"\bboys and girls\b", text) + _count(r"\bPrimary\b", text)
                + _count(r"\blittle children\b", text) + _count(r"\bchildren of (?:the )?Primary\b", text))

    if sisters * per_k >= 2.0 and sisters >= 3 and sisters > 2 * brethren:
        tags.add("female")
    if brethren * per_k >= 2.0 and brethren >= 3 and brethren > 2 * sisters:
        tags.add("male")
    if youth * per_k >= 3.0 and youth >= 5:
        tags.add("youth")
    if children * per_k >= 2.0 and children >= 4:
        tags.add("children")
    if re.search(r"\b(?:young women|young men|youth|teenagers?)\b", title, re.IGNORECASE):
        tags.add("youth")
    if re.search(r"\b(?:children|Primary)\b", title):
        tags.add("children")
    return sorted(tags)
