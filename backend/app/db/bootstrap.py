from sqlalchemy import inspect, select, text, update

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.models import User, Job
from app.db.session import SessionLocal, engine


def bootstrap_database() -> None:
    # Local SQLite installs historically used create_all instead of Alembic.
    # Add only the new nullable ownership column; never rewrite existing data.
    if engine.dialect.name == "sqlite" and inspect(engine).has_table("jobs"):
        if "owner_id" not in {c["name"] for c in inspect(engine).get_columns("jobs")}:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN owner_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"))
    Base.metadata.create_all(bind=engine)
    settings = get_settings()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == settings.admin_username))
        if user is None:
            db.add(
                User(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                )
            )
            db.commit()

        admin = db.scalar(select(User).where(User.username == settings.admin_username))
        if admin is not None:
            db.execute(update(Job).where(Job.owner_id.is_(None)).values(owner_id=admin.id))
            db.commit()
