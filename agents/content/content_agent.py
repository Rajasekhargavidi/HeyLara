"""Content Agent — Phase 7.

Generates platform-specific post copy, hashtags, and CTAs via the
LLMProvider, plus creative concepts (short-form video, carousel) per the
CONTENT PROMPT in the master build spec. Supports generating multiple
variants so a marketer can pick the best one. Constrained against
fabricated statistics, testimonials, customers, or capabilities.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from packages.config.llm_provider import LLMProvider

logger = logging.getLogger("jarvis.content_agent")

BASE_RULES = (
    "You write social content for LaraVisionX, an AI/automation company. "
    "Voice: professional but approachable. "
    "Never fabricate statistics, testimonials, customers, or capabilities. "
    "Never make claims about pricing, guarantees, or timelines. "
    "Keep technical claims accurate and sourceable. Avoid spammy repetition "
    "or misleading engagement bait."
)

_PLATFORM_STYLE = {
    "LINKEDIN": "A LinkedIn post: professional tone, up to 120 words, one clear insight.",
    "INSTAGRAM": "An Instagram caption: friendly tone, short, can use light emoji, up to 60 words.",
    "FACEBOOK": "A Facebook post: conversational tone, up to 90 words.",
    "X": "An X (Twitter) post: punchy, under 280 characters total including hashtags.",
}

_POST_SYSTEM_PROMPT = (
    BASE_RULES + " Respond with ONLY a single JSON object, no other text, matching exactly: "
    '{"content": "...", "hashtags": ["#tag1", "#tag2"], "cta": "..."}. '
    "hashtags: 1-3 relevant hashtags, no more. cta: a short call to action sentence."
)

_CONCEPTS_SYSTEM_PROMPT = (
    BASE_RULES + " Respond with ONLY a single JSON object, no other text, matching exactly: "
    '{"short_form_video_concept": "...", "carousel_concept": "...", '
    '"hashtags": ["#tag1", "#tag2"], "cta": "..."}. '
    "short_form_video_concept: a 2-3 sentence concept for a 30-60s vertical video. "
    "carousel_concept: a 2-3 sentence concept describing what each slide of a "
    "multi-slide carousel post would cover."
)


@dataclass
class PostContent:
    content: str
    hashtags: list[str] = field(default_factory=list)
    cta: str = ""


@dataclass
class CreativeConcepts:
    short_form_video_concept: str
    carousel_concept: str
    hashtags: list[str] = field(default_factory=list)
    cta: str = ""


def _parse_json_object(raw: str) -> dict | None:
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return None


def generate_post_content(llm: LLMProvider, topic: str, platform: str) -> PostContent:
    style = _PLATFORM_STYLE.get(platform, _PLATFORM_STYLE["LINKEDIN"])
    prompt = f"Write {style}\n\nTopic: {topic}"
    fallback = PostContent(
        content=f"[DRAFT — LLM unavailable, template fallback] {topic}. Review before approving.",
        hashtags=["#AI", "#Automation"],
        cta="Learn more.",
    )
    try:
        raw = llm.generate(prompt, system=_POST_SYSTEM_PROMPT).strip()
    except RuntimeError:
        return fallback

    parsed = _parse_json_object(raw)
    if not parsed or "content" not in parsed:
        logger.warning("content_agent: could not parse model output for topic '%s', using fallback", topic)
        return PostContent(content=raw or fallback.content, hashtags=fallback.hashtags, cta=fallback.cta)

    hashtags = parsed.get("hashtags") or fallback.hashtags
    if not isinstance(hashtags, list):
        hashtags = fallback.hashtags
    return PostContent(content=str(parsed["content"]), hashtags=[str(h) for h in hashtags][:3], cta=str(parsed.get("cta", "")))


def generate_variants(llm: LLMProvider, topic: str, platform: str, count: int = 3) -> list[PostContent]:
    count = max(1, min(count, 3))
    variants: list[PostContent] = []
    seen_content: set[str] = set()
    # Ask independently per variant rather than one big JSON array — small local
    # models are far more reliable producing one object at a time than a list.
    attempts = 0
    while len(variants) < count and attempts < count + 2:
        attempts += 1
        nudge = "" if attempts == 1 else " Make this variant clearly different in angle or phrasing from a typical one."
        v = generate_post_content(llm, topic + nudge, platform)
        if v.content not in seen_content:
            variants.append(v)
            seen_content.add(v.content)
    return variants


def generate_creative_concepts(llm: LLMProvider, topic: str) -> CreativeConcepts:
    prompt = f"Topic: {topic}"
    fallback = CreativeConcepts(
        short_form_video_concept="[LLM unavailable] Review manually — describe a 30-60s video about the topic.",
        carousel_concept="[LLM unavailable] Review manually — describe a multi-slide carousel about the topic.",
        hashtags=["#AI", "#Automation"],
        cta="Learn more.",
    )
    try:
        raw = llm.generate(prompt, system=_CONCEPTS_SYSTEM_PROMPT).strip()
    except RuntimeError:
        return fallback

    parsed = _parse_json_object(raw)
    if not parsed:
        logger.warning("content_agent: could not parse concepts output for topic '%s', using fallback", topic)
        return fallback

    hashtags = parsed.get("hashtags") or fallback.hashtags
    if not isinstance(hashtags, list):
        hashtags = fallback.hashtags
    return CreativeConcepts(
        short_form_video_concept=str(parsed.get("short_form_video_concept", fallback.short_form_video_concept)),
        carousel_concept=str(parsed.get("carousel_concept", fallback.carousel_concept)),
        hashtags=[str(h) for h in hashtags][:3],
        cta=str(parsed.get("cta", fallback.cta)),
    )
