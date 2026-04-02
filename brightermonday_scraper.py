"""
BrighterMonday Job Scraper
==========================
Scrapes job listings from https://www.brightermonday.co.ke/jobs

Features:
  - Paginated listing-page crawling
  - Full job-detail extraction per listing
  - Salary, experience, and date parsing
  - Structured data mapped to WorkeAfrica DB schema
  - Rate limiting, retries, and polite crawling
  - JSON output ready for DB ingestion

Usage:
    python brightermonday_scraper.py
    python brightermonday_scraper.py --pages 10
    python brightermonday_scraper.py --pages all
    python brightermonday_scraper.py --pages 2 --output jobs.json
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from config import (
    BM_BASE_URL,
    BM_COUNTRY,
    BM_JOBS_URL,
    BM_JOB_ID_PREFIX,
    BM_SOURCE_PLATFORM,
    DEFAULT_MAX_PAGES,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    LOG_LEVEL,
    MAX_RETRIES,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF,
    get_output_filename,
)
from models import JobListing, jobs_to_json

# Logger Setup
logger = logging.getLogger("brightermonday")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
logger.addHandler(_handler)


def _polite_sleep() -> None:
    """Sleep for a random interval to be polite to the server."""
    delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    time.sleep(delay)


def _fetch(url: str, session: requests.Session) -> Optional[BeautifulSoup]:
    """
    Fetch a URL and return parsed BeautifulSoup, with retry logic.
    Returns None if all retries fail.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            
            # Check encoding and content
            logger.debug(
                "Content-Encoding: %s",
                resp.headers.get("Content-Encoding")
            )
            logger.debug("Apparent Encoding: %s", resp.apparent_encoding)
            logger.debug("Declared Encoding: %s", resp.encoding)
            logger.debug(
                "Content bytes: %d, text length: %d",
                len(resp.content),
                len(resp.text)
            )

            # requests should automatically decode gzip/br
            # Use resp.content for encoding detection
            soup = BeautifulSoup(resp.content, "lxml")
            return soup
        except requests.RequestException as exc:
            wait = RETRY_BACKOFF ** attempt
            logger.warning(
                "Attempt %d/%d failed for %s: %s — retrying in %ds",
                attempt,
                MAX_RETRIES,
                url,
                exc,
                wait,
            )
            time.sleep(wait)
    logger.error("All %d attempts failed for %s", MAX_RETRIES, url)
    return None


def _text(tag: Optional[Tag]) -> str:
    """Safely extract stripped text from a BS4 tag."""
    if tag is None:
        return ""
    if hasattr(tag, "get_text"):
        return tag.get_text(strip=True)
    return str(tag).strip()


def _inner_html(tag: Optional[Tag]) -> str:
    """Get the inner HTML of a tag (preserving child tags for structure)."""
    if not tag:
        return ""
    return "".join(str(child) for child in tag.children).strip()


def _clean_text(text: str) -> str:
    """Collapse whitespace in a string."""
    return re.sub(r"\s+", " ", text).strip()


