#!/usr/bin/env python3
import json
import logging
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(__file__))

import config
from sources import (
    adzuna, arbeitnow, remoteok, himalayas, jobicy, jsearch,
    wwr, linkedin, relocateme,
    remotive, landingjobs, wellfound, remoteco,
)
from scorer import score_job
from state import StateManager
from alerts import create_alert_issue
from ai_evaluator import evaluate_matches, evaluate_companies
from dashboard import generate_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("sayema-finder")

JOBS_FILE = os.path.join(os.path.dirname(__file__), "data", "jobs.json")
COMPANY_CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "company_cache.json")
TRACKER_API_URL = os.environ.get("TRACKER_API_URL", "")


def _fetch_tracked_statuses() -> dict:
    if not TRACKER_API_URL:
        return {}
    try:
        resp = requests.get(f"{TRACKER_API_URL}/api/statuses", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        logger.warning("Could not fetch tracked statuses from %s", TRACKER_API_URL)
    return {}


def _load_cumulative_jobs() -> list[dict]:
    try:
        with open(JOBS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _rescore_cumulative(jobs: list[dict], company_cache: dict | None = None) -> int:
    from sources.base import JobPosting, enrich
    updated = 0
    for j in jobs:
        job = JobPosting(
            id=j.get("id", ""), source=j.get("source", ""),
            title=j.get("title", ""), company=j.get("company", ""),
            location=j.get("location", ""), url=j.get("url", ""),
            description=j.get("description", ""), date_posted=j.get("date_posted", ""),
            tags=j.get("tags", []), salary=j.get("salary", ""),
            seniority=j.get("seniority", ""), remote_type=j.get("remote_type", ""),
            job_type=j.get("job_type", ""), visa_sponsorship=j.get("visa_sponsorship", ""),
        )
        job = enrich(job)
        if job.company_normalized and j.get("company_normalized") != job.company_normalized:
            j["company_normalized"] = job.company_normalized
        enrichment = company_cache.get(job.company_normalized) if company_cache and job.company_normalized else None
        new_score, new_breakdown = score_job(job, company_enrichment=enrichment)
        if new_score != j.get("score"):
            updated += 1
            j["score"] = new_score
            j["breakdown"] = new_breakdown
    return updated


def _dedup_cumulative(jobs: list[dict]) -> tuple[list[dict], int]:
    seen: dict[str, int] = {}
    result = []
    for j in jobs:
        c = j.get("company_normalized") or re.sub(r"[^a-z0-9]", "", j.get("company", "").lower())
        t = re.sub(r"[^a-z0-9]", "", j.get("title", "").lower())
        loc = re.sub(r"[^a-z0-9]", "", j.get("location", "").lower())
        fp = f"{c}::{t}::{loc}"
        if fp in seen:
            idx = seen[fp]
            if j.get("score", 0) > result[idx].get("score", 0):
                result[idx] = j
            continue
        seen[fp] = len(result)
        result.append(j)
    removed = len(jobs) - len(result)
    return result, removed


MAX_CUMULATIVE_JOBS = 5000


def _atomic_json_write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _save_cumulative_jobs(jobs: list[dict], tracked_ids: set[str] | None = None) -> None:
    if len(jobs) > MAX_CUMULATIVE_JOBS:
        if tracked_ids:
            tracked = [j for j in jobs if j.get("id") in tracked_ids]
            untracked = [j for j in jobs if j.get("id") not in tracked_ids]
            untracked.sort(key=lambda j: j.get("date_posted", ""), reverse=True)
            keep = MAX_CUMULATIVE_JOBS - len(tracked)
            jobs = tracked + untracked[:max(0, keep)]
        else:
            jobs.sort(key=lambda j: j.get("date_posted", ""), reverse=True)
            jobs = jobs[:MAX_CUMULATIVE_JOBS]
    _atomic_json_write(JOBS_FILE, jobs)


def _job_fingerprint(job) -> str:
    company = job.company_normalized if job.company_normalized else re.sub(r"[^a-z0-9]", "", job.company.lower())
    title = re.sub(r"[^a-z0-9]", "", job.title.lower())
    location = re.sub(r"[^a-z0-9]", "", job.location.lower())
    return f"{company}::{title}::{location}"


def _deduplicate(jobs: list) -> list:
    seen: dict[str, int] = {}
    result = []
    for job in jobs:
        fp = _job_fingerprint(job)
        if fp in seen:
            continue
        seen[fp] = 1
        result.append(job)
    return result


def _fetch_source(name: str, fetch_fn) -> list:
    logger.info("Fetching from %s...", name)
    try:
        result = fetch_fn()
        logger.info("%s: got %d jobs", name, len(result))
        return result
    except Exception:
        logger.exception("%s: failed", name)
        return []


def _load_company_cache() -> dict:
    try:
        with open(COMPANY_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_company_cache(cache: dict) -> None:
    _atomic_json_write(COMPANY_CACHE_FILE, cache)


def _enrich_companies(cumulative: list[dict], company_cache: dict, test_mode: bool = False) -> tuple[dict, list[str]]:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    companies_to_enrich: dict[str, dict] = {}
    for j in cumulative:
        cn = j.get("company_normalized", "")
        if not cn:
            continue
        if j.get("score", 0) < config.ENRICHMENT_THRESHOLD:
            continue
        if cn in company_cache:
            cached = company_cache[cn]
            last_eval = cached.get("last_evaluated", "")
            if last_eval:
                try:
                    eval_date = datetime.strptime(last_eval, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - eval_date).days
                    if age < 90:
                        continue
                except ValueError:
                    pass
        if cn not in companies_to_enrich:
            companies_to_enrich[cn] = {
                "key": cn,
                "name": j.get("company", ""),
                "sample_jobs": [],
            }
        if len(companies_to_enrich[cn]["sample_jobs"]) < 2:
            companies_to_enrich[cn]["sample_jobs"].append({
                "title": j.get("title", ""),
                "location": j.get("location", ""),
                "description_excerpt": j.get("description", "")[:500],
            })

    if not companies_to_enrich:
        logger.info("Company enrichment: all companies cached, nothing to enrich")
        return company_cache, []

    batch = list(companies_to_enrich.values())
    if test_mode:
        batch = batch[:3]

    logger.info("Company enrichment: %d companies to evaluate", len(batch))
    results = evaluate_companies(batch)

    newly_enriched = []
    for key, data in results.items():
        data["last_evaluated"] = today
        company_cache[key] = data
        newly_enriched.append(key)

    if newly_enriched:
        _save_company_cache(company_cache)
        logger.info("Company cache updated: %d new entries, %d total", len(newly_enriched), len(company_cache))

    return company_cache, newly_enriched


def _get_today_sources(force_all: bool = False, tier_override: str = "") -> set[str]:
    if force_all:
        all_sources: set[str] = set()
        for names in config.SOURCE_TIERS.values():
            all_sources.update(names)
        return all_sources
    if tier_override and tier_override != "auto":
        if tier_override == "all":
            all_sources = set()
            for names in config.SOURCE_TIERS.values():
                all_sources.update(names)
            return all_sources
        active: set[str] = set()
        active.update(config.SOURCE_TIERS.get("daily", []))
        active.update(config.SOURCE_TIERS.get(tier_override, []))
        logger.info("Source tier override: %s → %s", tier_override, ", ".join(sorted(active)))
        return active
    from datetime import datetime, timezone
    weekday = datetime.now(timezone.utc).weekday()
    active_tiers = config.TIER_SCHEDULE.get(weekday, ["daily", "A", "B", "C"])
    active = set()
    for tier in active_tiers:
        active.update(config.SOURCE_TIERS.get(tier, []))
    return active


# Display name in SOURCE_TIERS -> the source string adapters set on JobPosting.
_SOURCE_KEYS = {
    "Arbeitnow": "arbeitnow",
    "Himalayas": "himalayas",
    "Jobicy": "jobicy",
    "WWR": "wwr",
    "LinkedIn": "linkedin",
    "Remotive": "remotive",
    "JSearch": "jsearch",
    "Adzuna": "adzuna",
    "Remote.co": "remoteco",
}


def _get_today_linkedin_locations(force_all: bool = False, group_override: str = "") -> list[str]:
    if force_all:
        return config.LINKEDIN_LOCATIONS_GROUP1 + config.LINKEDIN_LOCATIONS_GROUP2 + config.LINKEDIN_LOCATIONS_GROUP3
    if group_override and group_override != "auto":
        groups = {
            "1": config.LINKEDIN_LOCATIONS_GROUP1,
            "2": config.LINKEDIN_LOCATIONS_GROUP2,
            "3": config.LINKEDIN_LOCATIONS_GROUP3,
            "all": config.LINKEDIN_LOCATIONS_GROUP1 + config.LINKEDIN_LOCATIONS_GROUP2 + config.LINKEDIN_LOCATIONS_GROUP3,
            "none": [],
        }
        locs = groups.get(group_override, [])
        logger.info("LinkedIn group override: %s → %d locations", group_override, len(locs))
        return locs
    from datetime import datetime, timezone
    weekday = datetime.now(timezone.utc).weekday()
    return config.LINKEDIN_LOCATION_SCHEDULE.get(weekday, [])


def main() -> None:
    role_profile = os.environ.get("ROLE_PROFILE", "customer_success")
    config.activate_profile(role_profile)
    logger.info("Active profile: %s", config.ACTIVE_PROFILE)

    test_mode = os.environ.get("TEST_MODE", "").lower() in ("1", "true", "yes")
    if test_mode:
        logger.info("TEST MODE — capping API calls, skipping issue creation and state persistence")

    logger.info("Starting sayema-finder run")
    state = StateManager()

    tracked_statuses = _fetch_tracked_statuses()
    tracked_ids = set(tracked_statuses.keys())
    tracked_skip = {"applied", "interviewing", "offered", "rejected", "skipped"}
    if tracked_ids:
        logger.info("Tracker: %d jobs with statuses (will skip %s from alerts)",
                     len(tracked_ids), ", ".join(sorted(tracked_skip)))

    all_jobs = []
    source_counts = {}
    seen_ids = set(state.seen.keys())
    cumulative = _load_cumulative_jobs()
    existing_fps: set[str] = set()
    for j in cumulative:
        c = j.get("company_normalized") or re.sub(r"[^a-z0-9]", "", j.get("company", "").lower())
        t = re.sub(r"[^a-z0-9]", "", j.get("title", "").lower())
        loc = re.sub(r"[^a-z0-9]", "", j.get("location", "").lower())
        existing_fps.add(f"{c}::{t}::{loc}")
    logger.info("State loaded: %d seen IDs, %d cumulative fingerprints", len(seen_ids), len(existing_fps))

    force_all = os.environ.get("RUN_ALL_SOURCES", "").lower() in ("1", "true", "yes")
    tier_override = os.environ.get("SOURCE_TIER", "").strip()
    linkedin_group_override = os.environ.get("LINKEDIN_GROUP", "").strip()
    active_sources = _get_today_sources(force_all=force_all or test_mode, tier_override=tier_override)
    today_linkedin_locs = _get_today_linkedin_locations(force_all=force_all or test_mode, group_override=linkedin_group_override)

    if test_mode:
        adzuna_queries = config.ADZUNA_QUERIES[:1]
        adzuna_countries = config.ADZUNA_COUNTRIES[:1]
        jsearch_queries = config.JSEARCH_QUERIES[:1]
        linkedin_queries = config.SEARCH_QUERIES[:2]
        linkedin_locations = linkedin.LOCATIONS[:3]
        himalayas_queries = config.SEARCH_QUERIES[:2]
    else:
        adzuna_queries = config.ADZUNA_QUERIES
        adzuna_countries = config.ADZUNA_COUNTRIES
        jsearch_queries = config.JSEARCH_QUERIES
        linkedin_queries = config.SEARCH_QUERIES
        linkedin_locations = today_linkedin_locs
        himalayas_queries = config.SEARCH_QUERIES

    sources = [
        ("Arbeitnow", lambda: arbeitnow.fetch_jobs(max_days_old=config.MAX_DAYS_OLD)),
        ("Himalayas", lambda: himalayas.fetch_jobs(queries=himalayas_queries, max_days_old=config.MAX_DAYS_OLD)),
        ("Jobicy", lambda: jobicy.fetch_jobs(max_days_old=config.MAX_DAYS_OLD)),
        ("WWR", lambda: wwr.fetch_jobs(max_days_old=config.MAX_DAYS_OLD)),
        ("LinkedIn", lambda: linkedin.fetch_jobs(max_days_old=config.MAX_DAYS_OLD, queries=linkedin_queries, locations=linkedin_locations, seen_ids=seen_ids)),
        ("Remotive", lambda: remotive.fetch_jobs(max_days_old=config.MAX_DAYS_OLD)),
        ("JSearch", lambda: jsearch.fetch_jobs(queries=jsearch_queries, max_days_old=config.MAX_DAYS_OLD)),
        ("Adzuna", lambda: adzuna.fetch_jobs(queries=adzuna_queries, countries=adzuna_countries, max_days_old=config.MAX_DAYS_OLD)),
        ("Remote.co", lambda: remoteco.fetch_jobs(max_days_old=config.MAX_DAYS_OLD)),
    ]

    browser_sources = set()
    api_sources = []
    skipped_sources = []
    for name, fetch_fn in sources:
        if name not in active_sources:
            skipped_sources.append(name)
            continue
        api_sources.append((name, fetch_fn))

    all_fetched_ids: list[str] = []

    def _filter_known(jobs: list, source_name: str) -> list:
        filtered = []
        skipped_id = 0
        skipped_fp = 0
        for job in jobs:
            all_fetched_ids.append(job.id)
            if job.id in seen_ids:
                skipped_id += 1
                continue
            fp = _job_fingerprint(job)
            if fp in existing_fps:
                skipped_fp += 1
                continue
            filtered.append(job)
        if skipped_id or skipped_fp:
            logger.info("%s: skipped %d seen-ID + %d known-fingerprint (kept %d)", source_name, skipped_id, skipped_fp, len(filtered))
        return filtered

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_fetch_source, name, fn): name for name, fn in api_sources}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                source_counts[name] = len(result)
                result = _filter_known(result, name)
                all_jobs.extend(result)
            except Exception:
                logger.exception("Source %s failed in thread pool", name)
                source_counts[name] = 0

    if skipped_sources:
        logger.info("Skipped %d sources (not scheduled today): %s", len(skipped_sources), ", ".join(skipped_sources))

    logger.info("Total jobs fetched: %d", len(all_jobs))

    healthy = []
    empty = []
    for name, count in source_counts.items():
        if count > 0:
            healthy.append(f"{name}({count})")
        else:
            empty.append(name)
    logger.info("Source health — OK: %s", ", ".join(healthy) if healthy else "none")
    if empty:
        logger.warning("Source health — ZERO RESULTS: %s (check logs above for per-source errors)", ", ".join(empty))

    before_dedup = len(all_jobs)
    all_jobs = _deduplicate(all_jobs)
    dupes = before_dedup - len(all_jobs)
    if dupes:
        logger.info("Cross-source dedup removed %d duplicates (%d -> %d)", dupes, before_dedup, len(all_jobs))

    new_jobs = all_jobs
    logger.info("New jobs after early filtering: %d", len(new_jobs))

    company_cache = _load_company_cache()

    scored = []
    for job in new_jobs:
        enrichment = company_cache.get(job.company_normalized) if job.company_normalized else None
        score, breakdown = score_job(job, company_enrichment=enrichment)
        scored.append((job, score, breakdown))

    rescored = _rescore_cumulative(cumulative, company_cache=company_cache)
    if rescored:
        logger.info("Re-scored %d cumulative jobs with updated rules", rescored)

    cumulative, dedup_removed = _dedup_cumulative(cumulative)
    if dedup_removed:
        logger.info("Cumulative dedup removed %d duplicates", dedup_removed)

    added = 0
    for job, score, breakdown in scored:
        fp = _job_fingerprint(job)
        if fp in existing_fps:
            continue
        existing_fps.add(fp)
        added += 1
        cumulative.append({
            "id": job.id,
            "source": job.source,
            "title": job.title,
            "company": job.company,
            "company_normalized": job.company_normalized,
            "location": job.location,
            "url": job.url,
            "description": job.description,
            "date_posted": job.date_posted,
            "tags": job.tags,
            "salary": job.salary,
            "seniority": job.seniority,
            "remote_type": job.remote_type,
            "job_type": job.job_type,
            "visa_sponsorship": job.visa_sponsorship,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_currency": job.salary_currency,
            "score": score,
            "breakdown": breakdown,
        })
    skipped_dupes = len(scored) - added
    if skipped_dupes:
        logger.info("Cross-run dedup: skipped %d already-existing jobs", skipped_dupes)
    _save_cumulative_jobs(cumulative, tracked_ids=tracked_ids or None)
    logger.info("Cumulative jobs total: %d (added %d new)", len(cumulative), added)

    company_cache, newly_enriched = _enrich_companies(cumulative, company_cache, test_mode=test_mode)
    if newly_enriched:
        enriched_count = 0
        for j in cumulative:
            cn = j.get("company_normalized", "")
            if cn in newly_enriched:
                from sources.base import JobPosting, enrich as enrich_job
                job = JobPosting(
                    id=j.get("id", ""), source=j.get("source", ""),
                    title=j.get("title", ""), company=j.get("company", ""),
                    location=j.get("location", ""), url=j.get("url", ""),
                    description=j.get("description", ""), date_posted=j.get("date_posted", ""),
                    tags=j.get("tags", []), salary=j.get("salary", ""),
                    seniority=j.get("seniority", ""), remote_type=j.get("remote_type", ""),
                    job_type=j.get("job_type", ""), visa_sponsorship=j.get("visa_sponsorship", ""),
                )
                job = enrich_job(job)
                new_score, new_breakdown = score_job(job, company_enrichment=company_cache.get(cn))
                if new_score != j.get("score"):
                    j["score"] = new_score
                    j["breakdown"] = new_breakdown
                    enriched_count += 1
        if enriched_count:
            logger.info("Re-scored %d jobs after company enrichment", enriched_count)
            _save_cumulative_jobs(cumulative, tracked_ids=tracked_ids or None)
        for job_t, score_t, breakdown_t in scored:
            cn = job_t.company_normalized
            if cn in newly_enriched:
                new_score, new_breakdown = score_job(job_t, company_enrichment=company_cache.get(cn))
                scored = [(j, new_score if j is job_t else s, new_breakdown if j is job_t else b) for j, s, b in scored]

    matches = [
        (job, score)
        for job, score, _ in scored
        if score >= config.ALERT_THRESHOLD
        and tracked_statuses.get(job.id, {}).get("status") not in tracked_skip
    ]
    matches.sort(key=lambda x: x[1], reverse=True)

    logger.info("Matches above threshold (%d): %d", config.ALERT_THRESHOLD, len(matches))

    # Per-source yield. A source that fetches plenty but yields nothing is
    # pointed at the wrong category — without this it just hides behind the
    # scorer, which is how the QA-query bug went unnoticed for a full run.
    usable_by_source: dict[str, int] = {}
    for job, score, _ in scored:
        if score >= config.ALERT_THRESHOLD:
            usable_by_source[job.source] = usable_by_source.get(job.source, 0) + 1

    source_stats = []
    for name, fetched in sorted(source_counts.items(), key=lambda kv: -kv[1]):
        key = _SOURCE_KEYS.get(name, name.lower())
        usable = usable_by_source.get(key, 0)
        source_stats.append({
            "source": name,
            "fetched": fetched,
            "usable": usable,
            "yield": (100.0 * usable / fetched) if fetched else 0.0,
        })

    logger.info("--- per-source yield (fetched -> usable) ---")
    for st in source_stats:
        flag = "  <-- ZERO YIELD" if st["fetched"] > 20 and st["usable"] == 0 else ""
        logger.info("  %-14s %5d -> %4d  (%.1f%%)%s",
                    st["source"], st["fetched"], st["usable"], st["yield"], flag)

    ai_matches = matches[:3] if test_mode else matches
    enrichments = evaluate_matches(ai_matches)
    if enrichments:
        logger.info("AI enrichment: %d jobs evaluated", len(enrichments))
        for job_data in cumulative:
            if job_data["id"] in enrichments:
                job_data["ai"] = enrichments[job_data["id"]]
        _save_cumulative_jobs(cumulative, tracked_ids=tracked_ids or None)

    if test_mode:
        logger.info("TEST MODE — skipping GitHub issue creation")
    elif matches:
        create_alert_issue(matches, enrichments, company_cache=company_cache, source_stats=source_stats)
    else:
        logger.info("No matches found — no alert created")

    for job, score in matches[:10]:
        logger.info(
            "  [%d] %s @ %s (%s) — %s",
            score, job.title, job.company, job.location, job.source,
        )

    logger.info("Generating dashboard...")
    generate_dashboard(company_cache=company_cache)

    if test_mode:
        logger.info("TEST MODE — skipping state persistence")
    else:
        state.mark_seen(all_fetched_ids)
        state.prune()
        state.save()

    total_sources = len(source_counts)
    working_sources = sum(1 for c in source_counts.values() if c > 0)
    total_fetched = sum(source_counts.values())
    early_filtered = total_fetched - before_dedup
    logger.info(
        "=== RUN SUMMARY [%s] === sources=%d/%d ok | fetched=%d | early_skip=%d | dedup=%d | new=%d | added=%d | "
        "matches=%d (threshold=%d) | ai_enriched=%d/%d | cumulative=%d",
        config.ACTIVE_PROFILE,
        working_sources, total_sources, total_fetched, early_filtered, dupes, len(new_jobs),
        added, len(matches), config.ALERT_THRESHOLD,
        len(enrichments), len(ai_matches),
        len(cumulative),
    )
    logger.info("Run complete")


if __name__ == "__main__":
    main()
