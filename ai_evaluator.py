import json
import logging
import os
import time

from sources.base import JobPosting
import config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a job match evaluator for a customer success / business operations
professional with 5+ years of experience. You will receive a candidate profile and a batch of
job postings. For each job, produce a structured JSON evaluation.

Rules:
- Be direct and specific. No filler.
- "experience_years_required" must be extracted from the description text, not guessed.
  If no years mentioned, return null.
- "priority" is your overall recommendation: "high", "medium", "low", or "skip".
- "skip" means the job is technically in scope but practically a poor fit (wrong domain,
  too junior, no visa path, etc.). It still appears in results — just at the bottom.
- Never return jobs not in the input. Never add jobs.
- If you cannot determine a field, return null — do not guess."""

_OUTPUT_SCHEMA = """{
  "job_id": "string — Job ID from input",
  "priority": "high | medium | low | skip",
  "priority_reason": "string — 1-2 sentence explanation",
  "one_liner": "string — one sentence: why this job fits or doesn't",
  "experience_fit": "over_qualified | good_fit | stretch | under_qualified",
  "experience_years_required": "integer or null",
  "location_reality": "string — actual work arrangement",
  "industry": "string — company's actual industry",
  "company_type": "startup | scale-up | enterprise | agency | consulting | unknown",
  "domain_relevance": "core | partial | none",
  "skills_match": "string — brief skills overlap assessment",
  "red_flags": ["list of specific concerns"]
}"""

_PRIORITY_RULES = """Priority Decision Rules:
- high: Customer Success / Client Relationship / Service Management role, location works
  (any country with visa sponsorship, remote, or Bangladesh), visa not explicitly denied,
  experience range includes 5 years. Role involves CRM, client management, retention, or
  account management.
- medium: Right domain but one concern (unknown visa, slightly senior requirement,
  less preferred location). Or adjacent role: Business Development, Account Manager,
  Data Analyst with strong skills overlap. Worth applying.
- low: Marginal fit — role is adjacent (e.g., general admin with client duties, support
  representative), or location requires visa with no mention of sponsorship.
