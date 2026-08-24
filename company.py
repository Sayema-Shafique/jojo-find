import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_SALARY_BRACKET_RE = re.compile(
    r'\s*\[([\d\s.,]+)\s*[-–]\s*([\d\s.,]+)\s*(?:EUR|USD|GBP)?\s*\]\s*$',
    re.IGNORECASE,
)

_NOISE_SUFFIXES_RE = re.compile(
    r'\s*\((?:Production|Pvt|Private)\)\s*$',
    re.IGNORECASE,
)

_LEGAL_SUFFIXES = [
    "& co. kg", "& co.kg", "gmbh & co. kg", "gmbh & co.kg",
    "gmbh", "ag", "se", "e.v.", "kg", "ohg", "ug",
    "ltd.", "ltd", "limited", "plc", "llp",
    "inc.", "inc", "llc", "corp.", "corp", "corporation",
    "b.v.", "bv", "n.v.", "nv",
    "s.a.", "sa", "s.r.l.", "srl", "s.p.a.", "spa",
    "pty ltd", "pty. ltd.",
    "co.", "company",
]

_LEGAL_SUFFIX_RE = re.compile(
    r'\s+(?:' + '|'.join(re.escape(s) for s in sorted(_LEGAL_SUFFIXES, key=len, reverse=True)) + r')\s*$',
    re.IGNORECASE,
)

_ALIAS_FILE = os.path.join(os.path.dirname(__file__), "data", "company_aliases.json")

_aliases: dict[str, str] | None = None


def _load_aliases() -> dict[str, str]:
    global _aliases
    if _aliases is not None:
        return _aliases
    try:
        with open(_ALIAS_FILE) as f:
            _aliases = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _aliases = {}
    return _aliases


def _parse_salary_number(s: str) -> float:
    s = s.strip().replace(" ", "")
    if "." in s and "," in s:
        if s.index(",") > s.index("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            s = s.replace(".", "")
        # else: treat as decimal point (e.g., "45.5")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    return float(s)


def extract_salary_from_company(raw: str) -> tuple[float | None, float | None]:
    m = _SALARY_BRACKET_RE.search(raw)
    if not m:
        return None, None
    try:
        sal_min = _parse_salary_number(m.group(1))
        sal_max = _parse_salary_number(m.group(2))
        return sal_min, sal_max
    except (ValueError, IndexError):
        return None, None


def normalize_company_name(raw: str) -> str:
    name = _SALARY_BRACKET_RE.sub("", raw)
    name = _NOISE_SUFFIXES_RE.sub("", name)
    name = re.sub(r'\s+', ' ', name).strip()
    key = name.lower()
    key = _LEGAL_SUFFIX_RE.sub("", key).strip()

    aliases = _load_aliases()
    if key in aliases:
        key = aliases[key]

    return key
