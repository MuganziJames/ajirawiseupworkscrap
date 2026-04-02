"""
Database Storage Module
=======================
Connects to the WorkeAfrica PostgreSQL database and inserts scraped jobs
using asyncpg + SQLAlchemy async.

The schema matches the `job_listings` table in the production backend.
Uses ON CONFLICT DO NOTHING on `job_id` for deduplication.

Usage:
    from db_storage import push_jobs_to_db
    import asyncio

    asyncio.run(push_jobs_to_db(jobs_list))
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import sys
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    Date,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import DATABASE_URL, DATABASE_ECHO, LOG_FORMAT, LOG_DATE_FORMAT
from models import JobListing

logger = logging.getLogger("db_storage")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    logger.addHandler(_handler)


# ──────────────────────────────────────────────
# SQLAlchemy ORM Model (mirrors backend's job_listings table)
# ──────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class JobListingDB(Base):
    __tablename__ = "job_listings"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    job_id = Column(String(20), unique=True, nullable=False, index=True)

    # Core
    title = Column(Text, nullable=False)
    company = Column(Text, nullable=False)
    company_logo_url = Column(Text)
    location_type = Column(String(20), nullable=False, default="on-site")
    specific_location = Column(Text)
    country = Column(Text)
    job_type = Column(Text)
    employment_type = Column(Text)

    # Descriptions
    description = Column(Text)
    requirements = Column(Text)
    responsibilities = Column(Text)
    benefits = Column(Text)

    # Experience
    experience_years_min = Column(Integer)
    experience_years_max = Column(Integer)

    # Salary
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    salary_currency = Column(String(10))
    salary_disclosed = Column(Boolean, nullable=False, default=False)

    # Application
    application_url = Column(Text)
    application_email = Column(Text)
    application_deadline = Column(Date)

    # Company
    company_website = Column(Text)

    # Source
    source_platform = Column(Text)
    source_url = Column(Text)

    # Dates
    posted_date = Column(DateTime)
    scraped_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime)

    # Flags & counters
    is_featured = Column(Boolean, default=False)
    view_count = Column(Integer, default=0)
    application_count = Column(Integer, default=0)

    # AI/backend-populated fields
    extracted_skills = Column(ARRAY(String))
    ai_summary = Column(Text)
    job_embedding = Column(Text)  # pgvector column — leave NULL

    # Metadata
    job_metadata = Column(JSON)

    # Timestamps
    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"))


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _parse_datetime(val: Optional[str]) -> Optional[datetime]:
    """Parse ISO date/datetime string to datetime object."""
    if not val:
        return None
    for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def _parse_date(val: Optional[str]) -> Optional[date]:
    """Parse date string to date object."""
    if not val:
        return None
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def job_to_db_dict(job: JobListing) -> Dict[str, Any]:
    """Convert a scraper JobListing dataclass to a dict for DB insertion."""
    return {
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "company_logo_url": job.company_logo_url,
        "location_type": job.location_type or "on-site",
        "specific_location": job.specific_location,
        "country": job.country,
        "job_type": job.job_type,
        "employment_type": job.employment_type,
        "description": job.description,
        "requirements": job.requirements,
        "responsibilities": job.responsibilities,
        "benefits": job.benefits,
        "experience_years_min": job.experience_years_min,
        "experience_years_max": job.experience_years_max,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "salary_disclosed": job.salary_disclosed,
        "application_url": job.application_url,
        "application_email": job.application_email,
        "application_deadline": _parse_date(job.application_deadline),
        "company_website": job.company_website,
        "source_platform": job.source_platform,
        "source_url": job.source_url,
        "posted_date": _parse_datetime(job.posted_date),
        "scraped_at": _parse_datetime(job.scraped_at) or datetime.utcnow(),
        "expires_at": None,
        "is_featured": job.is_featured,
        "view_count": job.view_count or 0,
        "application_count": job.application_count or 0,
        "extracted_skills": None,
        "ai_summary": None,
        "job_metadata": job.job_metadata if job.job_metadata else None,
    }


# ──────────────────────────────────────────────
# Core DB Operations
# ──────────────────────────────────────────────
def _get_engine():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to your .env file."
        )
    # asyncpg doesn't accept sslmode= in the URL; strip it and pass ssl context
    url = DATABASE_URL
    use_ssl = False
    if "sslmode=" in url:
        use_ssl = "sslmode=require" in url or "sslmode=verify" in url
        # Remove sslmode param from URL
        import re
        url = re.sub(r"[?&]sslmode=[^&]*", "", url)
        # Clean up leftover ? or & at end
        url = url.rstrip("?&")

    connect_args = {}
    if use_ssl:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx

    return create_async_engine(
        url,
        echo=DATABASE_ECHO,
        pool_size=5,
        max_overflow=10,
        connect_args=connect_args,
    )


async def test_connection() -> bool:
    """Test the database connection. Returns True if successful."""
    engine = _get_engine()
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            row = result.scalar()
            if row == 1:
                logger.info("Database connection successful!")
                return True
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        return False
    finally:
        await engine.dispose()
    return False


async def push_jobs_to_db(jobs: List[JobListing]) -> Dict[str, int]:
    """
    Insert scraped jobs into the database.

    Uses INSERT ... ON CONFLICT (job_id) DO NOTHING for deduplication.
    Returns summary: {"saved": N, "skipped": N, "errors": N}
    """
    if not jobs:
        logger.warning("No jobs to push.")
        return {"saved": 0, "skipped": 0, "errors": 0}

    engine = _get_engine()
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    saved = 0
    skipped = 0
    errors = 0

    try:
        async with async_session() as session:
            for job in jobs:
                try:
                    db_dict = job_to_db_dict(job)
                    # Use raw SQL for ON CONFLICT DO NOTHING
                    columns = ", ".join(db_dict.keys())
                    placeholders = ", ".join(f":{k}" for k in db_dict.keys())
                    sql = text(
                        f"INSERT INTO job_listings ({columns}) "
                        f"VALUES ({placeholders}) "
                        f"ON CONFLICT (job_id) DO NOTHING"
                    )
                    result = await session.execute(sql, db_dict)
                    if result.rowcount > 0:
                        saved += 1
                        logger.debug("  Saved: %s — %s", job.job_id, job.title[:40])
                    else:
                        skipped += 1
                        logger.debug("  Skipped (duplicate): %s", job.job_id)
                except Exception as exc:
                    errors += 1
                    logger.error("  Error inserting %s: %s", job.job_id, exc)

            await session.commit()

    except Exception as exc:
        logger.error("Database session error: %s", exc)
        raise
    finally:
        await engine.dispose()

    logger.info(
        "DB push complete — saved: %d | skipped: %d | errors: %d",
        saved, skipped, errors,
    )
    return {"saved": saved, "skipped": skipped, "errors": errors}


# ──────────────────────────────────────────────
# CLI entry point for testing
# ──────────────────────────────────────────────
async def _main():
    """Quick connectivity test."""
    print("Testing database connection...")
    ok = await test_connection()
    if ok:
        # Count existing jobs
        engine = _get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM job_listings"))
            count = result.scalar()
            print(f"Connection OK. Current job_listings count: {count}")
        await engine.dispose()
    else:
        print("Connection FAILED. Check your .env DATABASE_URL.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_main())