- skip: Wrong domain entirely (engineering, design, finance, healthcare), explicitly no visa
  for onsite international role, clearly too junior (intern/entry level) or too senior
  (VP/C-level), or pure call center agent role with no growth path."""


def _format_candidate_profile() -> str:
    p = config.CANDIDATE_PROFILE
    seniority_pref = p.get("seniority_preference", {})
    seniority_str = ", ".join(f"{k} = {v}" for k, v in seniority_pref.items())
    lines = [
        f"Current Role: {p['current_role']}",
        f"Target Role: {p['target_role']}",
        f"Years of Experience: {p['years_experience']}",
        f"Minimum Acceptable Experience Requirement: {p['min_acceptable_experience']} years",
        f"Seniority Preference: {seniority_str}",
        f"Current Location: {p['location']}",
        f"Target Locations: {', '.join(p['target_locations'])}",
        f"Visa Status: {p['visa_status']}",
        f"Core Skills: {', '.join(p['core_skills'])}",
        f"Certifications: {', '.join(p.get('certifications', []))}",
        f"Education: {p.get('education', '')}",
        f"Languages: {p.get('languages', '')}",
        f"Industry Preference: {p.get('industry', '')}",
        f"Deal Breakers: {'; '.join(p['deal_breakers'])}",
    ]
    return "\n".join(lines)


def _format_job(job: JobPosting, score: int, index: int) -> str:
    lines = [
        f"### Job {index}",
        f"- ID: {job.id}",
        f"- Title: {job.title}",
        f"- Company: {job.company}",
        f"- Location: {job.location}",
        f"- Source: {job.source}",
        f"- Stage 1 Score: {score}",
        f"- Remote Type: {job.remote_type or 'unknown'}",
        f"- Visa Sponsorship: {job.visa_sponsorship or 'unknown'}",
        f"- Description (first 3000 chars):",
        job.description[:3000],
        "---",
    ]
    return "\n".join(lines)


def _build_user_prompt(batch: list[tuple[JobPosting, int]]) -> str:
    parts = [
        "## Candidate Profile",
        _format_candidate_profile(),
        "",
        "## Jobs to Evaluate",
    ]
    for i, (job, score) in enumerate(batch, 1):
        parts.append(_format_job(job, score, i))
    parts.extend([
        "",
        "## Output Format",
        "Return a JSON array with one object per job, in the same order as input.",
        "Each object must have exactly these fields:",
        _OUTPUT_SCHEMA,
        "",
        _PRIORITY_RULES,
    ])
    return "\n".join(parts)


GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def _call_gemini(batch: list[tuple[JobPosting, int]], api_key: str) -> list[dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    user_prompt = _build_user_prompt(batch)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=_SYSTEM_PROMPT + "\n\n" + user_prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )

    raw = response.text
    result = json.loads(raw)

    if isinstance(result, dict) and "jobs" in result:
        result = result["jobs"]
    if not isinstance(result, list):
        raise ValueError(f"Expected JSON array, got {type(result).__name__}")

    return result


def _validate_enrichment(item: dict) -> dict:
    valid_priorities = {"high", "medium", "low", "skip"}
    valid_experience_fits = {"over_qualified", "good_fit", "stretch", "under_qualified"}
    valid_domain_relevance = {"core", "partial", "none"}
    valid_company_types = {"startup", "scale-up", "enterprise", "agency", "consulting", "unknown"}

    cleaned = {}
    cleaned["job_id"] = str(item.get("job_id", ""))

    priority = item.get("priority", "").lower()
    cleaned["priority"] = priority if priority in valid_priorities else "medium"

    cleaned["priority_reason"] = str(item.get("priority_reason", ""))[:500]
    cleaned["one_liner"] = str(item.get("one_liner", ""))[:300]

    exp_fit = item.get("experience_fit", "").lower()
    cleaned["experience_fit"] = exp_fit if exp_fit in valid_experience_fits else None

    years = item.get("experience_years_required")
    if years is not None:
        try:
            cleaned["experience_years_required"] = int(str(years).rstrip("+").strip())
        except (ValueError, TypeError):
            cleaned["experience_years_required"] = None
    else:
        cleaned["experience_years_required"] = None

    cleaned["location_reality"] = str(item.get("location_reality", ""))[:300]

    cleaned["industry"] = str(item.get("industry", ""))[:100]

    company_type = str(item.get("company_type", "unknown")).lower()
    cleaned["company_type"] = company_type if company_type in valid_company_types else "unknown"

    domain_rel = str(item.get("domain_relevance", "none")).lower()
    cleaned["domain_relevance"] = domain_rel if domain_rel in valid_domain_relevance else "none"

    cleaned["skills_match"] = str(item.get("skills_match", ""))[:500]

    flags = item.get("red_flags", [])
    if isinstance(flags, list):
        cleaned["red_flags"] = [str(f)[:200] for f in flags[:10]]
    else:
        cleaned["red_flags"] = []

    return cleaned


def evaluate_matches(matches: list[tuple[JobPosting, int]]) -> dict[str, dict]:
    if not matches:
        return {}

    if len(matches) > config.MAX_AI_MATCHES:
        logger.info("Capping AI evaluation from %d to %d matches", len(matches), config.MAX_AI_MATCHES)
        matches = matches[:config.MAX_AI_MATCHES]

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.info("No GEMINI_API_KEY set — skipping AI evaluation")
        return {}

    try:
        from google import genai  # noqa: F401
    except ImportError:
        logger.warning("google-genai not installed — skipping AI evaluation")
        return {}

    logger.info(
        "Starting AI evaluation with Gemini (model=%s) for %d jobs",
        GEMINI_MODEL, len(matches),
    )

    enrichments: dict[str, dict] = {}
    batch_size = 10
    batches = [matches[i:i + batch_size] for i in range(0, len(matches), batch_size)]

    for batch_num, batch in enumerate(batches, 1):
        if batch_num > 1:
            time.sleep(5)
        logger.info("Processing batch %d/%d (%d jobs)", batch_num, len(batches), len(batch))

        try:
            results = _call_gemini(batch, api_key)
            for item in results:
                cleaned = _validate_enrichment(item)
                if cleaned["job_id"]:
                    enrichments[cleaned["job_id"]] = cleaned
            logger.info("Batch %d: enriched %d jobs", batch_num, len(results))
        except json.JSONDecodeError as e:
            logger.error("Batch %d: JSON parse error — %s", batch_num, e)
        except Exception as e:
            is_quota = "429" in str(e) or "quota" in str(e).lower() or "limit" in str(e).lower()
            if is_quota:
                logger.warning("Batch %d: rate limited — waiting 60s", batch_num)
                time.sleep(60)
                try:
                    results = _call_gemini(batch, api_key)
                    for item in results:
                        cleaned = _validate_enrichment(item)
                        if cleaned["job_id"]:
                            enrichments[cleaned["job_id"]] = cleaned
                    logger.info("Batch %d: retry succeeded, enriched %d jobs", batch_num, len(results))
                except Exception as retry_err:
                    logger.error("Batch %d: retry failed — %s. Skipping remaining.", batch_num, retry_err)
                    break
            else:
                logger.exception("Batch %d: failed — skipping", batch_num)

    logger.info("AI evaluation complete: %d/%d jobs enriched", len(enrichments), len(matches))
    return enrichments


_COMPANY_SYSTEM_PROMPT = """You are a company intelligence analyst. You will receive a batch of companies
with sample job postings from each. For each company, produce a structured JSON assessment.

Rules:
- Return "unknown" for any field you are not confident about. Do NOT guess.
- visa_likelihood: "likely" only for large companies or those with known sponsorship track records.
  Default to "unknown" — never infer from company size alone.
