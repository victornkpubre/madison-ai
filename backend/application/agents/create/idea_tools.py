"""
idea_tools.py
=============
Tools and data layer for the StreamEye Idea Generator.

Four concerns:
  Profile management   — save/retrieve the creator's structured profile
  Content history      — track past topics and formats to avoid repetition
  Audience signals     — ingest raw messages and extract intelligence
  Idea generation      — synthesise everything into actionable content ideas

Audience intelligence metrics computed per topic:
  frequency      — total times a topic has been mentioned
  velocity       — rate of growth in mentions (recent vs older)
  curiosity_score — proportion of mentions that are questions
  sentiment       — weighted average sentiment (-1 negative to +1 positive)

Questions are detected by the LLM (is_question=True in signal analysis),
contributing to curiosity_score.  Requests are also flagged (is_request=True),
contributing to a separate request_score on the topic row.
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from langchain_core.tools import tool

from config import settings

# ── in-memory fallback stores ─────────────────────────────────────────────────
_profile: dict = {}
_content_history: list[dict] = []
_signals: list[dict] = []
_topic_analytics: dict[str, dict] = {}

# ── DB helpers ────────────────────────────────────────────────────────────────

# ── profile management ────────────────────────────────────────────────────────

PROFILE_FIELDS = {
    "niche":            "Main content area (fitness, finance, cooking, etc.)",
    "sub_niche":        "Specific focus within the niche",
    "target_audience":  "Who the content is for (demographics, interests, pain points)",
    "platforms":        "Where the creator posts (list of platforms)",
    "content_style":    "Communication style (educational, entertaining, motivational...)",
    "monetization":     "Revenue streams (sponsorships, courses, memberships, tips...)",
}


@tool
def save_profile_field(field: str, value: str) -> str:
    """
    Save a single creator profile field.
    Call this as each piece of profile information is gathered.

    Args:
        field: one of niche, sub_niche, target_audience, platforms,
               content_style, monetization
        value: the extracted value from the creator's answer
    """
    if field not in PROFILE_FIELDS:
        return f"Unknown field '{field}'. Valid fields: {', '.join(PROFILE_FIELDS)}"

    if settings.database_url:
        from database import upsert_profile_field
        upsert_profile_field(field, value)
    else:
        _profile[field] = value

    return f"✓ Saved {field} = {value!r}"


@tool
def get_profile_status() -> str:
    """
    Return which profile fields have been collected and which are still missing.
    Call this to track progress and decide what to ask next.
    """
    if settings.database_url:
        from database import load_profile as db_load
        profile = db_load()
    else:
        profile = _profile

    filled   = {k: v for k, v in profile.items() if v}
    missing  = [k for k in PROFILE_FIELDS if k not in filled or not filled[k]]

    lines = ["Creator profile status:"]
    for k, v in filled.items():
        lines.append(f"  ✓  {k:<20} {str(v)[:60]}")
    for k in missing:
        lines.append(f"  ○  {k:<20} (not yet collected)")
    lines.append(f"\n{len(filled)}/{len(PROFILE_FIELDS)} fields complete.")
    return "\n".join(lines)


def load_profile() -> dict:
    """Internal: load the full profile dict for use in idea generation."""
    if settings.database_url:
        from database import load_profile as db_load
        return db_load()
    return dict(_profile)


# ── content history ───────────────────────────────────────────────────────────

@tool
def add_content_item(title: str, topic: str,
                     content_type: str, platform: str = "") -> str:
    """
    Add a piece of historical content to the creator's content library.
    This helps the idea generator avoid repetition and understand coverage gaps.

    Args:
        title:        title or description of the content piece
        topic:        the main topic or theme (keep it concise, 3-5 words)
        content_type: one of video, photo, live, digital
        platform:     where it was posted (optional)
    """
    item = {
        "title":        title,
        "topic":        topic,
        "content_type": content_type,
        "platform":     platform,
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }
    if settings.database_url:
        from database import insert_content_item as db_insert
        db_insert(title, topic, content_type, platform)
    else:
        _content_history.append(item)

    return f"✓ Added: {content_type} — '{title}' (topic: {topic})"


@tool
def get_content_history_summary() -> str:
    """
    Return a summary of the content topics already covered.
    Use this to identify gaps and avoid suggesting already-done topics.
    """
    if settings.database_url:
        from database import load_content_history_summary
        items = load_content_history_summary()
    else:
        items = list(_content_history)

    if not items:
        return "No content history recorded yet."

    by_type: dict[str, list] = {}
    for item in items:
        by_type.setdefault(item["content_type"], []).append(item["topic"])

    lines = [f"Content history ({len(items)} items):"]
    for ctype, topics in by_type.items():
        lines.append(f"  {ctype}: {', '.join(topics[:10])}"
                     + (" ..." if len(topics) > 10 else ""))
    return "\n".join(lines)


def load_content_topics() -> list[str]:
    """Internal: return a flat list of covered topics for the idea generator."""
    if settings.database_url:
        from database import load_content_topics as db_load
        return db_load()
    return [item["topic"] for item in _content_history if item.get("topic")]


# ── audience signals ──────────────────────────────────────────────────────────

def ingest_signal(content: str, source: str = "telegram",
                  session_id: str = "") -> None:
    """
    Store a raw audience message for later analysis.
    Called from telegram_webhook, email_webhook, or capture results.
    """
    if settings.database_url:
        from database import insert_signal
        insert_signal(content, source, session_id or "")
    else:
        _signals.append({
            "content":    content,
            "source":     source,
            "session_id": session_id,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        })


async def _analyse_signals_with_llm(raw_texts: list[str]) -> list[dict]:
    """
    Use the LLM to extract topic, sentiment, is_question, is_request from messages.
    Returns a list of dicts with those fields.
    """
    if not raw_texts:
        return []

    batch     = raw_texts[:100]   # cap to avoid token limits
    formatted = "\n".join(f"{i+1}. {t}" for i, t in enumerate(batch))
    prompt    = (
        "Analyse these audience messages from a creator's community. "
        "For each message return a JSON object with:\n"
        "  topic (2-4 word phrase), sentiment (-1.0 to 1.0),\n"
        "  is_question (true/false), is_request (true/false)\n"
        "Return a JSON array only, no other text.\n\n"
        f"Messages:\n{formatted}"
    )

    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {settings.openai_api_key}",
    }
    body = {
        "model":       settings.openai_model,
        "max_tokens":  2000,
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers, json=body,
        )
    raw = r.json()["choices"][0]["message"]["content"].strip()
    raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except Exception:
        return []


@tool
async def analyze_audience() -> str:
    """
    Analyse all stored audience signals to compute topic intelligence.
    Updates topic_analytics with frequency, velocity, curiosity score,
    question and request aggregations, and sentiment trends.
    Call this before generate_ideas() to get the richest idea set.
    """
    if settings.database_url:
        from database import load_unanalysed_signals
        raw = load_unanalysed_signals()
    else:
        raw = [s for s in _signals if not s.get("signal_type")]

    if not raw:
        return ("No unanalysed audience signals found. "
                "Signals are collected automatically from Telegram messages, "
                "email replies, and captured chat content.")

    texts    = [r["content"] for r in raw]
    analysed = await _analyse_signals_with_llm(texts)

    now      = datetime.now(timezone.utc)
    cutoff   = now - timedelta(days=7)

    # Accumulate per-topic stats
    topic_stats: dict[str, dict] = {}
    for i, (sig, ana) in enumerate(zip(raw, analysed)):
        topic = (ana.get("topic") or "general").lower().strip()
        ts    = sig.get("timestamp") or sig.get("created_at")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts = now

        if topic not in topic_stats:
            topic_stats[topic] = {
                "frequency": 0, "recent": 0,
                "questions": 0, "requests": 0,
                "sentiment_sum": 0.0, "sentiment_count": 0,
            }

        t = topic_stats[topic]
        t["frequency"]  += 1
        if isinstance(ts, datetime) and ts >= cutoff:
            t["recent"] += 1
        if ana.get("is_question"):
            t["questions"] += 1
        if ana.get("is_request"):
            t["requests"]  += 1
        sent = float(ana.get("sentiment", 0))
        t["sentiment_sum"]   += sent
        t["sentiment_count"] += 1

        # Mark signal as analysed
        stype = ("question" if ana.get("is_question") else
                 "request"  if ana.get("is_request")  else
                 "positive" if sent > 0.2              else
                 "negative" if sent < -0.2             else "neutral")
        if settings.database_url:
            from database import update_signal_topic
            update_signal_topic(sig["id"], stype, topic)
        else:
            _signals[i]["signal_type"] = stype
            _signals[i]["topic"]       = topic

    # Persist topic analytics
    summary_lines = [f"Analysed {len(analysed)} signals across {len(topic_stats)} topics:"]
    for topic, t in sorted(topic_stats.items(),
                           key=lambda x: -x[1]["frequency"])[:15]:
        freq     = t["frequency"]
        velocity = t["recent"] / max(freq, 1)
        curiosity = t["questions"] / max(freq, 1)
        sentiment = (t["sentiment_sum"] / t["sentiment_count"]
                     if t["sentiment_count"] else 0.0)

        if settings.database_url:
            from database import upsert_topic_analytics
            upsert_topic_analytics(topic, freq, velocity, curiosity,
                                   t["questions"], t["requests"], sentiment)
        else:
            _topic_analytics[topic] = {
                "frequency":      freq,
                "velocity":       round(velocity, 3),
                "curiosity_score": round(curiosity, 3),
                "question_count": t["questions"],
                "request_count":  t["requests"],
                "sentiment":      round(sentiment, 3),
            }

        trend = "↑" if velocity > 0.3 else "→"
        senti = "+" if sentiment > 0.1 else ("-" if sentiment < -0.1 else "~")
        summary_lines.append(
            f"  {trend} {topic:<25} freq={freq}  "
            f"curiosity={curiosity:.0%}  sentiment={senti}"
        )

    return "\n".join(summary_lines)


def load_topic_analytics(limit: int = 20) -> list[dict]:
    """Internal: load top topics by frequency for the idea generator."""
    if settings.database_url:
        from database import load_topic_analytics as db_load
        return db_load(limit)
    return sorted(_topic_analytics.values(),
                  key=lambda x: -x.get("frequency", 0))[:limit]


# ── idea generation ───────────────────────────────────────────────────────────

IDEA_SYSTEM_PROMPT = """You are a strategic content advisor for digital creators.
You will receive a creator's profile, their content history, and audience intelligence data.
Generate specific, actionable content ideas in four categories.

