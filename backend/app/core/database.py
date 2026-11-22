"""Database connection and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency that provides a database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create all tables on startup."""
    from app.core.migrations import migrate_changeover_table

    async with engine.begin() as conn:
        # Model modules must be imported so their tables are registered before migrating.
        import app.models.schemas  # noqa: F401

        await conn.run_sync(migrate_changeover_table)
        await conn.run_sync(Base.metadata.create_all)
