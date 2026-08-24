import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from .base import JobPosting, enrich

logger = logging.getLogger(__name__)

SEARCH_URL = "https://himalayas.app/jobs/api/search"

# Fallback only — main.py passes config.SEARCH_QUERIES.
SEARCHES = [
    "customer success manager",
    "customer service manager",
    "account manager",
    "client relationship manager",
    "customer experience manager",
]


def fetch_jobs(queries: list[str] | None = None, max_days_old: int = 7) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    seen_ids: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)

    for search in (queries if queries is not None else SEARCHES):
        page = 1
        max_pages = 3

        while page <= max_pages:
            try:
                resp = requests.get(
                    SEARCH_URL,
                    params={"q": search, "page": page, "sort": "recent"},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("Himalayas API error for q=%s page=%d", search, page)
                break

            items = data.get("jobs", [])
            if not items:
                break

            too_old = 0
            for item in items:
                job_id = str(item.get("id", ""))
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                posted = item.get("pubDate", "") or item.get("updated_at", "")
                try:
                    if isinstance(posted, (int, float)):
                        post_date = datetime.fromtimestamp(posted, tz=timezone.utc)
                    else:
                        post_date = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
                except (ValueError, TypeError, OSError):
                    post_date = datetime.now(timezone.utc)

                if post_date < cutoff:
                    too_old += 1
                    continue

                categories = item.get("categories", [])
                if isinstance(categories, list):
                    tags = [c.get("name", "") if isinstance(c, dict) else str(c) for c in categories]
                else:
                    tags = []

                sal_min = float(item.get("minSalary") or 0)
                sal_max = float(item.get("maxSalary") or 0)
                sal_currency = str(item.get("salaryCurrency") or "")

                job = JobPosting(
                    id=f"himalayas_{job_id}",
                    source="himalayas",
                    title=item.get("title", ""),
                    company=item.get("companyName", ""),
                    location=item.get("location", ""),
                    url=item.get("applicationLink", "") or item.get("url", ""),
                    description=item.get("description", "")[:3000],
                    date_posted=post_date.strftime("%Y-%m-%d"),
                    tags=tags,
                    salary_min=sal_min,
                    salary_max=sal_max,
                    salary_currency=sal_currency,
                )
                jobs.append(enrich(job))

            if too_old > len(items) // 2:
                break

            page += 1
            time.sleep(0.5)

    logger.info("Himalayas: fetched %d jobs from %d unique results", len(jobs), len(seen_ids))
    return jobs