For each idea include:
  title    — a clear, compelling title
  angle    — the specific angle or hook that makes it fresh
  reason   — why this will resonate with the audience (cite the data)
  format   — specific format notes (length, structure, CTA)

Return valid JSON only with this structure:
{
  "videos": [...],
  "pictures": [...],
  "live_activities": [...],
  "digital_services": [...]
}
Each array should contain 4-6 idea objects."""


async def _call_llm_for_ideas(prompt: str) -> dict:
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {settings.openai_api_key}",
    }
    body = {
        "model":       settings.openai_model,
        "max_tokens":  3000,
        "temperature": 0.8,
        "messages": [
            {"role": "system", "content": IDEA_SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers, json=body,
        )
    raw = r.json()["choices"][0]["message"]["content"].strip()
    raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()
    return json.loads(raw)


@tool
async def generate_ideas() -> str:
    """
    Generate content ideas for videos, pictures, live stream activities,
    and digital services. Uses the creator's profile, content history,
    and audience intelligence to produce targeted, data-driven suggestions.
    Call this after the profile is complete and analyze_audience() has run.
    """
    profile  = load_profile()
    history  = load_content_topics()
    topics   = load_topic_analytics()

    if not profile.get("niche"):
        return (
            "Cannot generate ideas yet — the creator profile is incomplete. "
            "At minimum, niche is required. Call get_profile_status() to see "
            "what is missing."
        )

    # Build the analysis prompt
    top_topics = [t for t in topics if t.get("frequency", 0) > 0]
    questions  = [t for t in topics if t.get("curiosity_score", 0) > 0.3]
    requests   = [t for t in topics if t.get("request_count", 0) > 0]
    trending   = sorted(topics, key=lambda x: -x.get("velocity", 0))[:5]
    neg_topics = [t for t in topics if t.get("sentiment", 0) < -0.1]

    prompt = f"""CREATOR PROFILE
