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
