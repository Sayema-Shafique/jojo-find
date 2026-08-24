import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from .base import JobPosting, enrich

logger = logging.getLogger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"

CATEGORIES = ["qa", "software-dev", "devops-sysadmin", "product", "data"]

SEARCHES = ["QA", "SDET", "Test", "Quality", "Automation", "Verification"]


def fetch_jobs(max_days_old: int = 7) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)
    seen_ids: set[str] = set()

    search_combos = []
    for search in SEARCHES:
        search_combos.append({"search": search})
    for category in CATEGORIES:
        search_combos.append({"category": category, "search": "QA"})
        search_combos.append({"category": category, "search": "test"})

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

        for item in data.get("jobs", []):
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
