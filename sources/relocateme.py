import logging
import re
from datetime import datetime, timezone

from .base import JobPosting, enrich, stable_id

logger = logging.getLogger(__name__)

CATEGORY_URLS = [
    "https://relocate.me/international-jobs/qa",
    "https://relocate.me/international-jobs/qa-engineer",
    "https://relocate.me/international-jobs/quality-assurance",
]

MAX_PAGES = 10


def _extract_jobs_from_page(page) -> list[dict]:
    """Extract job data from the current page using JS evaluation."""
    return page.evaluate("""() => {
        const jobs = [];
        // Find all links that point to individual job pages
        const links = document.querySelectorAll('a[href*="/international-jobs/"]');
        const seen = new Set();

        for (const link of links) {
            const href = link.getAttribute('href') || '';
            // Skip category/filter links, only want individual job links
            // Job links typically have company/role slugs with multiple segments
            if (!href || seen.has(href)) continue;
            if (href.split('/').length < 4) continue;
            // Skip pagination and filter links
            if (href.includes('?page=') || href.includes('?sort=')) continue;

            seen.add(href);

            // Try to extract structured data from the card
            const card = link.closest('article, [class*="card"], [class*="Card"], [class*="job"], [class*="Job"], div');
            if (!card) continue;

            const text = card.innerText || '';
            const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);

            if (lines.length < 2) continue;

            jobs.push({
                href: href.startsWith('http') ? href : 'https://relocate.me' + href,
                text: lines,
                fullText: text.substring(0, 2000),
            });
        }
        return jobs;
    }""")


def _parse_job_data(raw: dict) -> JobPosting | None:
    """Parse raw extracted data into a JobPosting."""
    href = raw.get("href", "")
    lines = raw.get("text", [])
    full_text = raw.get("fullText", "")

    if len(lines) < 2:
        return None

    title = lines[0][:150]
    company = lines[1][:100] if len(lines) > 1 else ""
    location = ""

    for line in lines[2:6]:
        line_lower = line.lower()
        if any(geo in line_lower for geo in [
            "germany", "netherlands", "ireland", "uk", "united kingdom",
            "berlin", "amsterdam", "dublin", "london", "remote",
            "europe", "spain", "france", "sweden", "canada", "usa",
            "singapore", "australia", "switzerland", "austria", "poland",
        ]):
            location = line
            break

    if not location:
        for line in lines[2:6]:
            if len(line) < 60 and not any(kw in line.lower() for kw in ["apply", "save", "view", "posted", "ago"]):
                location = line
                break

    has_relocation = bool(re.search(r"relocation|visa|work permit|sponsorship", full_text, re.I))
    has_remote = bool(re.search(r"\bremote\b", full_text, re.I))

    job_id = stable_id("relocateme", href)

    return JobPosting(
        id=job_id,
        source="relocateme",
        title=title,
        company=company,
        location=location,
        url=href,
        description=full_text[:3000],
        date_posted=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        tags=["relocation"] if has_relocation else [],
        visa_sponsorship="yes" if has_relocation else "",
        remote_type="remote" if has_remote else "",
    )


def fetch_jobs(max_days_old: int = 7, max_pages: int | None = None) -> list[JobPosting]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright not installed — skipping Relocate.me source")
        return []

    jobs: list[JobPosting] = []
    seen_urls: set[str] = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()

            pages_limit = max_pages if max_pages is not None else MAX_PAGES
            for base_url in CATEGORY_URLS:
                for page_num in range(1, pages_limit + 1):
                    url = base_url if page_num == 1 else f"{base_url}?page={page_num}"

                    try:
                        page.goto(url, timeout=30000, wait_until="networkidle")
                    except Exception:
                        logger.exception("Relocate.me: failed to load %s", url)
                        break

                    raw_jobs = _extract_jobs_from_page(page)
                    if not raw_jobs:
                        break

                    new_on_page = 0
                    for raw in raw_jobs:
                        href = raw.get("href", "")
                        if href in seen_urls:
                            continue
                        seen_urls.add(href)

                        job = _parse_job_data(raw)
                        if job:
                            jobs.append(enrich(job))
                            new_on_page += 1

                    if new_on_page == 0:
                        break

            browser.close()

    except Exception:
        logger.exception("Relocate.me: Playwright error")

    logger.info("Relocate.me: fetched %d jobs", len(jobs))
    return jobs
