import logging
import re
from datetime import datetime, timedelta, timezone

from .base import JobPosting, enrich, get_with_retry

logger = logging.getLogger(__name__)

API_URL = "https://wellfound.com/api/v2/jobs"

SEARCH_ROLES = ["qa-engineer", "sdet", "test-engineer", "quality-engineer"]


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def fetch_jobs(max_days_old: int = 30) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)
    seen_ids: set[str] = set()

    for role in SEARCH_ROLES:
        try:
            resp = get_with_retry(
                API_URL,
                params={"role": role, "page": 1},
                headers={
                    "Accept": "application/json",
                    "User-Agent": "JobFinder/1.0",
                },
            )
            data = resp.json()
        except Exception:
            logger.exception("Wellfound API error for role=%s", role)
            continue

        listings = data if isinstance(data, list) else data.get("jobs", data.get("data", []))

        for item in listings:
            item_id = str(item.get("id", ""))
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            date_str = item.get("published_at", item.get("created_at", ""))
            try:
                post_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                post_date = datetime.now(timezone.utc)

            if post_date < cutoff:
                continue

            startup = item.get("startup", item.get("company", {}))
            if isinstance(startup, dict):
                company = startup.get("name", "")
            else:
                company = str(startup) if startup else ""

            tags = item.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            location = item.get("location", "") or ""
            if item.get("remote", False) and "remote" not in location.lower():
                location = f"{location}, Remote" if location else "Remote"

            sal_min = float(item.get("salary_min", 0) or 0)
            sal_max = float(item.get("salary_max", 0) or 0)

            description = item.get("description", item.get("body", ""))
            if description:
                description = _strip_html(description)[:3000]
            else:
                description = ""

            job = JobPosting(
                id=f"wellfound_{item_id}",
                source="wellfound",
                title=item.get("title", item.get("role", "")),
                company=company,
                location=location,
                url=item.get("url", item.get("link", "")),
                description=description,
                date_posted=post_date.strftime("%Y-%m-%d"),
                tags=tags,
                salary_min=sal_min,
                salary_max=sal_max,
                salary_currency=item.get("currency", ""),
            )
            jobs.append(enrich(job))

    logger.info("Wellfound: fetched %d jobs", len(jobs))
    return jobs
