import hashlib
import logging
import re
import time
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)


@dataclass
class JobPosting:
    id: str
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str
    date_posted: str
    tags: list[str] = field(default_factory=list)
    salary: str = ""
    seniority: str = ""
    remote_type: str = ""
    job_type: str = ""
    visa_sponsorship: str = ""
    salary_min: float = 0
    salary_max: float = 0
    salary_currency: str = ""
    company_normalized: str = ""


_SENIORITY_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:head of|director)\b", "director"),
    (r"\bprincipal\b", "principal"),
    (r"\bstaff\b", "staff"),
    (r"\b(?:lead|architect)\b", "lead"),
    (r"\bsenior\b", "senior"),
    (r"\b(?:mid[- ]?level|intermediate)\b", "mid"),
    (r"\bjunior\b", "junior"),
]


def infer_seniority(title: str) -> str:
    t = title.lower()
    for pattern, level in _SENIORITY_PATTERNS:
        if re.search(pattern, t):
            return level
    return ""


_REMOTE_PATTERNS: list[tuple[str, str]] = [
    (r"\bfully[- ]?remote\b", "remote"),
    (r"\bremote[- ]?first\b", "remote"),
    (r"\b100%\s*remote\b", "remote"),
    (r"\bhybrid\b", "hybrid"),
    (r"\bon[- ]?site\b", "onsite"),
    (r"\bin[- ]?office\b", "onsite"),
    (r"\bremote\b", "remote"),
]


def infer_remote_type(location: str, description: str = "") -> str:
    for text in [location, description[:500]]:
        t = text.lower()
        for pattern, rtype in _REMOTE_PATTERNS:
            if re.search(pattern, t):
                return rtype
    return ""


_VISA_POSITIVE = [
    r"\bvisa\s+sponsor",
    r"\bsponsor\s+(?:a\s+)?(?:work\s+)?vis(?:a|as)\b",
    r"\bwork\s+visa\b",
    r"\bvisa\s+support\b",
    r"\brelocation\s+(?:package|assistance|support|bonus)\b",
    r"\b(?:provide|offer|assist|help|arrange)\s+(?:\w+\s+){0,2}work\s+permit",
    r"\bwork\s+permit\s+(?:sponsor|assistance|support|provided|available|included|arranged|obtained)",
    r"\bh[- ]?1[- ]?b\s+(?:transfer|sponsorship)(?:\s+\w+)?\s+(?:supported|available|provided|accepted)",
    r"\bopen\s+to\s+international\b",
    r"\bglobal\s+candidates?\s+(?:welcome|encouraged|invited)",
    r"\bsponsorship\s+(?:is\s+)?(?:provided|offered|available)\b",
    r"\bwe\s+(?:offer|provide)\s+(?:visa|sponsorship|relocation)",
]
_VISA_NEGATIVE = [
    r"\bno\s+(?:visa\s+)?sponsorship\b",
    r"\bcannot\s+sponsor\b",
    r"\bunable\s+to\s+(?:sponsor|(?:offer|provide)\s+(?:[\w/]+\s+){0,3}(?:visa\s+)?sponsorship)\b",
    r"\b(?:will|does|do)\s+not\s+(?:sponsor|(?:provide|offer)\s+(?:[\w/]+\s+){0,3}(?:sponsorship|work\s+authori[sz]ation))\b",
    r"\b(?:won'?t|doesn'?t|don'?t)\s+(?:sponsor|(?:provide|offer)\s+(?:[\w/]+\s+){0,3}(?:sponsorship|work\s+authori[sz]ation))\b",
    r"\bnot\s+(?:eligible|available)\s+for\s+(?:visa\s+)?(?:sponsorship|relocation)\b",
    r"\bnot\s+(?:offering|providing)\s+(?:visa\s+)?sponsorship\b",
    r"\bnot\s+sponsor\s+vis(?:a|as)\b",
    r"\bwithout\s+(?:the\s+)?need\s+for\s+(?:visa\s+)?sponsorship\b",
    r"\bwithout\s+(?:employer\s+)?sponsorship\b",
    r"\bsponsorship\s+(?:is\s+)?(?:not|n't)\s+(?:available|offered|provided|possible)\b",
    r"(?:visa|sponsorship|relocation)[\w\s/,]+(?:not|n't)\s+(?:available|offered|provided|possible)",
    r"\bmust\s+not\s+require\b.*?\bsponsorship\b",
    r"\bno\s+relocation\b",
    r"\brelocation\s+(?:is\s+)?(?:not|n't)\s+(?:available|offered|provided|possible|eligible)\b",
    r"\bmust\s+(?:have\s+(?:the\s+)?right\s+to\s+work|be\s+(?:legally\s+)?authorized)\b",
    r"\bwork\s+authorization\s+required\b",
    r"\b(?:legally\s+)?authori[sz]ed\s+to\s+work\s+in\b",
    r"\bmust\s+be\s+authorized\s+to\s+work.*?without\s+(?:employer\s+)?sponsorship",
    r"\b(?:must|need\s+to|required\s+to)\s+(?:[\w/]+\s+){0,4}(?:hold|own|have|possess)\s+(?:a\s+)?(?:valid\s+)?(?:work\s+)?(?:permit|visa|authorization)\b",
    r"\bright\s+to\s+work\s+in\b",
    r"\bwork\s+permit\s+(?:restrict|holders?|required)",
    r"\bcan\s+only\s+consider\b",
    r"\b(?:eu|eea|swiss|schengen)\s+(?:citizen|national|resident|passport)",
    r"\b(?:citizen|national)s?\s+(?:of\s+)?(?:the\s+)?(?:eu|eea|switzerland)\b",
    r"\bmust\s+be\s+a\s+[\w/]+\s+citizen\b",
    r"\bcitizens?\s+and\s+permanent\s+residents?\s+only\b",
    r"\bpermanent\s+residen(?:t|ce|cy)\s+(?:required|needed|is\s+required)\b",
    r"\bgreen\s+card\s+(?:required|holders?\s+only|needed)\b",
    r"\bsecurity\s+clearance\b", r"\bsicherheitsüberprüfung\b",
    r"\b(?:active\s+)?(?:ts[/-]?sci|top\s+secret)\s+(?:clearance|required)",
    r"\bclearance\s+(?:is\s+)?required\b",
    r"\beu[- ]?paspoort\b", r"\bwerkvergunning\b",
    r"\beu[- ]?bürger\b", r"\barbeitserlaubnis\b", r"\baufenthaltserlaubnis\b", r"\barbeitsgenehmigung\b",
]