Niche:           {profile.get('niche', 'not set')}
Sub-niche:       {profile.get('sub_niche', 'not set')}
Target audience: {profile.get('target_audience', 'not set')}
Platforms:       {profile.get('platforms', 'not set')}
Content style:   {profile.get('content_style', 'not set')}
Monetization:    {profile.get('monetization', 'not set')}

CONTENT HISTORY (topics already covered — avoid repeating these)
{chr(10).join(f"  - {t}" for t in history[:30]) or "  No history recorded."}

AUDIENCE INTELLIGENCE
Top topics by frequency:
{chr(10).join(f"  - {t['topic']} (freq={t['frequency']}, sentiment={t['sentiment']:+.2f})" for t in top_topics[:10]) or "  No data yet."}

High curiosity topics (questions being asked):
{chr(10).join(f"  - {t['topic']} (curiosity={t['curiosity_score']:.0%}, {t['question_count']} questions)" for t in questions[:8]) or "  None detected."}

Active viewer requests:
{chr(10).join(f"  - {t['topic']} ({t['request_count']} requests)" for t in requests[:8]) or "  None detected."}

Trending topics (rising fast):
{chr(10).join(f"  - {t['topic']} (velocity={t['velocity']:.0%})" for t in trending) or "  None detected."}

Negative sentiment areas (audience pain points — opportunity for solutions):
{chr(10).join(f"  - {t['topic']} (sentiment={t['sentiment']:+.2f})" for t in neg_topics[:5]) or "  None."}