- funding_stage: only state a specific stage if you are confident. Default "unknown".
- reasoning: explain your assessment briefly — if you can't explain why, return "unknown".
- Never fabricate information. When in doubt, "unknown" is always correct."""

_COMPANY_OUTPUT_SCHEMA = """{
  "company_key": "string — normalized company name from input",
  "canonical_name": "string — best display name",
  "funding_stage": "pre-seed|seed|series-a|series-b|series-c-plus|growth|public|bootstrapped|unknown",
  "employee_count_range": "1-10|11-50|51-200|201-1000|1001-5000|5000+|unknown",
  "industry_sector": "string",
  "tech_company": true,
  "reputation_signal": "positive|neutral|negative|unknown",
  "visa_likelihood": "likely|unlikely|unknown",
  "reasoning": "1-2 sentences explaining assessment"
}"""


def _build_company_prompt(companies: list[dict]) -> str:
    parts = [
        "## Companies to Evaluate",
        "",
    ]
    for i, company in enumerate(companies, 1):
        parts.append(f"### Company {i}")
        parts.append(f"- Key: {company['key']}")
        parts.append(f"- Name: {company['name']}")
        parts.append(f"- Sample jobs:")
        for sj in company.get("sample_jobs", []):
            parts.append(f"  - Title: {sj['title']}, Location: {sj['location']}")
            parts.append(f"    Description excerpt: {sj['description_excerpt']}")
        parts.append("---")

    parts.extend([
        "",
        "## Output Format",
        "Return a JSON array with one object per company, in the same order as input.",
        "Each object must have exactly these fields:",
        _COMPANY_OUTPUT_SCHEMA,
    ])
    return "\n".join(parts)


def _validate_company_enrichment(item: dict) -> dict:
    valid_funding = {"pre-seed", "seed", "series-a", "series-b", "series-c-plus", "growth", "public", "bootstrapped", "unknown"}
    valid_employee = {"1-10", "11-50", "51-200", "201-1000", "1001-5000", "5000+", "unknown"}
    valid_reputation = {"positive", "neutral", "negative", "unknown"}
    valid_visa = {"likely", "unlikely", "unknown"}

    cleaned = {}
    cleaned["company_key"] = str(item.get("company_key", ""))
    cleaned["canonical_name"] = str(item.get("canonical_name", ""))[:200]

    funding = str(item.get("funding_stage", "unknown")).lower()
    cleaned["funding_stage"] = funding if funding in valid_funding else "unknown"

    emp = str(item.get("employee_count_range", "unknown"))
    cleaned["employee_count_range"] = emp if emp in valid_employee else "unknown"

    cleaned["industry_sector"] = str(item.get("industry_sector", ""))[:100]
    cleaned["tech_company"] = bool(item.get("tech_company", False))

    rep = str(item.get("reputation_signal", "unknown")).lower()
    cleaned["reputation_signal"] = rep if rep in valid_reputation else "unknown"

    visa = str(item.get("visa_likelihood", "unknown")).lower()
    cleaned["visa_likelihood"] = visa if visa in valid_visa else "unknown"

    reasoning = str(item.get("reasoning", ""))
    if cleaned["funding_stage"] != "unknown" and not reasoning:
        cleaned["funding_stage"] = "unknown"
    cleaned["reasoning"] = reasoning[:500]

    return cleaned


def _call_company_gemini(batch: list[dict], api_key: str) -> list[dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    user_prompt = _build_company_prompt(batch)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=_COMPANY_SYSTEM_PROMPT + "\n\n" + user_prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    raw_results = json.loads(response.text)
    if isinstance(raw_results, dict):
        raw_results = raw_results.get("companies", list(raw_results.values()))
    if not isinstance(raw_results, list):
        raw_results = [raw_results]
    return raw_results


def evaluate_companies(companies: list[dict]) -> dict[str, dict]:
    if not companies:
        return {}

    if len(companies) > config.MAX_AI_COMPANIES:
        logger.info("Capping company enrichment from %d to %d", len(companies), config.MAX_AI_COMPANIES)
        companies = companies[:config.MAX_AI_COMPANIES]

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.info("No GEMINI_API_KEY set — skipping company enrichment")
        return {}

    try:
        from google import genai  # noqa: F401
    except ImportError:
        logger.warning("google-genai not installed — skipping company enrichment")
        return {}

    logger.info(
        "Starting company enrichment with Gemini for %d companies",
        len(companies),
    )

    results: dict[str, dict] = {}
    batch_size = 15
    batches = [companies[i:i + batch_size] for i in range(0, len(companies), batch_size)]

    for batch_num, batch in enumerate(batches, 1):
        if batch_num > 1:
            time.sleep(3)

        try:
            raw_results = _call_company_gemini(batch, api_key)
            for item in raw_results:
                cleaned = _validate_company_enrichment(item)
                key = cleaned["company_key"]
                if key:
                    results[key] = cleaned
            logger.info("Company batch %d/%d: enriched %d companies", batch_num, len(batches), len(raw_results))

        except Exception as e:
            logger.exception("Company enrichment batch %d failed", batch_num)

    logger.info("Company enrichment complete: %d/%d companies enriched", len(results), len(companies))
    return results
