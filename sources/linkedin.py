import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

from .base import JobPosting, enrich, stable_id

logger = logging.getLogger(__name__)

GUEST_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

# Fallback only — main.py passes config.SEARCH_QUERIES for the active profile.
QUERIES = [
    "Customer Success Manager",
    "Customer Service Manager",
    "Client Relationship Manager",
    "Customer Experience Manager",
    "Account Manager",
]

LOCATIONS = [
    "Germany",
    "Netherlands",
    "Ireland",
    "United Kingdom",
    "Canada",
    "Australia",
    "Singapore",
    "Sweden",
    "Switzerland",
    "Japan",
    "Denmark",
    "Norway",
    "Finland",
    "Austria",
    "France",
    "Spain",
    "Poland",
    "New Zealand",
    "United Arab Emirates",
    "South Korea",
    "Portugal",
    "Belgium",
    "Czech Republic",
    "Italy",
    "United States",
    "Remote",
    "Worldwide",
]


def _parse_job_cards(html: str) -> list[dict]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed — skipping LinkedIn parsing")
        return []

    soup = BeautifulSoup(html, "lxml")
    results = []

    for card in soup.select("li"):
        title_el = card.select_one(".base-search-card__title")
        company_el = card.select_one(".base-search-card__subtitle a")
        location_el = card.select_one(".job-search-card__location")
        link_el = card.select_one("a.base-card__full-link")
        date_el = card.select_one("time")

        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        company = company_el.get_text(strip=True) if company_el else ""
        location = location_el.get_text(strip=True) if location_el else ""
        url = link_el.get("href", "").split("?")[0] if link_el else ""
        date_posted = date_el.get("datetime", "") if date_el else ""

        results.append({
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "date_posted": date_posted[:10] if date_posted else "",
        })

    return results


def _fetch_job_description(url: str) -> str:
    for attempt in range(2):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
                timeout=15,
            )
            if resp.status_code == 429:
                if attempt == 0:
                    time.sleep(5)
                    continue
                logger.warning("LinkedIn desc fetch 429 for %s after retry", url)
                return ""
            if resp.status_code != 200:
                return ""
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")
            desc_el = soup.select_one(".show-more-less-html__markup")
            if desc_el:
                return re.sub(r"<[^>]+>", " ", str(desc_el))[:3000]
        except Exception:
            pass
        break
    return ""


_SOURCE_TIME_BUDGET = 20 * 60
_MAX_CONSECUTIVE_429 = 3


def fetch_jobs(max_days_old: int = 7, queries: list[str] | None = None, locations: list[str] | None = None, seen_ids: set[str] | None = None) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)
    seen_urls: set[str] = set()
    use_queries = queries if queries is not None else QUERIES
    use_locations = locations if locations is not None else LOCATIONS
    start_time = time.time()
    consecutive_429 = 0

    try:
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        logger.warning("beautifulsoup4 not installed — skipping LinkedIn source")
        return []

    for query in use_queries:
        if time.time() - start_time > _SOURCE_TIME_BUDGET:
            logger.warning("LinkedIn: time budget exceeded (%ds), returning %d jobs", int(time.time() - start_time), len(jobs))
            break

        for location in use_locations:
            if time.time() - start_time > _SOURCE_TIME_BUDGET:
                break

            for start in range(0, 50, 25):
                try:
                    resp = requests.get(
                        GUEST_API,
                        params={
                            "keywords": query,
                            "location": location,
                            "start": start,
                        },
                        headers={
                            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                        },
                        timeout=20,
                    )
                    if resp.status_code == 429:
                        consecutive_429 += 1
                        backoff = 60 * (2 ** (consecutive_429 - 1))
                        logger.warning("LinkedIn rate limited (%d consecutive), backing off %ds", consecutive_429, backoff)
                        if consecutive_429 >= _MAX_CONSECUTIVE_429:
                            logger.warning("LinkedIn: %d consecutive 429s, bailing out with %d jobs", consecutive_429, len(jobs))
                            return jobs
                        time.sleep(backoff)
                        break
                    if resp.status_code != 200:
                        continue
                    consecutive_429 = 0
                except Exception:
                    logger.exception("LinkedIn API error for query=%s location=%s", query, location)
                    continue

                cards = _parse_job_cards(resp.text)
                if not cards:
                    break

                new_urls = []
                card_map: dict[str, dict] = {}
                skipped_seen = 0
                for card in cards:
                    url = card["url"]
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    if seen_ids and stable_id("linkedin", url) in seen_ids:
                        skipped_seen += 1
                        continue
                    date_str = card["date_posted"]
                    try:
                        post_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        post_date = datetime.now(timezone.utc)
                    if post_date < cutoff:
                        continue
                    new_urls.append(url)
                    card_map[url] = card

                if not new_urls and start == 0:
                    break

                descriptions: dict[str, str] = {}
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {}
                    for url in new_urls:
                        futures[executor.submit(_fetch_job_description, url)] = url
                        time.sleep(0.3)
                    for future in as_completed(futures):
                        url = futures[future]
                        try:
                            descriptions[url] = future.result()
                        except Exception:
                            descriptions[url] = ""

                for url in new_urls:
                    card = card_map[url]
                    job = JobPosting(
                        id=stable_id("linkedin", url),
                        source="linkedin",
                        title=card["title"],
                        company=card["company"],
                        location=card["location"],
                        url=url,
                        description=descriptions.get(url, ""),
                        date_posted=card["date_posted"],
                        tags=[],
                    )
                    jobs.append(enrich(job))

            time.sleep(1)

    elapsed = int(time.time() - start_time)
    total_seen = len(seen_urls) - len(jobs)
    logger.info("LinkedIn: fetched %d new jobs in %ds (skipped %d already-seen)", len(jobs), elapsed, total_seen)
    return jobs
