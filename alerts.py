import logging
import os
from datetime import datetime, timezone

import requests

from sources.base import JobPosting
import config

logger = logging.getLogger(__name__)


def _build_issue_body(
    matches: list[tuple[JobPosting, int]],
    enrichments: dict[str, dict] | None = None,
    company_cache: dict | None = None,
) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sources = sorted({job.source for job, _ in matches})

    if enrichments and company_cache:
        return _build_company_grouped_body(matches, enrichments, company_cache, today, sources)
    if enrichments:
        return _build_enriched_body(matches, enrichments, today, sources)
    return _build_basic_body(matches, today, sources)


def _build_basic_body(
    matches: list[tuple[JobPosting, int]],
    today: str,
    sources: list[str],
) -> str:
    lines = [
        f"## Job Finder Alert — {today}",
        f"Found **{len(matches)}** new matching roles from {', '.join(sources)}.",
        "",
    ]

    tiers = [
        ("Top Matches", lambda s: s >= config.HIGH_MATCH_THRESHOLD),
        ("Good Matches", lambda s: config.MEDIUM_MATCH_THRESHOLD <= s < config.HIGH_MATCH_THRESHOLD),
        ("Worth a Look", lambda s: config.ALERT_THRESHOLD <= s < config.MEDIUM_MATCH_THRESHOLD),
    ]

    for tier_name, predicate in tiers:
        tier_matches = [(job, score) for job, score in matches if predicate(score)]
        if not tier_matches:
            continue

        lines.append(f"### {tier_name}")
        lines.append("")
        lines.append("| Score | Title | Company | Location | Source | Link |")
        lines.append("|-------|-------|---------|----------|--------|------|")

        for job, score in tier_matches:
            title = job.title.replace("|", "\\|")[:60]
            company = job.company.replace("|", "\\|")[:30]
            location = job.location.replace("|", "\\|")[:25]
            lines.append(
                f"| {score} | {title} | {company} | {location} | {job.source} | [View]({job.url}) |"
            )

        lines.append("")

    return "\n".join(lines)


def _build_enriched_body(
    matches: list[tuple[JobPosting, int]],
    enrichments: dict[str, dict],
    today: str,
    sources: list[str],
) -> str:
    priority_order = {"high": 0, "medium": 1, "low": 2, "skip": 3}

    categorized: dict[str, list[tuple[JobPosting, int, dict]]] = {
        "high": [], "medium": [], "low": [], "skip": [],
    }

    for job, score in matches:
        ai = enrichments.get(job.id)
        if ai:
            priority = ai.get("priority", "medium")
            if priority not in priority_order:
                priority = "medium"
            categorized[priority].append((job, score, ai))
        else:
            categorized["medium"].append((job, score, {}))

    high_count = len(categorized["high"])
    medium_count = len(categorized["medium"])

    lines = [
        f"## Job Finder Alert — {today}",
        f"Found **{len(matches)}** new matching roles from {', '.join(sources)}."
        f" AI evaluation prioritized **{high_count}** high, **{medium_count}** medium.",
        "",
    ]

    section_labels = [
        ("high", "High Priority"),
        ("medium", "Medium Priority"),
        ("low", "Low Priority"),
        ("skip", "Skip"),
    ]

    for priority, label in section_labels:
        jobs = categorized[priority]
        if not jobs:
            continue

        collapse = priority in ("low", "skip")

        if collapse:
            lines.append(f"<details><summary><strong>{label}</strong> ({len(jobs)})</summary>")
            lines.append("")

        lines.append(f"### {label}")
        lines.append("")
        lines.append("| Score | Title | Company | Location | Why | Link |")
        lines.append("|-------|-------|---------|----------|-----|------|")

        for job, score, ai in jobs:
            title = job.title.replace("|", "\\|")[:60]
            company = job.company.replace("|", "\\|")[:30]
            location = job.location.replace("|", "\\|")[:25]
            why = ai.get("one_liner", "").replace("|", "\\|")[:80] if ai else ""
            lines.append(
                f"| {score} | {title} | {company} | {location} | {why} | [View]({job.url}) |"
            )

        lines.append("")

        if collapse:
            lines.append("</details>")
            lines.append("")

    return "\n".join(lines)


