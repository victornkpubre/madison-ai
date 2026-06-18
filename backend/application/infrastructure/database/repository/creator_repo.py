from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.infrastructure.database.models import CreatorIdeaProfile, CreatorProfile

_IDEA_FIELDS = frozenset(
    {"niche", "sub_niche", "target_audience",
     "platforms", "content_style", "monetization"}
)


class CreatorRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── public profile (name, bio, cta) ───────────────────────────────────────

    async def upsert_profile(self, name: str, bio: str, cta: str,
                              email: str | None = None) -> None:
        await self.session.execute(
            pg_insert(CreatorProfile)
            .values(id=1, name=name, bio=bio, cta=cta,
                    email=email, updated_at=func.now())
            .on_conflict_do_update(
                index_elements=["id"],
                set_=dict(name=name, bio=bio, cta=cta,
                          email=email, updated_at=func.now()),
            )
        )
        await self.session.commit()

    async def get_profile(self) -> dict:
        result = await self.session.execute(
            select(CreatorProfile).where(CreatorProfile.id == 1)
        )
        row = result.scalar_one_or_none()
        if not row:
            return {}
        return {"name": row.name, "bio": row.bio,
                "cta":  row.cta,  "email": row.email}

    # ── idea profile (niche, style, audience) ─────────────────────────────────

    async def upsert_idea_field(self, field: str, value: str) -> None:
        if field not in _IDEA_FIELDS:
            raise ValueError(f"Unknown idea profile field: {field!r}")
        await self.session.execute(
            pg_insert(CreatorIdeaProfile)
            .values(id=1, **{field: value}, updated_at=func.now())
            .on_conflict_do_update(
                index_elements=["id"],
                set_={field: value, "updated_at": func.now()},
            )
        )
        await self.session.commit()

    async def get_idea_profile(self) -> dict:
        result = await self.session.execute(
            select(CreatorIdeaProfile).where(CreatorIdeaProfile.id == 1)
        )
        row = result.scalar_one_or_none()
        if not row:
            return {}
        return {"niche":           row.niche,
                "sub_niche":       row.sub_niche,
                "target_audience": row.target_audience,
                "platforms":       row.platforms,
                "content_style":   row.content_style,
                "monetization":    row.monetization}
