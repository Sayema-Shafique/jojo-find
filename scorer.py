import re

from sources.base import JobPosting
import config


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _word_boundary_match(keyword: str, text: str) -> bool:
    start = 0
    while True:
        pos = text.find(keyword, start)
        if pos == -1:
            return False
        before_ok = pos == 0 or not text[pos - 1].isalpha()
        end = pos + len(keyword)
        after_ok = end == len(text) or not text[end].isalpha()
        if before_ok and after_ok:
            return True
        start = pos + 1


_SENIORITY_SCORES = {
    "director": 5,
    "vp": 5,
    "principal": 5,
    "head": 4,
    "senior": 3,
    "lead": 3,
    "staff": 2,
    "manager": 2,
    "specialist": 1,
    "associate": 0,
    "junior": -3,
    "entry": -5,
    "intern": -10,
}

_REMOTE_SCORES = {
    "remote": 10,
    "hybrid": 5,
    "onsite": 0,
}

_VISA_SCORES = {
    "yes": 20,
    "no": -15,
}

_REMOTE_LOCATION_KEYWORDS = {"remote", "worldwide", "anywhere", "work from home", "wfh"}

_BOUNDARY_CHECK_SKILLS = {"crm", "erp", "kpi", "nps", "sap", "sql", "api", "b2b", "b2c", "r"}


def score_job(job: JobPosting, company_enrichment: dict | None = None) -> tuple[int, dict]:
    title = _normalize(job.title)
    description = _normalize(job.description)
    tags_text = _normalize(" ".join(job.tags))
    full_text = f"{description} {tags_text}"
    location = _normalize(job.location)

    # --- Title skip filter (negative gate) ---
    skip_reason = ""
    for skip_kw in config.TITLE_SKIP:
        if _word_boundary_match(skip_kw, title):
            skip_reason = skip_kw
            break

    if skip_reason:
        return 0, {"skip_reason": f"title_skip: {skip_reason}"}

    # --- Skills scoring (primary signal) ---
    skills_score = 0
    for keyword, weight in config.SKILL_KEYWORDS.items():
        if keyword in _BOUNDARY_CHECK_SKILLS:
            if _word_boundary_match(keyword, full_text):
                skills_score += weight
        else:
            if keyword in full_text:
                skills_score += weight
    skills_score = min(skills_score, config.SKILLS_CAP)

    # --- Visa scoring ---
    visa_score = 0
    if job.visa_sponsorship:
        visa_score = _VISA_SCORES.get(job.visa_sponsorship, 0)
    else:
        visa_pos = 0
        for keyword, weight in config.VISA_POSITIVE.items():
            if keyword in full_text:
                visa_pos = max(visa_pos, weight)
        if visa_pos > 0:
            visa_score = visa_pos
        else:
            visa_neg = 0
            for keyword, penalty in config.VISA_NEGATIVE.items():
                if keyword in full_text:
                    visa_neg = min(visa_neg, penalty)
            visa_score = visa_neg

    # --- Location scoring ---
    raw_location_score = 0
    for keyword, weight in config.LOCATION_SCORES.items():
        if keyword in location:
            raw_location_score = max(raw_location_score, weight)

    is_remote = (
        job.remote_type == "remote"
        or any(kw in location for kw in _REMOTE_LOCATION_KEYWORDS)
    )

    location_score = raw_location_score

    # --- Geo-restriction penalty ---
    geo_penalty = 0
    if is_remote:
        loc_and_desc = f"{location} {full_text}"
        for phrase in config.GEO_RESTRICTED_REMOTE:
            if phrase in loc_and_desc:
                geo_penalty = config.GEO_RESTRICTED_PENALTY
                break

    seniority_score = _SENIORITY_SCORES.get(job.seniority, 0)

    remote_score = _REMOTE_SCORES.get(job.remote_type, 0)

    # --- Visa unknown penalty (onsite job in foreign country, no visa info) ---
    visa_unknown_penalty = 0
    visa_unknown_adjusted = False
    if visa_score == 0 and not is_remote and raw_location_score > 0:
        is_bangladesh = "bangladesh" in location or "dhaka" in location
        if not is_bangladesh:
            visa_unknown_penalty = config.VISA_UNKNOWN_ONSITE_PENALTY
            if company_enrichment:
                visa_lk = company_enrichment.get("visa_likelihood", "unknown")
                if visa_lk == "likely":
                    visa_unknown_penalty = config.COMPANY_VISA_LIKELY_PENALTY
                    visa_unknown_adjusted = True
                elif (
                    company_enrichment.get("employee_count_range", "unknown") in ("201-1000", "1001-5000", "5000+")
                ):
                    visa_unknown_penalty = config.COMPANY_LARGE_FUNDED_PENALTY
                    visa_unknown_adjusted = True

    # --- Company quality bonus ---
    company_bonus = 0
    if company_enrichment:
        rep = company_enrichment.get("reputation_signal", "unknown")
        if rep == "positive":
            company_bonus += config.COMPANY_REPUTATION_POSITIVE
        elif rep == "negative":
            company_bonus += config.COMPANY_REPUTATION_NEGATIVE
        company_bonus = max(config.COMPANY_BONUS_FLOOR, min(company_bonus, config.COMPANY_BONUS_CAP))

    short_desc_penalty = config.SHORT_DESC_PENALTY if len(description) < config.SHORT_DESC_THRESHOLD else 0

    # --- Total (skills-based gate) ---
    if skills_score < config.SKILLS_MIN:
        total = 0
    else:
        total = (
            skills_score
            + location_score
            + visa_score
            + remote_score
            + seniority_score
            + visa_unknown_penalty
            + geo_penalty
            + short_desc_penalty
            + company_bonus
        )
        total = max(0, min(total, config.MAX_SCORE))

    breakdown = {
        "skills": skills_score,
        "location": location_score,
        "location_raw": raw_location_score,
        "visa": visa_score,
        "visa_unknown_penalty": visa_unknown_penalty,
        "visa_unknown_adjusted": visa_unknown_adjusted,
        "remote_score": remote_score,
        "geo_penalty": geo_penalty,
        "short_desc_penalty": short_desc_penalty,
        "company_bonus": company_bonus,
        "is_remote": is_remote,
        "seniority": job.seniority,
        "seniority_score": seniority_score,
        "remote_type": job.remote_type,
        "job_type": job.job_type,
        "visa_status": job.visa_sponsorship,
    }

    return total, breakdown