def _build_company_grouped_body(
    matches: list[tuple[JobPosting, int]],
    enrichments: dict[str, dict],
    company_cache: dict,
    today: str,
    sources: list[str],
) -> str:
    from company import normalize_company_name

    priority_order = {"high": 0, "medium": 1, "low": 2, "skip": 3}
    categorized: dict[str, list[tuple[JobPosting, int, dict]]] = {
        "high": [], "medium": [], "low": [], "skip": [],
    }

    for job, score in matches:
        ai = enrichments.get(job.id)
        if ai:
            priority = ai.get("priority", "medium")
            if priority not in priority_order:
                priority = "medium"
            categorized[priority].append((job, score, ai))
        else:
            categorized["medium"].append((job, score, {}))

    high_count = len(categorized["high"])
    medium_count = len(categorized["medium"])

    lines = [
        f"## Job Finder Alert — {today}",
        f"Found **{len(matches)}** new matching roles from {', '.join(sources)}."
        f" AI evaluation prioritized **{high_count}** high, **{medium_count}** medium.",
        "",
    ]

    section_labels = [
        ("high", "High Priority"),
        ("medium", "Medium Priority"),
        ("low", "Low Priority"),
        ("skip", "Skip"),
    ]

    for priority, label in section_labels:
        jobs = categorized[priority]
        if not jobs:
            continue

        collapse = priority in ("low", "skip")

        if collapse:
            lines.append(f"<details><summary><strong>{label}</strong> ({len(jobs)})</summary>")
            lines.append("")

        lines.append(f"### {label}")
        lines.append("")

        company_groups: dict[str, list[tuple[JobPosting, int, dict]]] = {}
        for job, score, ai in jobs:
            cn = normalize_company_name(job.company) if job.company else job.company.lower()
            if cn not in company_groups:
                company_groups[cn] = []
            company_groups[cn].append((job, score, ai))

        sorted_companies = sorted(company_groups.items(), key=lambda x: max(s for _, s, _ in x[1]), reverse=True)

        for cn, group_jobs in sorted_companies:
            cc = company_cache.get(cn, {})
            display_name = cc.get("canonical_name", group_jobs[0][0].company)
            meta_parts = []
            if cc.get("industry_sector"):
                meta_parts.append(cc["industry_sector"])
            if cc.get("employee_count_range") and cc["employee_count_range"] != "unknown":
                meta_parts.append(f"{cc['employee_count_range']} employees")
            if cc.get("visa_likelihood") == "likely":
                meta_parts.append("Visa likely")
            if cc.get("ai_relevance") in ("core", "partial"):
                meta_parts.append(f"AI: {cc['ai_relevance']}")
            meta = " — " + ", ".join(meta_parts) if meta_parts else ""

            job_count = f" ({len(group_jobs)} jobs)" if len(group_jobs) > 1 else ""
            lines.append(f"#### {display_name}{job_count}{meta}")
            lines.append("")
            lines.append("| Score | Title | Location | Why | Link |")
            lines.append("|-------|-------|----------|-----|------|")

            for job, score, ai in sorted(group_jobs, key=lambda x: x[1], reverse=True):
                title = job.title.replace("|", "\\|")[:60]
                location = job.location.replace("|", "\\|")[:25]
                why = ai.get("one_liner", "").replace("|", "\\|")[:80] if ai else ""
                lines.append(
                    f"| {score} | {title} | {location} | {why} | [View]({job.url}) |"
                )

            lines.append("")

        if collapse:
            lines.append("</details>")
            lines.append("")

    return "\n".join(lines)


def create_alert_issue(
    matches: list[tuple[JobPosting, int]],
    enrichments: dict[str, dict] | None = None,
    company_cache: dict | None = None,
) -> None:
    if not matches:
        logger.info("No matches — skipping alert")
        return

    token = os.environ.get("GITHUB_TOKEN", "")
    repo_owner = os.environ.get("REPO_OWNER", "chowdhury-nahid")
    repo_name = os.environ.get("REPO_NAME", "preparing-j")

    if not token:
        logger.warning("GITHUB_TOKEN not set — printing matches to stdout instead")
        body = _build_issue_body(matches, enrichments, company_cache=company_cache)
        print(body)
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    has_high = any(score >= config.HIGH_MATCH_THRESHOLD for _, score in matches)

    labels = ["job-finder"]
    if has_high:
        labels.append("high-match")
    if enrichments:
        high_priority = any(
            enrichments.get(job.id, {}).get("priority") == "high"
            for job, _ in matches
        )
        if high_priority:
            labels.append("ai-high-priority")

    title = f"Job Finder: {len(matches)} new matches — {today}"
    body = _build_issue_body(matches, enrichments, company_cache=company_cache)

    try:
        resp = requests.post(
            f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            },
            json={
                "title": title,
                "body": body,
                "labels": labels,
            },
            timeout=30,
        )
        resp.raise_for_status()
        issue_url = resp.json().get("html_url", "")
        logger.info("Created alert issue: %s", issue_url)
    except Exception:
        logger.exception("Failed to create GitHub issue — printing to stdout")
        print(_build_issue_body(matches, enrichments, company_cache=company_cache))
