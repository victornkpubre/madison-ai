from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.infrastructure.database.models import EmailAccount


class EmailRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_smtp(self, email: str, password: str,
                          display_name: str | None = None,
                          smtp_host: str | None    = None,
                          smtp_port: int           = 587,
                          imap_host: str | None    = None,
                          imap_port: int           = 993) -> None:
        await self.session.execute(
            pg_insert(EmailAccount)
            .values(email=email.lower(), provider="smtp",
                    display_name=display_name, access_token=password,
                    smtp_host=smtp_host, smtp_port=smtp_port,
                    imap_host=imap_host, imap_port=imap_port,
                    updated_at=func.now())
            .on_conflict_do_update(
                index_elements=["email"],
                set_=dict(display_name=display_name, access_token=password,
                          smtp_host=smtp_host, smtp_port=smtp_port,
                          imap_host=imap_host, imap_port=imap_port,
                          updated_at=func.now()),
            )
        )
        await self.session.commit()

    async def get_smtp(self, email: str) -> dict | None:
        result = await self.session.execute(
            select(EmailAccount)
            .where(EmailAccount.email    == email.lower(),
                   EmailAccount.provider == "smtp")
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {"email":        row.email,
                "display_name": row.display_name,
                "password":     row.access_token,
                "smtp_host":    row.smtp_host,
                "smtp_port":    row.smtp_port,
                "imap_host":    row.imap_host,
                "imap_port":    row.imap_port}

    async def list_all(self, limit: int = 50) -> list[dict]:
        result = await self.session.execute(
            select(EmailAccount.email, EmailAccount.provider,
                   EmailAccount.display_name)
            .order_by(EmailAccount.created_at)
            .limit(limit)
        )
        return [{"email": r.email, "provider": r.provider,
                 "display_name": r.display_name}
                for r in result.all()]
