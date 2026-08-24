import logging
import os
import time

import requests

from .base import JobPosting, enrich

logger = logging.getLogger(__name__)

API_URL = "https://jsearch.p.rapidapi.com/search"


def fetch_jobs(queries: list[str], max_days_old: int = 3) -> list[JobPosting]:
    api_key = os.environ.get("JSEARCH_API_KEY", "")

    if not api_key:
        logger.warning("JSEARCH_API_KEY not set — skipping JSearch source")
        return []

    jobs: list[JobPosting] = []
    seen_ids: set[str] = set()

    date_posted_map = {1: "today", 3: "3days", 7: "week", 30: "month"}
    date_posted = date_posted_map.get(max_days_old, "week")

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    for query in queries:
        resp = None
        for attempt in range(3):
            try:
                resp = requests.get(
                    API_URL,
                    params={
                        "query": query,
                        "page": "1",
                        "num_pages": "1",
                        "date_posted": date_posted,
                        "remote_jobs_only": "false",
                    },
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code == 429:
                    time.sleep(2 ** (attempt + 1))
                    continue
                resp.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                if resp is not None and resp.status_code == 429 and attempt < 2:
                    continue
                if resp is not None and resp.status_code in (401, 403):
                    logger.error("JSearch auth error (status %d) — check JSEARCH_API_KEY and RapidAPI subscription", resp.status_code)
                    return jobs
                if resp is not None and resp.status_code == 404:
                    logger.error("JSearch 404 for query=%s — API endpoint may have changed or subscription inactive", query)
                    break
                logger.exception("JSearch API error for query=%s", query)
                break
            except Exception:
                logger.exception("JSearch API error for query=%s", query)
                break
        else:
            continue

        if resp is None or resp.status_code != 200:
            continue

        try:
            data = resp.json()
        except Exception:
            logger.exception("JSearch JSON parse error for query=%s", query)
            continue

        for item in data.get("data", []):
            job_id = item.get("job_id", "")
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            sal_min = float(item.get("job_min_salary") or 0)
            sal_max = float(item.get("job_max_salary") or 0)
            sal_currency = item.get("job_salary_currency", "")
            salary_parts = []
            if sal_min:
                salary_parts.append(f"min: {sal_min:.0f}")
            if sal_max:
                salary_parts.append(f"max: {sal_max:.0f}")
            if sal_currency:
                salary_parts.append(sal_currency)

            location_parts = []
            if item.get("job_city"):
                location_parts.append(item["job_city"])
            if item.get("job_state"):
                location_parts.append(item["job_state"])
            if item.get("job_country"):
                location_parts.append(item["job_country"])
            is_remote = item.get("job_is_remote", False)
            if is_remote:
                location_parts.append("Remote")
            location = ", ".join(location_parts) if location_parts else ""

            description = item.get("job_description", "")[:3000]

            qualifications = item.get("job_highlights", {}).get("Qualifications", [])
            tags = qualifications[:10] if isinstance(qualifications, list) else []

            employment_type = (item.get("job_employment_type") or "").lower()
            job_type = ""
            if "fulltime" in employment_type or "full_time" in employment_type:
                job_type = "full-time"
            elif "contractor" in employment_type or "contract" in employment_type:
                job_type = "contract"
            elif "parttime" in employment_type or "part_time" in employment_type:
                job_type = "part-time"

            job = JobPosting(
                id=f"jsearch_{job_id}",
                source="jsearch",
                title=item.get("job_title", ""),
                company=item.get("employer_name", ""),
                location=location,
                url=item.get("job_apply_link", "") or item.get("job_google_link", ""),
                description=description,
                date_posted=item.get("job_posted_at_datetime_utc", "")[:10],
                tags=tags,
                salary=" ".join(salary_parts),
                salary_min=sal_min,
                salary_max=sal_max,
                salary_currency=sal_currency,
                job_type=job_type,
                remote_type="remote" if is_remote else "",
            )
            jobs.append(enrich(job))

    if not jobs:
        logger.warning("JSearch: 0 jobs — likely API endpoint down or RapidAPI subscription inactive")
    else:
        logger.info("JSearch: fetched %d jobs", len(jobs))
    return jobs
