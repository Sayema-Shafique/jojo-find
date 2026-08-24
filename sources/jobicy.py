import logging
from datetime import datetime, timedelta, timezone

import requests

from .base import JobPosting, enrich

logger = logging.getLogger(__name__)

API_URL = "https://jobicy.com/api/v2/remote-jobs"

# Jobicy industry tags. "management" is kept — it was the best-yielding tag in
# the audit (30.7%). Unknown tags return nothing and are warned on below.
JOBICY_TAGS = ["supporting", "sales", "marketing", "business", "management"]


def fetch_jobs(max_days_old: int = 3, tags: list[str] | None = None) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)
    seen_ids: set[str] = set()

    for tag in (tags if tags is not None else JOBICY_TAGS):
        try:
            resp = requests.get(
                API_URL,
                params={"count": 50, "tag": tag},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Jobicy API error for tag=%s", tag)
            continue

        found = data.get("jobs", [])
        if not found:
            logger.warning("Jobicy: no jobs for tag=%s (check tag name)", tag)

        for item in found:
            item_id = str(item.get("id", ""))
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            pub_date = item.get("pubDate", "")
            try:
                post_date = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                try:
                    post_date = datetime.strptime(pub_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    post_date = datetime.now(timezone.utc)

            if post_date < cutoff:
                continue

            job_type_raw = item.get("jobType", [])
            if isinstance(job_type_raw, list):
                tags = job_type_raw
            elif isinstance(job_type_raw, str):
                tags = [job_type_raw]
            else:
                tags = []

            job_type = ""
            for t in tags:
                tl = t.lower()
                if "full" in tl:
                    job_type = "full-time"
                elif "contract" in tl:
                    job_type = "contract"
                elif "part" in tl:
                    job_type = "part-time"
                elif "freelance" in tl:
                    job_type = "freelance"

            sal_min = float(item.get("annualSalaryMin") or 0)
            sal_max = float(item.get("annualSalaryMax") or 0)
            salary_parts = []
            if sal_min:
                salary_parts.append(f"min: {sal_min:.0f}")
            if sal_max:
                salary_parts.append(f"max: {sal_max:.0f}")

            job = JobPosting(
                id=f"jobicy_{item_id}",
                source="jobicy",
                title=item.get("jobTitle", ""),
                company=item.get("companyName", ""),
                location=item.get("jobGeo", ""),
                url=item.get("url", ""),
                description=item.get("jobDescription", "")[:3000],
                date_posted=post_date.strftime("%Y-%m-%d"),
                tags=tags,
                salary=", ".join(salary_parts),
                salary_min=sal_min,
                salary_max=sal_max,
                job_type=job_type,
                remote_type="remote",
            )
            jobs.append(enrich(job))

    logger.info("Jobicy: fetched %d jobs (scanned %d across %d tags)", len(jobs), len(seen_ids), len(JOBICY_TAGS))
    return jobs
