import logging
from datetime import datetime, timedelta, timezone

import requests

from .base import JobPosting, enrich, stable_id

logger = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"


def fetch_jobs(max_days_old: int = 3) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)

    try:
        resp = requests.get(
            API_URL,
            headers={"User-Agent": "JobFinder/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("RemoteOK API error")
        return jobs

    for item in data[1:]:
        date_str = item.get("date", "")
        try:
            post_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            post_date = datetime.now(timezone.utc)

        if post_date < cutoff:
            continue

        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        sal_min = float(item.get("salary_min") or 0)
        sal_max = float(item.get("salary_max") or 0)

        job = JobPosting(
            id=f"remoteok_{item.get('id', '')}" if item.get('id') else stable_id("remoteok", item.get('position', '')),
            source="remoteok",
            title=item.get("position", ""),
            company=item.get("company", ""),
            location=item.get("location", "") or "Remote",
            url=item.get("url", ""),
            description=item.get("description", "")[:2000],
            date_posted=post_date.strftime("%Y-%m-%d"),
            tags=tags,
            salary_min=sal_min,
            salary_max=sal_max,
            remote_type="remote",
        )
        jobs.append(enrich(job))

    logger.info("RemoteOK: fetched %d jobs", len(jobs))
    return jobs
