import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from .base import JobPosting, enrich

logger = logging.getLogger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"

# Remotive category slugs. Unverified slugs simply return no jobs and are
# reported by the zero-yield warning below rather than failing the source.
CATEGORIES = ["customer-support", "sales-marketing", "business", "all-others"]

SEARCHES = [
    "customer success",
    "customer service",
    "account manager",
    "client relationship",
    "customer experience",
]


def fetch_jobs(max_days_old: int = 7, queries: list[str] | None = None,
               categories: list[str] | None = None) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)
    seen_ids: set[str] = set()

    use_searches = queries if queries is not None else SEARCHES
    use_categories = categories if categories is not None else CATEGORIES

    search_combos = []
    for search in use_searches:
        search_combos.append({"search": search})
    # Whole-category sweeps: these boards are small enough that an unfiltered
    # category pull beats guessing search terms.
    for category in use_categories:
        search_combos.append({"category": category})

    for i, params in enumerate(search_combos):
        if i > 0:
            time.sleep(0.5)
        try:
            resp = requests.get(
                API_URL,
                params={**params, "limit": 50},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Remotive API error for params=%s", params)
            continue

        found = data.get("jobs", [])
        if not found:
            logger.warning("Remotive: no jobs for params=%s (check slug)", params)

        for item in found:
            job_id = str(item.get("id", ""))
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            pub_date = item.get("publication_date", "")
            try:
                post_date = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                if post_date.tzinfo is None:
                    post_date = post_date.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                try:
                    post_date = datetime.strptime(pub_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    post_date = datetime.now(timezone.utc)

            if post_date < cutoff:
                continue

            candidate_location = item.get("candidate_required_location", "")
            location = candidate_location or "Remote"

            sal_min = float(item.get("salary_min") or 0)
            sal_max = float(item.get("salary_max") or 0)
            salary = item.get("salary", "") or ""

            tags = item.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            job_type_raw = (item.get("job_type") or "").lower()
            job_type = ""
            if "full" in job_type_raw:
                job_type = "full-time"
            elif "contract" in job_type_raw:
                job_type = "contract"
            elif "part" in job_type_raw:
                job_type = "part-time"

            job = JobPosting(
                id=f"remotive_{job_id}",
                source="remotive",
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=location,
                url=item.get("url", ""),
                description=item.get("description", "")[:3000],
                date_posted=post_date.strftime("%Y-%m-%d"),
                tags=tags,
                salary=salary,
                salary_min=sal_min,
                salary_max=sal_max,
                job_type=job_type,
                remote_type="remote",
            )
            jobs.append(enrich(job))

    logger.info("Remotive: fetched %d jobs", len(jobs))
    return jobs
