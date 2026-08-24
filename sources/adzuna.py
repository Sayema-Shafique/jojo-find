import logging
import os
import time

import requests

from .base import JobPosting, enrich

logger = logging.getLogger(__name__)

API_BASE = "https://api.adzuna.com/v1/api/jobs"


def _get_with_retry(url: str, params: dict, max_retries: int = 2) -> requests.Response | None:
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 503 and attempt < max_retries:
                time.sleep(2 ** (attempt + 1))
                continue
            if resp.status_code == 404:
                logger.warning("Adzuna 404 for %s — response: %s", url, resp.text[:500])
                return None
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError:
            if resp.status_code == 503 and attempt < max_retries:
                time.sleep(2 ** (attempt + 1))
                continue
            logger.warning("Adzuna HTTP %d for %s — response: %s", resp.status_code, url, resp.text[:500])
            raise
    return None


def fetch_jobs(
    queries: list[str],
    countries: list[str],
    max_days_old: int = 3,
) -> list[JobPosting]:
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")

    if not app_id or not app_key:
        logger.warning("Adzuna API keys not set — skipping Adzuna source")
        return []

    jobs: list[JobPosting] = []
    seen_ids: set[str] = set()

    for country in countries:
        for query in queries:
            try:
                resp = _get_with_retry(
                    f"{API_BASE}/{country}/search/1",
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "what": query,
                        "results_per_page": 50,
                        "max_days_old": max_days_old,
                        "content-type": "application/json",
                    },
                )
                if resp is None:
                    continue
                data = resp.json()
            except Exception:
                logger.exception(
                    "Adzuna API error for country=%s query=%s", country, query
                )
                continue

            for item in data.get("results", []):
                adzuna_id = str(item.get("id", ""))
                if adzuna_id in seen_ids:
                    continue
                seen_ids.add(adzuna_id)

                location_parts = []
                loc = item.get("location", {})
                for area in loc.get("area", []):
                    location_parts.append(area)
                location_str = ", ".join(location_parts) if location_parts else country.upper()

                salary_min = float(item.get("salary_min") or 0)
                salary_max = float(item.get("salary_max") or 0)
                salary_parts = []
                if salary_min:
                    salary_parts.append(f"min: {salary_min:.0f}")
                if salary_max:
                    salary_parts.append(f"max: {salary_max:.0f}")

                contract_type = (item.get("contract_type") or "").lower()
                job_type = ""
                if "permanent" in contract_type or "full" in contract_type:
                    job_type = "full-time"
                elif "contract" in contract_type:
                    job_type = "contract"
                elif "part" in contract_type:
                    job_type = "part-time"

                job = JobPosting(
                    id=f"adzuna_{adzuna_id}",
                    source="adzuna",
                    title=item.get("title", ""),
                    company=item.get("company", {}).get("display_name", ""),
                    location=location_str,
                    url=item.get("redirect_url", ""),
                    description=item.get("description", "")[:2000],
                    date_posted=item.get("created", "")[:10],
                    salary=", ".join(salary_parts),
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=item.get("salary_currency", ""),
                    job_type=job_type,
                )
                jobs.append(enrich(job))

    if not jobs:
        logger.warning("Adzuna: 0 jobs — check ADZUNA_APP_ID/ADZUNA_APP_KEY validity and API subscription status")
    else:
        logger.info("Adzuna: fetched %d jobs across %d countries", len(jobs), len(countries))
    return jobs
