import logging
from datetime import datetime, timedelta, timezone

from .base import JobPosting, enrich, get_with_retry, stable_id

logger = logging.getLogger(__name__)

API_URL = "https://landing.jobs/api/v1/offers"

SEARCH_PARAMS = {
    "tags[]": ["qa", "testing", "sdet", "quality", "test-automation"],
}


def fetch_jobs(max_days_old: int = 30) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)

    try:
        resp = get_with_retry(
            API_URL,
            params={"page": 1, "per_page": 50},
            headers={"Accept": "application/json", "User-Agent": "JobFinder/1.0"},
        )
        data = resp.json()
    except Exception:
        logger.exception("Landing.jobs API error")
        return jobs

    offers = data if isinstance(data, list) else data.get("offers", data.get("data", []))

    for item in offers:
        date_str = item.get("published_at", item.get("created_at", ""))
        try:
            post_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            post_date = datetime.now(timezone.utc)

        if post_date < cutoff:
            continue

        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        location = item.get("city", "")
        country = item.get("country", "")
        if country:
            location = f"{location}, {country}" if location else country

        job = JobPosting(
            id=f"landingjobs_{item.get('id', '')}" if item.get('id') else stable_id("landingjobs", item.get('title', '')),
            source="landingjobs",
            title=item.get("title", ""),
            company=item.get("company_name", item.get("company", {}).get("name", "")),
            location=location,
            url=item.get("url", item.get("link", "")),
            description=item.get("description", item.get("body", ""))[:3000],
            date_posted=post_date.strftime("%Y-%m-%d"),
            tags=tags,
            salary_min=float(item.get("salary_from", 0) or 0),
            salary_max=float(item.get("salary_to", 0) or 0),
            salary_currency=item.get("currency", ""),
        )
        jobs.append(enrich(job))

    logger.info("Landing.jobs: fetched %d jobs", len(jobs))
    return jobs