Generate 4-6 ideas per category. Prioritise:
1. Topics with high curiosity score (unmet questions = content gap)
2. Topics with high velocity (trending = timely opportunity)
3. Negative sentiment topics (pain points = high value if addressed)
4. Topics NOT in the content history (coverage gaps)
5. Ideas that fit the monetization model: {profile.get('monetization', 'not specified')}"""

    try:
        ideas = await _call_llm_for_ideas(prompt)
    except Exception as e:
        return f"Idea generation failed: {e}"

    # Format for display
    lines = ["Content Ideas Generated\n" + "=" * 50]
    labels = {
        "videos":           "VIDEO IDEAS",
        "pictures":         "PICTURE / PHOTO IDEAS",
        "live_activities":  "LIVE STREAM ACTIVITIES",
        "digital_services": "DIGITAL SERVICES",
    }
    for key, label in labels.items():
        category = ideas.get(key, [])
        if not category:
            continue
        lines.append(f"\n{label}")
        lines.append("-" * 40)
        for i, idea in enumerate(category, 1):
            lines.append(f"\n{i}. {idea.get('title', 'Untitled')}")
            if idea.get("angle"):
                lines.append(f"   Angle:  {idea['angle']}")
            if idea.get("reason"):
                lines.append(f"   Why:    {idea['reason']}")
            if idea.get("format"):
                lines.append(f"   Format: {idea['format']}")

    return "\n".join(lines)


IDEA_TOOLS = [
    save_profile_field,
    get_profile_status,
    add_content_item,
    get_content_history_summary,
    analyze_audience,
    generate_ideas,
]
