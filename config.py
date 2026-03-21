"""
Shared configuration for all job scrapers.
Used by BrighterMonday scraper, Upwork scraper, and future scrapers.
"""

import os
from datetime import datetime

# ──────────────────────────────────────────────
# BrighterMonday Settings
# ──────────────────────────────────────────────
BM_BASE_URL = "https://www.brightermonday.co.ke"
BM_JOBS_URL = f"{BM_BASE_URL}/jobs"
BM_LISTING_PREFIX = f"{BM_BASE_URL}/listings/"

# ──────────────────────────────────────────────
# Request Settings
# ──────────────────────────────────────────────
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Rate limiting — seconds between requests (be polite to the server)
REQUEST_DELAY_MIN = 1.5
REQUEST_DELAY_MAX = 3.0

# Retry settings
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # exponential backoff multiplier

# Request timeout in seconds
REQUEST_TIMEOUT = 30

# ──────────────────────────────────────────────
# Scraper Defaults
# ──────────────────────────────────────────────
# Max pages to scrape (set to None for all pages)
DEFAULT_MAX_PAGES = 5

# Country for BrighterMonday Kenya
BM_COUNTRY = "Kenya"

# Source platform name
BM_SOURCE_PLATFORM = "brightermonday"

# Job ID prefix
BM_JOB_ID_PREFIX = "bm"

# ──────────────────────────────────────────────
# Output Settings
# ──────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# Timestamp format for filenames
def get_output_filename(scraper_name: str, ext: str = "json") -> str:
    """Generate a timestamped output filename."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(OUTPUT_DIR, f"{scraper_name}_{ts}.{ext}")


# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
