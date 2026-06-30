"""
idea_schemas.py
═════════════════════
Structured-output contracts for the idea-generation and audience-
analysis LLM calls made by IdeaService.

Kept separate from domain/ideas/idea_entity.py: these are LLM I/O
shapes (what we ask gpt-4o-mini to return), not persisted domain
entities.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IdeaScore(BaseModel):
    score: float = Field(description="0.0-1.0 fit against the creator's niche, content_style, and target_audience")
    critique: str = Field(description="Specific, actionable feedback if the score is low; empty string if not needed")


class TopicCluster(BaseModel):
    topic: str
    count: int
    sample_messages: list[str]


class TopicClusters(BaseModel):
    clusters: list[TopicCluster]


class SentimentResult(BaseModel):
    overall: Literal["positive", "neutral", "mixed", "negative"]
    summary: str


class AudienceSynthesis(BaseModel):
    summary: str = Field(description="Narrative summary of what this audience cares about and how they feel")
    gaps: list[str] = Field(description="Specific topics raised repeatedly with no clear answer yet")


class AudienceScore(BaseModel):
    score: float = Field(description="0.0-1.0 — is the summary/gaps genuinely grounded in the sample messages?")
    critique: str = Field(description="What's ungrounded or fabricated, if anything; empty string if not needed")


class OtherStreamAnalysis(BaseModel):
    topic: str = Field(description="Short label for what the other stream appears to be about")
    summary: str = Field(description="2-4 sentence report: what's happening, what's being discussed or shown")
    relevant: bool = Field(description="True if this overlaps enough with the creator's own niche/audience to be worth learning from")
    relevance_reason: str = Field(description="One sentence explaining the relevance verdict")
    ideas: list[str] = Field(description="2-4 related content ideas for the creator, inspired by but distinct from the other stream")


class ExtractedComment(BaseModel):
    author: str | None = Field(default=None, description="Comment author's display name, null if not visible")
    text: str = Field(description="The comment text")
    likes: int | None = Field(default=None, description="Like count on this comment, null if not visible")


class PostScreenshotExtraction(BaseModel):
    """Vision-extraction output for a screenshot of another creator's post/
    video page — see IdeaService.analyze_other_post_screenshot(). Pure
    extraction: no relevance/idea reasoning happens at this stage."""
    caption: str = Field(default="", description="The post's caption/description text; empty string if none visible")
    hashtags: list[str] = Field(default_factory=list, description="Hashtags visible in the caption, without the # symbol")
    like_count: int | None = Field(default=None, description="Like count shown on the post, null if not visible")
    comment_count: int | None = Field(default=None, description="Comment count shown on the post, null if not visible")
    save_count: int | None = Field(default=None, description="Save/bookmark count shown on the post, null if not visible")
    comments: list[ExtractedComment] = Field(default_factory=list, description="Visible comments, top to bottom")
