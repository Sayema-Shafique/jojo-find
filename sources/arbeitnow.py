import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from .base import JobPosting, enrich, stable_id

logger = logging.getLogger(__name__)

API_URL = "https://www.arbeitnow.com/api/job-board-api"


def fetch_jobs(max_days_old: int = 3) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)
    page = 1
    max_pages = 10

    while page <= max_pages:
        try:
            resp = requests.get(API_URL, params={"page": page}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Arbeitnow API error on page %d", page)
            break

        postings = data.get("data", [])
        if not postings:
            break

        for item in postings:
            created = item.get("created_at", "")
            try:
                post_date = datetime.fromtimestamp(int(created), tz=timezone.utc)
            except (ValueError, TypeError):
                post_date = datetime.now(timezone.utc)

            if post_date < cutoff:
                continue

            remote = item.get("remote", False)

            job = JobPosting(
                id=f"arbeitnow_{item.get('slug', '')}" if item.get('slug') else stable_id("arbeitnow", item.get('title', '')),
                source="arbeitnow",
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("location", ""),
                url=item.get("url", ""),
                description=item.get("description", "")[:2000],
                date_posted=post_date.strftime("%Y-%m-%d"),
                tags=item.get("tags", []),
                remote_type="remote" if remote else "",
            )
            jobs.append(enrich(job))

        links = data.get("links", {})
        if not links.get("next"):
            break
        page += 1
        time.sleep(1)

    logger.info("Arbeitnow: fetched %d jobs", len(jobs))
    return jobs