def _split_sentences(text: str) -> list[tuple[int, int]]:
    spans = []
    for m in re.finditer(r'[^.!?\n]+(?:[.!?]+|\n|$)', text):
        s, e = m.start(), m.end()
        if e - s > 5:
            spans.append((s, e))
    return spans or [(0, len(text))]


def infer_visa(description: str) -> str:
    d = description.lower()

    neg_positions = []
    for pattern in _VISA_NEGATIVE:
        m = re.search(pattern, d)
        if m:
            neg_positions.append(m.start())

    pos_positions = []
    for pattern in _VISA_POSITIVE:
        m = re.search(pattern, d)
        if m:
            pos_positions.append(m.start())

    if not neg_positions and not pos_positions:
        return ""
    if pos_positions and not neg_positions:
        return "yes"
    if neg_positions and not pos_positions:
        return "no"

    sentences = _split_sentences(d)

    def _sentence_idx(pos: int) -> int:
        for i, (s, e) in enumerate(sentences):
            if s <= pos < e:
                return i
        return len(sentences) - 1

    neg_sentences = {_sentence_idx(p) for p in neg_positions}
    pos_sentences = {_sentence_idx(p) for p in pos_positions}

    if pos_sentences - neg_sentences:
        return "mixed"
    return "no"


_JOB_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"\bcontract\b", "contract"),
    (r"\bfreelance\b", "freelance"),
    (r"\bpart[- ]?time\b", "part-time"),
    (r"\bfull[- ]?time\b", "full-time"),
    (r"\bpermanent\b", "full-time"),
]


def infer_job_type(text: str) -> str:
    t = text.lower()
    for pattern, jtype in _JOB_TYPE_PATTERNS:
        if re.search(pattern, t):
            return jtype
    return ""


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.md5(value.encode()).hexdigest()[:12]}"


_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def get_with_retry(url: str, retries: int = 3, backoff: float = 2.0, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 30)
    for attempt in range(retries):
        try:
            resp = requests.get(url, **kwargs)
            if resp.status_code in _RETRYABLE_STATUSES and attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                logger.warning("%s returned %d (attempt %d/%d) — retrying in %.0fs", url, resp.status_code, attempt + 1, retries, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.ConnectionError as e:
            if attempt == retries - 1:
                raise
            wait = backoff * (2 ** attempt)
            logger.warning("%s failed (attempt %d/%d): %s — retrying in %.0fs", url, attempt + 1, retries, e, wait)
            time.sleep(wait)
        except requests.RequestException:
            raise


_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize_id(raw_id: str) -> str:
    return _SAFE_ID_RE.sub("_", raw_id)[:128]


def _sanitize_url(url: str) -> str:
    if url and not url.startswith(("http://", "https://")):
        return ""
    return url


def enrich(job: JobPosting) -> JobPosting:
    from company import extract_salary_from_company, normalize_company_name

    job.id = _sanitize_id(job.id)
    job.url = _sanitize_url(job.url)
    if not job.seniority:
        job.seniority = infer_seniority(job.title)
    if not job.remote_type:
        job.remote_type = infer_remote_type(job.location, job.description)
    if not job.visa_sponsorship:
        job.visa_sponsorship = infer_visa(job.description)
    if not job.job_type:
        combined = " ".join(job.tags) + " " + job.description[:500]
        job.job_type = infer_job_type(combined)
    if not job.salary_min and not job.salary_max and job.company:
        sal_min, sal_max = extract_salary_from_company(job.company)
        if sal_min is not None:
            job.salary_min = sal_min
        if sal_max is not None:
            job.salary_max = sal_max
    if job.company:
        job.company_normalized = normalize_company_name(job.company)
    return job
