import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .base import JobPosting, enrich, stable_id, get_with_retry

logger = logging.getLogger(__name__)

RSS_URLS = [
    "https://weworkremotely.com/categories/remote-quality-assurance-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
]


def fetch_jobs(max_days_old: int = 7) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days_old)
    seen_ids: set[str] = set()

    for rss_url in RSS_URLS:
        try:
            resp = get_with_retry(rss_url, headers={"User-Agent": "JobFinder/1.0"})
        except Exception:
            logger.exception("WWR RSS error for %s", rss_url)
            continue

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            logger.exception("WWR RSS parse error for %s", rss_url)
            continue

        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date_str = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()

            guid = link or title
            if guid in seen_ids:
                continue
            seen_ids.add(guid)

            try:
                post_date = parsedate_to_datetime(pub_date_str)
                if post_date.tzinfo is None:
                    post_date = post_date.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                post_date = datetime.now(timezone.utc)

            if post_date < cutoff:
                continue

            company = ""
            job_title = title
            if ":" in title:
                company, job_title = title.split(":", 1)
                company = company.strip()
                job_title = job_title.strip()

            description_text = description.replace("<br>", "\n").replace("<br/>", "\n")
            import re
            description_text = re.sub(r"<[^>]+>", " ", description_text)[:3000]

            job = JobPosting(
                id=stable_id("wwr", guid),
                source="wwr",
                title=job_title,
                company=company,
                location="Remote",
                url=link,
                description=description_text,
                date_posted=post_date.strftime("%Y-%m-%d"),
                tags=[],
                remote_type="remote",
            )
            jobs.append(enrich(job))

    logger.info("WWR: fetched %d jobs from %d feeds", len(jobs), len(RSS_URLS))
    return jobs