def _bulletize(text: str) -> str:
    """Convert plain-text lines into bullet format: '• Line 1\\n• Line 2'."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    result = []
    for line in lines:
        # Strip existing bullets/numbering
        cleaned = re.sub(r"^[\d]+[.)]\s*", "", line)
        cleaned = re.sub(r"^[•\-\*]\s*", "", cleaned)
        if cleaned:
            result.append(f"• {cleaned}")
    return "\n".join(result) if result else text


def parse_salary(
    salary_text: str,
) -> Tuple[Optional[int], Optional[int], Optional[str], bool]:
    """Parse salary strings like 'KSh 60,000 - 75,000' or 'Confidential'."""
    if not salary_text or "confidential" in salary_text.lower():
        return None, None, None, False

    # Normalize currency to ISO codes
    currency = "KES"  # default for BrighterMonday Kenya
    upper = salary_text.upper()
    if "$" in salary_text or "USD" in upper:
        currency = "USD"
    elif "£" in salary_text or "GBP" in upper:
        currency = "GBP"
    elif "€" in salary_text or "EUR" in upper:
        currency = "EUR"

    less_than = re.search(r"[Ll]ess\s+than\s+([\d,]+)", salary_text)
    if less_than:
        max_val = int(float(less_than.group(1).replace(",", "")))
        return None, max_val, currency, True

    range_match = re.findall(r"([\d,]+(?:\.\d+)?)", salary_text)
    if len(range_match) >= 2:
        min_val = int(float(range_match[0].replace(",", "")))
        max_val = int(float(range_match[1].replace(",", "")))
        return min_val, max_val, currency, True
    elif len(range_match) == 1:
        val = int(float(range_match[0].replace(",", "")))
        return val, val, currency, True

    return None, None, currency, bool(salary_text.strip())


def parse_experience_years(
    exp_text: str
) -> Tuple[Optional[int], Optional[int]]:
    """Parse experience length strings like '2 years', '5 years'."""
    if not exp_text:
        return None, None

    low = exp_text.lower()
    if "no experience" in low or "less than 1" in low:
        return 0, 0

    range_match = re.search(r"(\d+)\s*[–\-to]+\s*(\d+)", exp_text)
    if range_match:
        return int(range_match.group(1)), int(range_match.group(2))

    single = re.search(r"(\d+)\s*(?:year|yr)", exp_text, re.IGNORECASE)
    if single:
        val = int(single.group(1))
        return val, val

    return None, None


def parse_relative_date(date_text: str) -> Optional[str]:
    """Convert relative dates like 'Today' to ISO dates."""
    if not date_text:
        return None

    now = datetime.now()
    low = date_text.strip().lower()

    if low == "today":
        return now.strftime("%Y-%m-%d")
    if low == "yesterday":
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")

    days_match = re.search(r"(\d+)\s*day", low)
    if days_match:
        days = int(days_match.group(1))
        return (now - timedelta(days=days)).strftime("%Y-%m-%d")

    weeks_match = re.search(r"(\d+)\s*week", low)
    if weeks_match:
        weeks = int(weeks_match.group(1))
        return (now - timedelta(weeks=weeks)).strftime("%Y-%m-%d")

    months_match = re.search(r"(\d+)\s*month", low)
    if months_match:
        months = int(months_match.group(1))
        return (now - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    return date_text.strip()


def extract_emails(text: str) -> List[str]:
    """Extract email addresses from text."""
    return re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)


def extract_deadline(text: str) -> Optional[str]:
    """Try to find application deadline from the description text."""
    patterns = [
        r"[Dd]eadline[:\s]+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})",
        r"[Bb]efore\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})",
        r"[Cc]losing\s+[Dd]ate[:\s]+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})",
        r"[Aa]pply\s+by[:\s]+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            raw = m.group(1)
            clean = re.sub(r"(\d+)(?:st|nd|rd|th)", r"\1", raw)
            try:
                dt = datetime.strptime(clean, "%d %B %Y")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                return raw
    return None


def extract_skills_from_text(text: str) -> List[str]:
    """Basic keyword-based skill extraction."""
    skill_keywords = [
        "python",
        "java",
        "javascript",
        "react",
        "node.js",
        "django",
        "flask",
        "sql",
        "mysql",
        "postgresql",
        "mongodb",
        "excel",
        "word",
        "powerpoint",
        "communication",
        "leadership",
        "management",
        "accounting",
        "finance",
        "marketing",
        "sales",
        "customer service",
        "project management",
        "data analysis",
        "machine learning",
        "ai",
        "cloud",
        "aws",
        "azure",
        "docker",
        "kubernetes",
        "git",
        "agile",
        "scrum",
        "sap",
        "erp",
        "odoo",
        "hris",
        "payroll",
        "recruitment",
        "procurement",
        "logistics",
        "supply chain",
        "inventory",
        "budgeting",
        "forecasting",
        "digital marketing",
        "seo",
        "social media",
        "figma",
        "photoshop",
        "illustrator",
        "canva",
        "html",
        "css",
        "typescript",
        "meta ads",
        "google ads",
        "quickbooks",
        "ifrs",
    ]
    lower = text.lower()
    found = [s for s in skill_keywords if s in lower]
    return sorted(set(found))


class BrighterMondayScraper:
    """Scrapes job listings from BrighterMonday Kenya."""

    def __init__(self, max_pages: Optional[int] = DEFAULT_MAX_PAGES):
        self.max_pages = max_pages
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def _get_total_pages(self, soup: BeautifulSoup) -> int:
        """Extract the last page number from pagination links."""
        page_links = soup.find_all("a", href=re.compile(r"[?&]page=\d+"))
        max_page = 1
        for link in page_links:
            href = link.get("href", "")
            m = re.search(r"page=(\d+)", href)
            if m:
                max_page = max(max_page, int(m.group(1)))
        return max_page

    def _extract_job_cards(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Parse the listing page and return job card info dicts."""
        cards: List[Dict[str, Any]] = []

        card_divs = soup.find_all(
            "div", attrs={"data-cy": "listing-cards-components"}
        )
        if not card_divs:
            # Fallback: find by class pattern
            def has_card_classes(class_list):
                if not class_list:
                    return False
                if isinstance(class_list, str):
                    class_list = [class_list]
                return "col-span-1" in class_list

            card_divs = soup.find_all("div", class_=has_card_classes)

        for card_div in card_divs:
            card_info = self._parse_single_card(card_div)
            if card_info and card_info.get("url"):
                cards.append(card_info)

        logger.info("Found %d job cards on page", len(cards))
        return cards

    def _parse_single_card(self, card: Tag) -> Optional[Dict[str, Any]]:
        """Parse a single job card div and return quick info dict."""
        info: Dict[str, Any] = {}

        title_link = card.find("a", attrs={"data-cy": "listing-title-link"})
        if not title_link:
            title_link = card.find("a", href=re.compile(r"/listings/"))
        if not title_link:
            return None

        info["url"] = title_link.get("href", "")
        if not info["url"]:
            return None

        if not info["url"].startswith("http"):
            info["url"] = urljoin(BM_BASE_URL, info["url"])

        info["title"] = _text(title_link)
        info["slug"] = info["url"].rstrip("/").split("/")[-1]
        logger.debug("Parsed card: %s", info["title"][:40])

        company_p = card.find("p", class_=lambda c: c and "text-blue-700" in c)
        info["company"] = _clean_text(_text(company_p)) if company_p else ""

        tag_spans = card.find_all(
            "span",
            class_=lambda c: c and "bg-brand-secondary-100" in c,
        )
        tags = [_clean_text(_text(s)) for s in tag_spans if _text(s)]
        info["tags"] = tags

        category_ps = card.find_all(
            "p", class_=lambda c: c and "text-gray-500" in c
        )
        for cp in category_ps:
            text = _clean_text(_text(cp))
            if text and len(text) < 60 and text != info.get("company", ""):
                info["category"] = text
                break

        featured_span = card.find(
            string=re.compile(r"FEATURED", re.IGNORECASE)
        )
        info["is_featured"] = bool(featured_span)

        new_span = card.find(
            "span", class_=lambda c: c and "bg-green-100" in c
        )
        info["is_new"] = bool(new_span and "new" in _text(new_span).lower())

        card_text = card.get_text(" ", strip=True)
        date_match = re.search(
            r"(Today|Yesterday|\d+\s+days?\s+ago|\d+\s+weeks?\s+ago)",
            card_text,
            re.IGNORECASE,
        )
        info["posted_date_text"] = date_match.group(1) if date_match else None

        logo_img = card.find(
            "img", src=re.compile(r"(advertiser-img|dealer-images|roamcdn)")
        )
        if logo_img:
            logo_url = logo_img.get("src") or logo_img.get("data-src")
            info["company_logo_url"] = logo_url
        else:
            logo_img2 = card.find("img")
            if logo_img2:
                src = logo_img2.get("src", "")
                if "dashboard-default" not in src and src:
                    info["company_logo_url"] = src

        all_gray_ps = card.find_all(
            "p", class_=lambda c: c and "text-gray-500" in c
        )
        for gp in all_gray_ps:
            text = _clean_text(_text(gp))
            if len(text) > 60:
                info["card_summary"] = text
                break

        return info

    def _scrape_job_detail(
        self, url: str, card_info: Dict[str, Any]
    ) -> Optional[JobListing]:
        """Visit a single job detail page and extract full data."""
        soup = _fetch(url, self.session)
        if not soup:
            return None

        job = JobListing()
        job.source_platform = BM_SOURCE_PLATFORM
        job.source_url = url
        job.country = BM_COUNTRY
        job.application_url = url
        job.stamp_scraped_at()

        h1 = soup.find("h1")
        job.title = _text(h1) or card_info.get("title", "")

        h2_tags = soup.find_all("h2")
        if len(h2_tags) >= 1:
            first_h2 = h2_tags[0]
            company_link = first_h2.find("a")
            if company_link:
                job.company = _text(company_link)
                href = company_link.get("href", "")
                if "/company/" in href:
                    job.company_website = (
                        href if href.startswith("http") else urljoin(BM_BASE_URL, href)
                    )
            else:
                job.company = _text(first_h2)

        if not job.company:
            job.company = card_info.get("company", "")
        if not job.company or job.company.strip() == "":
            job.company = "Anonymous Employer"

        # Generate deterministic job_id AFTER title and company are set
        job.job_id = JobListing.generate_job_id(
            job.title, job.company, prefix=BM_JOB_ID_PREFIX
        )

        if len(h2_tags) >= 2:
            cat_h2 = h2_tags[1]
            cat_link = cat_h2.find("a")
            if cat_link:
                job.job_type = _text(cat_link)
            else:
                cat_text = _text(cat_h2)
                if cat_text and cat_text.lower() != "stay updated":
                    job.job_type = cat_text

        if not job.job_type:
            job.job_type = card_info.get("category", "")

        for img in soup.find_all("img"):
            src = img.get("src", "") or ""
            if any(kw in src for kw in ["advertiser-img", "dealer-images", "roamcdn"]):
                job.company_logo_url = src
                break
        if not job.company_logo_url:
            job.company_logo_url = card_info.get("company_logo_url")

        self._apply_card_tags(card_info, job)
        self._parse_detail_tags(soup, job)

        job.is_featured = card_info.get("is_featured", False)
        if not job.is_featured:
            page_top_text = ""
            h1_tag = soup.find("h1")
            if h1_tag:
                parent = h1_tag.find_parent("div")
                if parent:
                    page_top_text = parent.get_text(" ", strip=True)[:500]
            job.is_featured = bool(
                re.search(r"\bFeatured\b", page_top_text, re.IGNORECASE)
            )

        date_text = card_info.get("posted_date_text")
        if not date_text:
            all_text = soup.get_text(" ", strip=True)
            dm = re.search(
                r"(Today|Yesterday|\d+\s+days?\s+ago|\d+\s+weeks?\s+ago)",
                all_text[:2000],
                re.IGNORECASE,
            )
            date_text = dm.group(1) if dm else None
        job.posted_date = parse_relative_date(date_text)

        summary_h3 = soup.find(
            lambda t: t.name == "h3" and "job summary" in t.get_text(strip=True).lower()
        )
        if summary_h3:
            summary_container = summary_h3.find_parent("div")
            if summary_container:
                summary_p = summary_container.find(
                    "p", class_=lambda c: c and "text-gray-500" in c
                )
                if summary_p:
                    summary_text = _text(summary_p)
                    job.job_metadata = job.job_metadata or {}
                    job.job_metadata["summary"] = summary_text

                meta_div = summary_container.find(
                    "div",
                    class_=lambda c: c
                    and "flex" in c
                    and "gap" in " ".join(c)
                    if c
                    else False,
                )
                if meta_div:
                    meta_text = _text(meta_div)
                    self._parse_summary_meta_text(meta_text, job)

        desc_h3 = soup.find(
            lambda t: t.name == "h3"
            and "job description" in t.get_text(strip=True).lower()
        )
        if desc_h3:
            desc_container = desc_h3.find_parent("div")
            if desc_container:
                content_div = desc_container.find(
                    "div", class_=lambda c: c and "mt-4" in c and "text-gray-500" in c
                )
                if not content_div:
                    content_div = desc_container.find(
                        "div", class_=lambda c: c and "mt-4" in c
                    )
                if not content_div:
                    content_div = desc_container

                job.description = _inner_html(content_div)

                plain_text = content_div.get_text("\n", strip=True)
                self._parse_description_sections(content_div, plain_text, job)

                if plain_text:
                    emails = extract_emails(plain_text)
                    if emails:
                        job.application_email = emails[0]
                    deadline = extract_deadline(plain_text)
                    if deadline:
                        job.application_deadline = deadline

        all_text = soup.get_text(" ", strip=True)
        # extracted_skills left as None — backend generates these
        job.extracted_skills = None

        # Build job_metadata with scraped_data wrapper for the backend
        raw_scraped = {
            "slug": card_info.get("slug", url.rstrip("/").split("/")[-1]),
            "easy_apply": "easy apply" in all_text.lower(),
            "is_new": card_info.get("is_new", False),
            "card_tags": card_info.get("tags", []),
            "card_summary": card_info.get("card_summary", ""),
        }
        if job.job_metadata and job.job_metadata.get("summary"):
            raw_scraped["summary"] = job.job_metadata["summary"]
        if job.job_metadata and job.job_metadata.get("industry"):
            raw_scraped["industry"] = job.job_metadata["industry"]

        metadata: Dict[str, Any] = {"scraped_data": raw_scraped}

        min_qual = self._find_label_value(soup, "Min Qualification")
        if min_qual:
            metadata["minimum_qualification"] = min_qual

        exp_level = self._find_label_value(soup, "Experience Level")
        if exp_level:
            metadata["experience_level"] = exp_level

        exp_length = self._find_label_value(soup, "Experience Length")
        if exp_length:
            metadata["experience_length"] = exp_length

        if job.application_deadline:
            metadata["deadline"] = job.application_deadline

        job.job_metadata = metadata

        return job

    def _apply_card_tags(self, card_info: Dict[str, Any], job: JobListing) -> None:
        """Apply quick info from the card (location, employment type, salary)."""
        tags = card_info.get("tags", [])

        employment_types = {
            "full time",
            "part time",
            "contract",
            "temporary",
            "freelance",
            "internship & graduate",
            "volunteer",
        }

        for tag in tags:
            tag_lower = tag.lower().strip()

            if tag_lower in employment_types:
                job.employment_type = tag
                continue

            if re.search(r"KSh|KES|USD|\$|€", tag) or tag_lower == "confidential":
                s_min, s_max, s_cur, s_disc = parse_salary(tag)
                job.salary_min = s_min
                job.salary_max = s_max
                job.salary_currency = s_cur
                job.salary_disclosed = s_disc
                continue

            if not job.specific_location and len(tag) < 50:
                job.specific_location = tag
                if "remote" in tag_lower:
                    job.location_type = "remote"
                elif "hybrid" in tag_lower:
                    job.location_type = "hybrid"
                else:
                    job.location_type = "on-site"

    def _parse_detail_tags(self, soup: BeautifulSoup, job: JobListing) -> None:
        """Parse tags from detail page (location, employment type, salary)."""
        if not job.specific_location:
            loc_link = soup.find(
                "a",
                href=re.compile(r"/jobs/[a-z-]+(?:\?|$)"),
                string=re.compile(
                    r"Nairobi|Mombasa|Kisumu|Eldoret|Nakuru|Rest of Kenya|Remote",
                    re.IGNORECASE,
                ),
            )
            if loc_link:
                job.specific_location = _text(loc_link)
                if "remote" in job.specific_location.lower():
                    job.location_type = "remote"
                else:
                    job.location_type = "on-site"

        if not job.employment_type:
            emp_link = soup.find(
                "a",
                href=re.compile(
                    r"/(full-time|part-time|contract|internship-graduate"
                    r"|freelance|temporary)"
                ),
            )
            if emp_link:
                job.employment_type = _text(emp_link)

        if not job.salary_disclosed:
            salary_tags = soup.find_all(string=re.compile(r"KSh\s+[\d,]"))
            for st in salary_tags:
                parent = st.parent if hasattr(st, "parent") else None
                if parent:
                    salary_text = _text(parent)
                    s_min, s_max, s_cur, s_disc = parse_salary(salary_text)
                    if s_disc:
                        job.salary_min = s_min
                        job.salary_max = s_max
                        job.salary_currency = s_cur
                        job.salary_disclosed = s_disc
                        break

        industry_links = soup.find_all("a", href=re.compile(r"industry="))
        if industry_links:
            for il in industry_links:
                text = _text(il)
                if text:
                    job.job_metadata = job.job_metadata or {}
                    job.job_metadata["industry"] = text
                    break

    def _parse_summary_meta_text(self, text: str, job: JobListing) -> None:
        """Parse metadata string from summary section."""
        exp_match = re.search(
            r"Experience\s*Length[:\s]*(.+?)(?:Min|Experience\s*Level|$)", text
        )
        if exp_match:
            exp_text = exp_match.group(1).strip()
            y_min, y_max = parse_experience_years(exp_text)
            job.experience_years_min = y_min
            job.experience_years_max = y_max

        if job.experience_years_min is None:
            exp_match2 = re.search(r"(\d+)\s*years?", text)
            if exp_match2:
                val = int(exp_match2.group(1))
                job.experience_years_min = val
                job.experience_years_max = val

        qual_match = re.search(r"Min\s*Qualification[:\s]*(\w+)", text)
        if qual_match:
            job.job_metadata = job.job_metadata or {}
            job.job_metadata["min_qualification"] = qual_match.group(1)

        level_match = re.search(
            r"Experience\s*Level[:\s]*(.+?)(?:Experience\s*Length|$)", text
        )
        if level_match:
            job.job_metadata = job.job_metadata or {}
            job.job_metadata["experience_level"] = level_match.group(1).strip()

    def _parse_description_sections(
        self, container: Tag, full_text: str, job: JobListing
    ) -> None:
        """Parse sub-sections from description (responsibilities, requirements)."""
        sections = self._split_into_sections_by_text(full_text)

        for heading, content in sections.items():
            heading_lower = heading.lower()

            if any(
                kw in heading_lower
                for kw in [
                    "responsibilit",
                    "key responsibilit",
                    "duties",
                    "role purpose",
                    "job purpose",
                    "scope of work",
                ]
            ):
                job.responsibilities = (
                    (job.responsibilities or "") + content.strip() + "\n"
                )

            elif any(
                kw in heading_lower
                for kw in [
                    "requirement",
                    "qualification",
                    "education",
                    "skills",
                    "competenc",
                    "who we",
                ]
            ):
                job.requirements = (job.requirements or "") + content.strip() + "\n"

            elif any(
                kw in heading_lower
                for kw in [
                    "benefit",
                    "offer",
                    "what we offer",
                    "why join",
                    "compensation",
                    "perks",
                    "we provide",
                ]
            ):
                job.benefits = (job.benefits or "") + content.strip() + "\n"

        if job.responsibilities:
            job.responsibilities = _bulletize(job.responsibilities.strip())
        if job.requirements:
            job.requirements = _bulletize(job.requirements.strip())
        if job.benefits:
            job.benefits = _bulletize(job.benefits.strip())

    def _split_into_sections_by_text(self, text: str) -> Dict[str, str]:
        """Split description text into sections based on heading patterns."""
        heading_patterns = [
            r"(?:Key\s+)?Responsibilities",
            r"(?:Key\s+)?Duties",
            r"Requirements?\s*(?:&\s*Experience)?",
            r"Qualifications?\s*(?:&\s*Experience)?",
            r"Education\s*(?:&\s*(?:Experience|Qualifications?))?",
            r"(?:Required\s+)?Skills?\s*(?:&\s*Competencies)?",
            r"What\s+We\s+Offer",
            r"Benefits?",
            r"Why\s+Join\s+Us",
            r"Compensation",
            r"Role\s+Purpose",
            r"Job\s+Purpose",
            r"About\s+(?:the\s+)?(?:Company|Role|Position)",
            r"Scope\s+of\s+Work",
            r"How\s+to\s+Apply",
            r"Application\s+(?:Process|Deadline|Instructions)",
        ]

        combined_pattern = "|".join(f"({p})" for p in heading_patterns)
        full_pattern = (
            r"(?:^|\n)\s*(?:\d+\.?\s*)?("
            + combined_pattern
            + r")\s*[:.]?\s*(?:\n|$)"
        )

        sections: Dict[str, str] = {}
        matches = list(re.finditer(full_pattern, text, re.IGNORECASE | re.MULTILINE))

        for i, match in enumerate(matches):
            heading = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if content:
                sections[heading] = content

        return sections

    def _find_label_value(self, soup: BeautifulSoup, label: str) -> Optional[str]:
        """Find the value next to a label like 'Min Qualification:'."""
        label_tags = soup.find_all(string=re.compile(re.escape(label), re.IGNORECASE))
        for label_tag in label_tags:
            parent = label_tag.parent if hasattr(label_tag, "parent") else None
            if parent:
                next_el = parent.find_next_sibling()
                if next_el:
                    val = _text(next_el)
                    if val:
                        return val
                full = _text(parent)
                parts = re.split(re.escape(label) + r"[:\s]*", full, maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    return parts[1].strip()
        return None

    def run(self) -> List[JobListing]:
        """Main entry point. Scrapes listing pages, then each job detail page."""
        logger.info("=" * 60)
        logger.info("BrighterMonday Scraper — Starting")
        logger.info("=" * 60)

        logger.info("Fetching first listing page: %s", BM_JOBS_URL)
        first_page = _fetch(BM_JOBS_URL, self.session)
        if not first_page:
            logger.error("Failed to fetch the first listing page. Aborting.")
            return []

        # DEBUG: Save HTML to file for inspection
        with open("debug_fetched_page.html", "w", encoding="utf-8") as f:
            f.write(str(first_page)[:100000])
        logger.debug("Saved fetched HTML to debug_fetched_page.html")

        total_pages = self._get_total_pages(first_page)
        pages_to_scrape = (
            total_pages if self.max_pages is None else min(self.max_pages, total_pages)
        )
        logger.info(
            "Total pages available: %d | Pages to scrape: %d",
            total_pages,
            pages_to_scrape,
        )

        all_cards: List[Dict[str, Any]] = []

        cards = self._extract_job_cards(first_page)
        all_cards.extend(cards)

        for page_num in range(2, pages_to_scrape + 1):
            _polite_sleep()
            page_url = f"{BM_JOBS_URL}?page={page_num}"
            logger.info(
                "Fetching listing page %d/%d: %s", page_num, pages_to_scrape, page_url
            )
            page_soup = _fetch(page_url, self.session)
            if page_soup:
                cards = self._extract_job_cards(page_soup)
                all_cards.extend(cards)
            else:
                logger.warning("Skipping page %d (fetch failed)", page_num)

        seen = set()
        unique_cards = []
        for card in all_cards:
            if card["url"] not in seen:
                seen.add(card["url"])
                unique_cards.append(card)
        all_cards = unique_cards

        logger.info("Total unique job cards collected: %d", len(all_cards))

        jobs: List[JobListing] = []
        for idx, card in enumerate(all_cards, 1):
            _polite_sleep()
            logger.info(
                "Scraping job %d/%d: %s",
                idx,
                len(all_cards),
                card.get("title", card["url"])[:50],
            )
            try:
                job = self._scrape_job_detail(card["url"], card)
                if job:
                    jobs.append(job)
                    logger.info(
                        "  ✓ %s | %s | %s | %s",
                        job.job_id,
                        job.title[:40],
                        job.company[:25],
                        job.specific_location or "N/A",
                    )
                else:
                    logger.warning("  ✗ Failed to scrape: %s", card["url"])
            except Exception as exc:
                logger.error(
                    "  ✗ Error scraping %s: %s", card["url"], exc, exc_info=True
                )

        logger.info("=" * 60)
        logger.info("Scraping complete! Total jobs scraped: %d", len(jobs))
        logger.info("=" * 60)

        return jobs


def main():
    parser = argparse.ArgumentParser(
        description="Scrape jobs from BrighterMonday Kenya",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python brightermonday_scraper.py
  python brightermonday_scraper.py --pages 10
  python brightermonday_scraper.py --pages all
  python brightermonday_scraper.py --pages 2 --output my_jobs.json
  python brightermonday_scraper.py --pages 2 --db        # scrape + push to DB
  python brightermonday_scraper.py --pages 2 --db --output my_jobs.json
        """,
    )
    parser.add_argument(
        "--pages",
        default=str(DEFAULT_MAX_PAGES),
        help=f"Number of pages to scrape, or 'all' (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output JSON file path (default: auto-generated timestamped file)",
    )
    parser.add_argument(
        "--db",
        action="store_true",
        default=False,
        help="Push scraped jobs to the production database",
    )
    args = parser.parse_args()

    if args.pages.lower() == "all":
        max_pages = None
    else:
        try:
            max_pages = int(args.pages)
        except ValueError:
            logger.error("Invalid --pages value: %s. Use a number or 'all'.", args.pages)
            sys.exit(1)

    scraper = BrighterMondayScraper(max_pages=max_pages)
    jobs = scraper.run()

    if not jobs:
        logger.warning("No jobs were scraped.")
        sys.exit(0)

    output_path = args.output or get_output_filename("brightermonday")
    output_json = jobs_to_json(jobs)

    os.makedirs(
        os.path.dirname(output_path) if os.path.dirname(output_path) else ".",
        exist_ok=True,
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_json)

    logger.info("Results saved to: %s", output_path)

    print("\n" + "=" * 60)
    print("  SCRAPE SUMMARY")
    print("=" * 60)
    print(f"  Total jobs scraped : {len(jobs)}")
    print(f"  Output file        : {output_path}")
    print(f"  Source platform    : {BM_SOURCE_PLATFORM}")
    print(f"  Country            : {BM_COUNTRY}")
    featured = sum(1 for j in jobs if j.is_featured)
    with_salary = sum(1 for j in jobs if j.salary_disclosed)
    with_email = sum(1 for j in jobs if j.application_email)
    with_deadline = sum(1 for j in jobs if j.application_deadline)
    with_skills = sum(1 for j in jobs if j.extracted_skills)
    with_responsibilities = sum(1 for j in jobs if j.responsibilities)
    with_requirements = sum(1 for j in jobs if j.requirements)
    with_benefits = sum(1 for j in jobs if j.benefits)
    print(f"  Featured jobs      : {featured}")
    print(f"  With salary shown  : {with_salary}")
    print(f"  With email found   : {with_email}")
    print(f"  With deadline      : {with_deadline}")
    print(f"  With skills found  : {with_skills}")
    print(f"  With responsibilities: {with_responsibilities}")
    print(f"  With requirements  : {with_requirements}")
    print(f"  With benefits      : {with_benefits}")
    print("=" * 60)

    # ── Push to database if --db flag is set ──
    if args.db:
        import asyncio
        from db_storage import push_jobs_to_db, test_connection

        print("\n" + "=" * 60)
        print("  DATABASE PUSH")
        print("=" * 60)

        async def _push():
            ok = await test_connection()
            if not ok:
                logger.error("Cannot connect to database. Skipping DB push.")
                return
            result = await push_jobs_to_db(jobs)
            print(f"  Saved to DB       : {result['saved']}")
            print(f"  Skipped (dupes)   : {result['skipped']}")
            print(f"  Errors            : {result['errors']}")
            print("=" * 60)

        asyncio.run(_push())


if __name__ == "__main__":
    main()
