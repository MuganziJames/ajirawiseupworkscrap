"""
Shared data models for all job scrapers.
Maps exactly to the WorkeAfrica database table schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List


@dataclass
class JobListing:
    """
    Represents a single job listing mapped to the WorkeAfrica DB schema.

    Every field here corresponds to a column in the jobs table.
    Fields are populated by the individual scrapers and then serialized
    for storage.
    """

    # ── Identifiers ──────────────────────────────────────────────
    # e.g. "bm-00001", "uw-00001"
    job_id: str = ""
    # auto-increment DB primary key (set by DB)
    id: Optional[int] = None

    # ── Core Job Info ────────────────────────────────────────────
    title: str = ""
    company: str = ""
    company_logo_url: Optional[str] = None

    # ── Location ─────────────────────────────────────────────────
    # "remote", "onsite", "hybrid"
    location_type: Optional[str] = None
    # "Nairobi", "Eldoret", etc.
    specific_location: Optional[str] = None
    # "Kenya"
    country: Optional[str] = None

    # ── Job Classification ───────────────────────────────────────
    # function/category e.g. "Human Resources"
    job_type: Optional[str] = None
    # "Full Time", "Part Time", "Internship & Graduate", "Contract"
    employment_type: Optional[str] = None

    # ── Descriptions (stored with structure tags) ────────────────
    description: Optional[str] = None        # full job description HTML/text
    requirements: Optional[str] = None       # requirements section
    responsibilities: Optional[str] = None   # responsibilities section
    benefits: Optional[str] = None           # benefits / what we offer section

    # ── Experience ───────────────────────────────────────────────
    experience_years_min: Optional[int] = None
    experience_years_max: Optional[int] = None

    # ── Salary ───────────────────────────────────────────────────
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None    # "KSh", "USD", etc.
    salary_disclosed: bool = False           # True if salary was shown

    # ── Application Details ──────────────────────────────────────
    application_url: Optional[str] = None    # direct apply link
    application_email: Optional[str] = None  # email if provided in description
    application_deadline: Optional[str] = None  # deadline string or ISO date

    # ── Company Info ─────────────────────────────────────────────
    company_website: Optional[str] = None

    # ── Source Tracking ──────────────────────────────────────────
    source_platform: str = ""                # "brightermonday", "upwork"
    source_url: str = ""                     # full URL of the job listing

    # ── Dates ────────────────────────────────────────────────────
    posted_date: Optional[str] = None        # when the job was posted
    scraped_at: Optional[str] = None         # when we scraped it (ISO format)
    expires_at: Optional[str] = None         # expiry date if available

    # ── Flags ────────────────────────────────────────────────────
    is_featured: bool = False

    # ── Extracted Metadata ───────────────────────────────────────
    extracted_skills: Optional[List[str]] = field(default_factory=list)
    view_count: Optional[int] = None
    application_count: Optional[int] = None

    # ── Flexible metadata (JSON blob for anything extra) ─────────
    job_metadata: Optional[dict] = field(default_factory=dict)

    # ── Timestamps (set by DB) ───────────────────────────────────
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # ──────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────

    def stamp_scraped_at(self) -> None:
        """Set scraped_at to current UTC time."""
        self.scraped_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        """Convert to a plain dict, serializing nested objects."""
        d = asdict(self)
        # Ensure lists/dicts are JSON-serializable
        if isinstance(d.get("extracted_skills"), list):
            d["extracted_skills"] = json.dumps(d["extracted_skills"])
        if isinstance(d.get("job_metadata"), dict):
            d["job_metadata"] = json.dumps(d["job_metadata"])
        return d

    def to_json(self) -> str:
        """Serialize to JSON string."""
        d = asdict(self)
        return json.dumps(d, indent=2, default=str, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "JobListing":
        """Create a JobListing from a dict (e.g. loaded from JSON)."""
        # Parse JSON strings back into Python objects
        if isinstance(data.get("extracted_skills"), str):
            data["extracted_skills"] = json.loads(data["extracted_skills"])
        if isinstance(data.get("job_metadata"), str):
            data["job_metadata"] = json.loads(data["job_metadata"])
        # Only keep keys that match dataclass fields
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


def jobs_to_json(jobs: List[JobListing]) -> str:
    """Serialize a list of JobListing objects to a JSON string."""
    import json as _json
    return _json.dumps(
        [json.loads(j.to_json()) for j in jobs],
        indent=2,
        ensure_ascii=False,
    )
