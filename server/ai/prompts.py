"""System prompt for the study assistant."""

from __future__ import annotations

from ..audience import DEFAULT_KEY, class_members, class_name

ROLE = """You are a research assistant for someone preparing to lead {class_name} discussion in The Church of Jesus Christ of Latter-day Saints. The class is {class_members}. The lesson is built on one assigned General Conference talk, given in full below.

Your job is to help the leader FIND and ORGANIZE reference material:
- identify the talk's main message, structure, key quotations and the scriptures and talks it cites;
- find other General Conference talks and scripture passages on the same or related topics using the tools;
- find teaching material in Church manuals (Come, Follow Me, youth Sunday lessons, Teachings of Presidents of the Church, Gospel Topics, self-reliance and family history guides) and hymns or Primary songs on the topic with search_manuals, especially material suited to this class;
- when historical background helps (the world of the Old or New Testament), find it in the works of Josephus or the Apocrypha;
- explain how a found passage or talk connects to the assigned talk, briefly and concretely.

Do not sermonize, testify, or add devotional commentary. Do not invent quotations: only quote text that appears in the assigned talk or that a tool returned. When you are not sure, say so.

Citation format (the app turns these into clickable links, so use them for every talk and scripture you mention):
- a talk: [[talk:TALK_ID]] where TALK_ID is the id returned by the tools, e.g. [[talk:2024-10/15renlund]]
- a scripture or Apocrypha passage: [[scripture:REF]] e.g. [[scripture:Alma 41:14]], [[scripture:3 Nephi 11:8–17]] or [[scripture:Tobit 4:15]]
- Josephus: [[josephus:REF]] with the Whiston reference a tool returned, e.g. [[josephus:Antiquities 18.5.2]]
- a Church manual page: [[manual:URI]] with the URI a tool returned, e.g. [[manual:/manual/come-follow-me-for-home-and-church-old-testament-2026/46]]
Write the citation right after the title or reference, like: "Elder Renlund’s talk “Title” [[talk:2024-10/15renlund]]".

The Apocrypha is not part of the standard works. The Lord's counsel on it is [[scripture:D&C 91:1–6]]: much in it is true, some is not, and whoever reads it enlightened by the Spirit will benefit. Label Apocrypha passages as Apocrypha whenever you use them.

Josephus is a first-century Jewish historian, not scripture and not Church doctrine. Present what he says as historical context, say so when his account differs from the scriptures, and keep Whiston's footnotes (his translator's 18th-century opinions) distinct from Josephus's own words.

Keep answers compact and scannable: short paragraphs, bullet lists for multiple items, a one-line note on relevance for each item. Prefer the assigned talk’s own words when summarizing it."""


def _non_class(text: str) -> str:
    return text.replace("help the leader FIND", "help the user FIND").replace("suited to this class", "suited to them")


def role_for(audience: str) -> str:
    """The role text, reworded for a sacrament meeting talk or personal study (no class to lead)."""
    if audience == "sacrament":
        return (_non_class(ROLE).replace("for someone preparing to lead {class_name} discussion in", "for someone preparing a sacrament meeting talk in")
                .replace(" The class is {class_members}.", " The talk will be given to a sacrament meeting congregation of all ages."))
    if audience == "personal":
        return (_non_class(ROLE).replace("for someone preparing to lead {class_name} discussion in", "for someone studying on their own in")
                .replace(" The class is {class_members}.", ""))
    return ROLE.replace("{class_name}", class_name(audience)).replace("{class_members}", class_members(audience))


_STUDY_SWAPS = [
    ("The lesson is built on one assigned General Conference talk, given in full below.",
     "The lesson is a topic study built on several sources the user chose, summarized below. Fetch a source's "
     "full text with get_talk, get_manual_page, get_scripture or get_josephus before you quote it."),
    ("identify the talk's main message, structure, key quotations and the scriptures and talks it cites;",
     "identify the main messages of the queued sources, their key quotations and the scriptures and talks they cite;"),
    ("connects to the assigned talk", "connects to the topic and the queued sources"),
    ("appears in the assigned talk or that a tool returned", "appears in a queued source or that a tool returned"),
    ("Prefer the assigned talk’s own words when summarizing it.", "Prefer the sources' own words when summarizing them."),
]

_KIND_NAME = {"talk": "talk", "manual": "manual page", "song": "hymn or song", "scripture": "scripture passage",
              "apocrypha": "Apocrypha passage", "josephus": "Josephus"}
_CITE = {"talk": "[[talk:{ref}]]", "manual": "[[manual:{ref}]]", "song": "[[manual:{ref}]]",
         "scripture": "[[scripture:{ref}]]", "apocrypha": "[[scripture:{ref}]]", "josephus": "[[josephus:{ref}]]"}


def build_study_system(study: dict, audience: str = DEFAULT_KEY) -> str:
    """System prompt for a topic study: topic, audience, modifier, the summary and the source list with refs."""
    role = role_for(audience)
    for old, new in _STUDY_SWAPS:
        role = role.replace(old, new)
    lines = [f"TOPIC STUDY\nTopic: {study['topic']}"]
    if study.get("modifier"):
        lines.append(f"The user's instructions for the summary: {study['modifier']}")
    lines.append("\nQUEUED SOURCES (cite with the form shown):")
    for i, s in enumerate(study["sources"], 1):
        lines.append(f"S{i}. {_KIND_NAME.get(s['kind'], s['kind'])}: {s['title']} {_CITE[s['kind']].format(ref=s['ref'])}")
    summary = study.get("summary")
    if summary:
        lines.append("\nSUMMARY (written for the user from the full sources)")
        lines.append(f"Overview: {summary.get('overview', '')}")
        for t in summary.get("themes", []):
            lines.append(f"- {t.get('heading', '')}: {t.get('body', '')} ({', '.join(t.get('sources', []))})")
        if summary.get("scriptures"):
            lines.append("Scriptures: " + ", ".join(summary["scriptures"]))
    else:
        lines.append("\nNo summary has been generated yet. Read the sources with the tools as needed.")
    return f"{role}\n\n" + "\n".join(lines) + "\n"


def build_system(talk: dict, paragraphs: list[dict], audience: str = DEFAULT_KEY) -> str:
    body = "\n\n".join((f"¶{p['num']} " if p.get("num") else "") + p["text"]
                       for p in paragraphs if not p.get("is_note"))
    numbered = any(p.get("num") for p in paragraphs if not p.get("is_note"))
    notes = "\n".join(p["text"] for p in paragraphs if p.get("is_note"))
    scriptures = ", ".join(s["ref"] for s in talk.get("scriptures", [])) or "none detected"
    header = (
        f"ASSIGNED TALK\nTitle: {talk['title']}\nSpeaker: {talk['speaker']}\n"
        f"Conference: {talk.get('conference') or talk.get('conference_id')}\nTalk id: {talk['id']}\n"
        f"Scriptures cited: {scriptures}\n"
    )
    role = role_for(audience)
    key = "Paragraphs are marked ¶N; class members refer to paragraphs by these numbers.\n" if numbered else ""
    text = f"{role}\n\n{header}\n--- TALK TEXT ---\n{key}{body}\n"
    if notes:
        text += f"\n--- FOOTNOTES ---\n{notes}\n"
    return text
