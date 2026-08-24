import logging
import re
import time
from datetime import datetime, timedelta, timezone

from .base import JobPosting, enrich, stable_id, get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://remote.co/remote-jobs/qa"


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _fetch_description(url: str) -> str:
    if not url:
        return ""
    try:
        from bs4 import BeautifulSoup
        resp = get_with_retry(
            url,
            retries=2,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )
        soup = BeautifulSoup(resp.text, "lxml")
        desc_el = soup.select_one(".job_description, .job-description, .entry-content, article")
        if desc_el:
            return _strip_html(str(desc_el))[:3000]
    except Exception:
        logger.debug("Remote.co: failed to fetch description from %s", url)
    return ""


def fetch_jobs(max_days_old: int = 30) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)

    try:
        resp = get_with_retry(
            BASE_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            },
        )
        html = resp.text
    except Exception:
        logger.exception("Remote.co scrape error")
        return jobs

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed — skipping Remote.co")
        return jobs

    soup = BeautifulSoup(html, "lxml")

    for card in soup.select(".card, .job_listing, article"):
        title_el = card.select_one("h2, h3, .position, .job_listing-title a, a[href*='remote-jobs']")
        company_el = card.select_one(".company, .company_name, .job_listing-company")
        link_el = card.select_one("a[href*='remote-jobs']")
        date_el = card.select_one("time, .date, .job_listing-date")

        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        company = company_el.get_text(strip=True) if company_el else ""
        url = ""
        if link_el:
            href = link_el.get("href", "")
            if href.startswith("/"):
                url = f"https://remote.co{href}"
            elif href.startswith("http"):
                url = href

        date_posted = ""
        if date_el:
            dt = date_el.get("datetime", "")
            if dt:
                date_posted = dt[:10]
            else:
                date_posted = ""

        if date_posted:
            try:
                post_date = datetime.strptime(date_posted, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if post_date < cutoff:
                    continue
            except ValueError:
                pass

        description = _fetch_description(url)
        if url:
            time.sleep(0.5)

        job = JobPosting(
            id=stable_id("remoteco", url or title),
            source="remoteco",
            title=title,
            company=company,
            location="Remote",
            url=url,
            description=description,
            date_posted=date_posted,
            tags=[],
            remote_type="remote",
        )
        jobs.append(enrich(job))

    logger.info("Remote.co: fetched %d jobs", len(jobs))
    return jobs
