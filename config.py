import os
import re

# ============================================================
# Role profile system
# ============================================================
# Default: customer_success. Override via ROLE_PROFILE env var.
# Profiles only swap SEARCH_QUERIES and SKILL_KEYWORDS.
# Roles don't coexist — one active at a time.

_PROFILES = {
    "customer_success": {
        "search_queries": [
            "Customer Success Manager",
            "Client Success Manager",
            "Customer Service Manager",
            "Customer Relationship Manager",
            "Client Relationship Manager",
            "Customer Experience Manager",
            "Customer Engagement Manager",
            "Customer Retention Manager",
            "Customer Advocacy Manager",
            "Customer Support Manager",
            "Client Services Manager",
            "Account Success Manager",
            "Service Delivery Manager",
            "Customer Operations Manager",
            "Customer Success Specialist",
            "Customer Success Lead",
            "Head of Customer Success",
            "Client Success Consultant",
            "Customer Care Manager",
            "Onboarding Manager",
            "Renewal Manager",
            "Implementation Manager",
        ],
        "adzuna_queries": [
            "title:(customer success manager OR client success manager OR customer experience manager)",
            "title:(customer service manager OR client services manager OR customer support manager)",
            "title:(customer relationship manager OR client relationship manager OR account success manager)",
            "title:(service delivery manager OR customer engagement manager OR customer retention manager)",
            "title:(customer operations manager OR customer care manager OR onboarding manager)",
        ],
        "jsearch_queries": [
            "Customer Success Manager",
            "Client Success Manager",
            "Customer Service Manager",
            "Customer Relationship Manager",
            "Customer Experience Manager",
            "Customer Support Manager",
            "Service Delivery Manager",
            "Account Success Manager",
        ],
        "skill_keywords": {
            # Core (10) — role-defining terms + primary tools
            "customer success": 10,
            "client success": 10,
            "customer relationship": 10,
            "client relationship": 10,
            "customer retention": 10,
            "client retention": 10,
            "customer engagement": 10,
            "customer advocacy": 10,
            "customer satisfaction": 10,
            "customer experience": 10,
            "service delivery": 10,
            "account management": 10,
            "key account": 10,
            "strategic account": 10,
            "client management": 10,
            "relationship management": 10,
            "stakeholder management": 10,
            "crm": 10,
            "salesforce": 10,
            "hubspot": 10,
            "zoho": 10,
            "zendesk": 10,
            "sap": 10,
            "microsoft dynamics": 10,
            "power bi": 10,
            "tableau": 10,
            "business development": 10,
            "upselling": 10,
            "cross-selling": 10,
            "revenue growth": 10,
            # Important (6) — supporting tools and skills
            "excel": 6,
            "microsoft excel": 6,
            "google sheets": 6,
            "sql": 6,
            "jira": 6,
            "asana": 6,
            "trello": 6,
            "powerpoint": 6,
            "data analysis": 6,
            "reporting": 6,
            "dashboards": 6,
            "metrics": 6,
            "kpi": 6,
            "analytics": 6,
            "business intelligence": 6,
            "negotiation": 6,
            "problem solving": 6,
            "communication": 6,
            "leadership": 6,
            "cross-functional": 6,
            "project management": 6,
            "process improvement": 6,
            "onboarding": 6,
            "implementation": 6,
            "training": 6,
            "customer support": 6,
            "troubleshooting": 6,
            "customer feedback": 6,
            "nps": 6,
            "net promoter score": 6,
            "churn reduction": 6,
            "renewal": 6,
            "contract negotiation": 6,
            "order management": 6,
            "order processing": 6,
            # Nice-to-have (3) — bonus signals
            "python": 3,
            "api": 3,
            "automation": 3,
            "intercom": 3,
            "drift": 3,
            "saas": 3,
            "software as a service": 3,
            "b2b": 3,
            "enterprise": 3,
            "fintech": 3,
            "healthtech": 3,
            "edtech": 3,
            "agile": 3,
            "scrum": 3,
            "remote collaboration": 3,
            "erp": 3,
            "freshworks": 3,
            "pipedrive": 3,
            "monday.com": 3,
            "notion": 3,
            "slack": 3,
        },
    },
    "business_development": {
        "search_queries": [
            "Business Development Manager",
            "Business Development Executive",
            "Business Development Specialist",
            "Sales Manager",
            "Account Manager",
            "Key Account Manager",
            "Strategic Partnerships Manager",
            "Partnerships Manager",
            "Growth Manager",
            "Business Growth Manager",
            "Sales Executive",
            "Client Acquisition Manager",
        ],
        "adzuna_queries": [
            "title:(business development manager OR business development executive)",
            "title:(sales manager OR account manager OR key account manager)",
            "title:(partnerships manager OR growth manager OR client acquisition)",
        ],
        "jsearch_queries": [
            "Business Development Manager",
            "Business Development Executive",
            "Sales Manager",
            "Account Manager",
            "Partnerships Manager",
            "Growth Manager",
        ],
        "skill_keywords": {
            "business development": 10,
            "client acquisition": 10,
            "lead generation": 10,
            "strategic partnerships": 10,
            "sales strategy": 10,
            "pipeline management": 10,
            "revenue growth": 10,
            "market analysis": 10,
            "negotiation": 10,
            "account management": 10,
            "crm": 10,
            "salesforce": 10,
            "hubspot": 10,
            "sap": 10,
            "stakeholder management": 10,
            "cold calling": 6,
            "outbound": 6,
            "inbound": 6,
            "proposal writing": 6,
            "contract negotiation": 6,
            "market research": 6,
            "competitive analysis": 6,
            "cross-selling": 6,
            "upselling": 6,
            "presentation": 6,
            "communication": 6,
            "leadership": 6,
            "project management": 6,
            "excel": 6,
            "sql": 6,
            "power bi": 6,
            "data analysis": 6,
            "reporting": 6,
            "b2b": 3,
            "b2c": 3,
            "saas": 3,
            "enterprise": 3,
            "fintech": 3,
            "e-commerce": 3,
        },
    },
    "data_analyst": {
        "search_queries": [
            "Data Analyst",
            "Business Analyst",
            "Business Intelligence Analyst",
            "BI Analyst",
            "Reporting Analyst",
            "Insights Analyst",
            "Operations Analyst",
            "Data Specialist",
            "Analytics Specialist",
            "Data Associate",
        ],
        "adzuna_queries": [
            "title:(data analyst OR business analyst OR bi analyst)",
            "title:(reporting analyst OR business intelligence analyst OR insights analyst)",
        ],
        "jsearch_queries": [
            "Data Analyst",
            "Business Analyst",
            "Business Intelligence Analyst",
            "Reporting Analyst",
            "Insights Analyst",
        ],
        "skill_keywords": {
            "power bi": 10,
            "sql": 10,
            "data visualization": 10,
            "data analysis": 10,
            "business intelligence": 10,
            "tableau": 10,
            "reporting": 10,
            "dashboards": 10,
            "excel": 10,
            "analytics": 10,
            "kpi": 10,
            "metrics": 10,
            "sap": 10,
            "data modelling": 6,
            "data mining": 6,
            "statistical analysis": 6,
            "etl": 6,
            "data warehousing": 6,
            "google analytics": 6,
            "looker": 6,
            "data studio": 6,
            "python": 6,
            "r": 6,
            "presentation": 6,
            "stakeholder management": 6,
            "process improvement": 6,
            "crm": 6,
            "salesforce": 6,
            "communication": 6,
            "problem solving": 6,
            "jira": 3,
            "confluence": 3,
            "agile": 3,
            "saas": 3,
            "b2b": 3,
        },
    },
}

# --- Active profile (set by activate_profile()) ---

SEARCH_QUERIES = _PROFILES["customer_success"]["search_queries"]
ADZUNA_QUERIES = _PROFILES["customer_success"]["adzuna_queries"]
JSEARCH_QUERIES = _PROFILES["customer_success"]["jsearch_queries"]
SKILL_KEYWORDS = _PROFILES["customer_success"]["skill_keywords"]
ACTIVE_PROFILE = "customer_success"


def activate_profile(name: str) -> None:
    global SEARCH_QUERIES, ADZUNA_QUERIES, JSEARCH_QUERIES, SKILL_KEYWORDS, ACTIVE_PROFILE
    profile = _PROFILES.get(name)
    if not profile:
        raise ValueError(f"Unknown profile: {name!r}. Choose from: {list(_PROFILES)}")
    SEARCH_QUERIES = profile["search_queries"]
    ADZUNA_QUERIES = profile["adzuna_queries"]
    JSEARCH_QUERIES = profile["jsearch_queries"]
    SKILL_KEYWORDS = profile["skill_keywords"]
    ACTIVE_PROFILE = name


# ============================================================
# Title skip filter (negative filter — match → score 0)
# ============================================================

# Regex patterns, matched against the lowercased title. A single hit scores the
# job 0. These are deliberately broad: none of Sayema's target titles contain
# "engineer", "developer", "qa", "quality", "test", or "technical" — so skipping
# on those tokens costs nothing and catches the endless real-world variants
# ("Senior Specialist QA", "Software QA Specialist", "Data Quality Engineer")
# that an exact-phrase list always misses.
# Testing/QA tokens are never rescued. A "Service Delivery QE/QA Banking Leader"
# is a QA role wearing a service-delivery label, and Sayema is not applying to
# it no matter which target phrase also appears in the title.
TITLE_HARD_SKIP_PATTERNS = [
    r"\bq\.?a\.?\b",
    r"\bq\.?e\.?\b",
    r"\bquality\b",
    r"\btest(er|ing|s)?\b",
    r"\bsdet\b",
    r"\bautomation\b",
]

TITLE_SKIP_PATTERNS = [
    # --- Software engineering (any form) ---
    r"\bengineer(ing|s)?\b",
    r"\bdevelope?r?s?\b",
    r"\bprogrammer\b",
    r"\bcoder\b",
    r"\bdev\s?ops\b",
    r"\bsre\b",
    r"\bsite reliability\b",
    r"\bfull[\s-]?stack\b",
    r"\bfront[\s-]?end\b",
    r"\bback[\s-]?end\b",
    r"\bsys\s?admin\b",
    r"\bsystem admin",
    r"\barchitect\b",
    r"\bprogramme?r\b",
    r"\bsoftware\b",
    r"\bweb\s?master\b",
    # --- Data science / ML (Data Analyst is a target role — not skipped) ---
    r"\bdata scien(ce|tist)",
    r"\bmachine learning\b",
    r"\bdeep learning\b",
    r"\b(ml|nlp)\b",
    r"\bcomputer vision\b",
    r"\bdata engineer",
    r"\betl\b",
    # --- Design ---
    r"\b(ux|ui)\b",
    r"\bdesigner\b",
    r"\buser experience\b",
    # --- Content / Marketing ---
    r"\bcopywriter\b",
    r"\bcontent (writer|strategist|specialist)\b",
    r"\bseo\b",
    r"\bsocial media\b",
    # --- HR / Admin ---
    r"\b(hr|human resources)\b",
    r"\brecruit(er|ment)\b",
    r"\btalent acquisition\b",
    r"\b(administrative|executive|personal) assistant\b",
    r"\breceptionist\b",
    r"\boffice manager\b",
    # --- Finance / Accounting ---
    r"\baccount(ant|ing)\b",
    r"\bbookkeep",
    r"\bfinancial analyst\b",
    r"\bauditor?\b",
    r"\bpayroll\b",
    r"\btax analyst\b",
    # --- Healthcare ---
    r"\bnurse\b", r"\bdoctor\b", r"\bphysician\b", r"\bpharmacist\b",
    r"\bdentist\b", r"\bveterinarian\b", r"\bclinical\b",
    # --- Legal ---
    r"\blawyer\b", r"\battorney\b", r"\bparalegal\b", r"\blegal counsel\b",
    # --- Education ---
    r"\bteacher\b", r"\bprofessor\b", r"\blecturer\b", r"\binstructor\b",
    # --- Non-software engineering / sciences / industrial ---
    r"\bquantity surveyor\b",
    r"\bchemist\b", r"\bbiologist\b", r"\bphysicist\b",
    r"\blab(oratory)?\s?(technician)?\b",
    r"\breagent",
    r"\bproduction\b",
    r"\bmanufacturing\b",
    r"\bmaintenance\b",
    # --- Trades / manual ---
    r"\bwarehouse\b", r"\bforklift\b", r"\bdriver\b", r"\bcourier\b",
    r"\bplumber\b", r"\belectrician\b", r"\bcarpenter\b", r"\bwelder\b",
    r"\btechnician\b",
]

TITLE_HARD_SKIP_RE = [re.compile(p) for p in TITLE_HARD_SKIP_PATTERNS]
TITLE_SKIP_RE = [re.compile(p) for p in TITLE_SKIP_PATTERNS]

# Titles that are unambiguously hers keep their place even when they collide
# with a skip token — "Customer Success Engineer" and "Technical Account
# Manager" are real SaaS roles, not engineering ones.
TITLE_RESCUE_PATTERNS = [
    r"\bcustomer success\b",
    r"\bclient success\b",
    r"\bcustomer experience\b",
    r"\bcustomer relationship\b",
    r"\bclient relationship\b",
    r"\baccount manage(r|ment)\b",
    r"\bservice delivery\b",
    r"\bclient services?\b",
]

TITLE_RESCUE_RE = [re.compile(p) for p in TITLE_RESCUE_PATTERNS]

# ============================================================
# Scoring settings
# ============================================================

SKILLS_CAP = 70
SKILLS_MIN = 6

# A job must show real domain signal, not just generic corporate vocabulary.
# CORE keywords are the weight-10 entries in the active profile (customer
# success, account management, CRM/SAP/Power BI). Without at least one, the job
# scores 0 no matter how many "communication / leadership / agile" hits it has.
CORE_SKILL_WEIGHT = 10
CORE_SKILL_MIN = 10

# Tier-2/3 keywords are supporting evidence, not the main signal. Capping their
# combined contribution stops a job from reaching SKILLS_CAP on filler alone.
GENERIC_SKILLS_CAP = 24

MAX_SCORE = 100

SHORT_DESC_THRESHOLD = 100
SHORT_DESC_PENALTY = -10

MIN_SALARY = 40000

# ============================================================
# Location scoring — Relocation > Remote > Dhaka
# ============================================================

LOCATION_SCORES = {
    # Tier 1 (20): Relocation destinations
    "united kingdom": 20,
    "uk": 20,
    "london": 20,
    "manchester": 20,
    "birmingham": 20,
    "canada": 20,
    "toronto": 20,
    "vancouver": 20,
    "montreal": 20,
    "australia": 20,
    "sydney": 20,
    "melbourne": 20,
    "brisbane": 20,
    "germany": 20,
    "berlin": 20,
    "munich": 20,
    "münchen": 20,
    "hamburg": 20,
    "frankfurt": 20,
    "netherlands": 20,
    "amsterdam": 20,
    "rotterdam": 20,
    "singapore": 20,
    "uae": 20,
    "united arab emirates": 20,
    "dubai": 20,
    "abu dhabi": 20,
    "qatar": 20,
    "doha": 20,
    "ireland": 20,
    "dublin": 20,
    "sweden": 20,
    "stockholm": 20,
    "denmark": 20,
    "copenhagen": 20,
    "norway": 20,
    "oslo": 20,
    "finland": 20,
    "helsinki": 20,
    "switzerland": 20,
    "zurich": 20,
    "zürich": 20,
    "new zealand": 20,
    "auckland": 20,
    "saudi arabia": 20,
    "saudi": 20,
    "riyadh": 20,
    "jeddah": 20,
    # Tier 2 (17): Remote — any country
    "remote": 17,
    "worldwide": 17,
    "anywhere": 17,
    "global": 17,
    "work from home": 17,
    "wfh": 17,
    # Tier 3 (14): Dhaka — home base
    "dhaka": 14,
    "bangladesh": 14,
    "chittagong": 14,
    # Tier 4 (12): Other international
    "united states": 12,
    "usa": 12,
    "new york": 12,
    "san francisco": 12,
    "malaysia": 12,
    "kuala lumpur": 12,
    "france": 12,
    "paris": 12,
    "spain": 12,
    "madrid": 12,
    "barcelona": 12,
    "japan": 12,
    "tokyo": 12,
    "south korea": 12,
    "seoul": 12,
    "italy": 12,
    "austria": 12,
    "vienna": 12,
    "belgium": 12,
    "brussels": 12,
    "portugal": 12,
    "lisbon": 12,
    "poland": 12,
    "warsaw": 12,
    "czech": 12,
    "prague": 12,
    # Tier 5 (8): Broad regions
    "europe": 8,
    "north america": 8,
    "apac": 8,
    "asia pacific": 8,
    "middle east": 8,
    # Tier 6 (5): Regional / low priority
    "india": 5,
    "pakistan": 5,
    "sri lanka": 5,
    "nepal": 5,
}

# ============================================================
# Visa / relocation scoring
# ============================================================

VISA_POSITIVE = {
    "visa sponsorship": 20,
    "work permit": 20,
    "relocation package": 20,
    "relocation assistance": 20,
    "relocation support": 20,
    "work visa": 20,
    "visa support": 20,
    "will sponsor": 20,
    "can sponsor": 20,
    "sponsorship provided": 20,
    "sponsorship available": 20,
    "global talent": 20,
    "skilled worker visa": 20,
}

VISA_NEGATIVE = {
    "no sponsorship": -15,
    "no visa": -15,
    "must have right to work": -15,
    "must be authorized": -15,
    "work authorization required": -15,
    "cannot sponsor": -15,
    "unable to sponsor": -15,
    "must be citizen": -15,
    "citizens only": -15,
    "green card required": -15,
}

VISA_UNKNOWN_ONSITE_PENALTY = -8

GEO_RESTRICTED_REMOTE = [
    "us only", "u.s. only", "united states only",
    "us citizens only", "u.s. citizens only",
    "us-based only", "us based only",
    "canada only", "uk only",
    "must reside in the us", "must reside in the eu",
    "must reside in the uk", "must be located in",
    "us work authorization required",
    "eu work authorization", "eu residency",
    "domestic candidates only",
    "local candidates only",
]
GEO_RESTRICTED_PENALTY = -15

# ============================================================
# Source scheduling
# ============================================================

# Landing.jobs, Wellfound, RemoteOK and Relocate.me were dropped: they are tech
# hiring boards with no customer-success inventory. Their adapters remain in
# sources/ and can be restored by adding the name back to a tier here.
SOURCE_TIERS = {
    "daily": ["LinkedIn", "Adzuna", "JSearch", "Arbeitnow"],
    "A": ["Jobicy", "Remotive"],
    "B": ["Himalayas", "WWR", "Remote.co"],
}

TIER_SCHEDULE = {
    0: ["daily", "A"],
    1: ["daily", "B"],
    2: ["daily", "A"],
    3: ["daily", "B"],
    4: ["daily", "A"],
    5: ["daily", "B"],
    6: ["daily"],
}

LINKEDIN_LOCATIONS_GROUP1 = [
    "Bangladesh", "United Kingdom", "Remote", "Worldwide",
    "United Arab Emirates", "Singapore",
]

LINKEDIN_LOCATIONS_GROUP2 = [
    "United States", "Canada", "Australia",
    "Germany", "Netherlands", "Ireland",
]

LINKEDIN_LOCATIONS_GROUP3 = [
    "Malaysia", "France", "Sweden", "Denmark",
    "Norway", "Finland", "Switzerland", "Austria",
    "Japan", "South Korea", "New Zealand",
    "Qatar", "Saudi Arabia", "Spain", "Italy",
]

LINKEDIN_LOCATION_SCHEDULE = {
    0: LINKEDIN_LOCATIONS_GROUP1,
    1: LINKEDIN_LOCATIONS_GROUP2,
    2: LINKEDIN_LOCATIONS_GROUP3,
    3: LINKEDIN_LOCATIONS_GROUP1,
    4: LINKEDIN_LOCATIONS_GROUP2,
    5: LINKEDIN_LOCATIONS_GROUP3,
    6: [],
}

ADZUNA_COUNTRIES = [
    "gb", "ca", "au", "us", "de", "nl", "sg",
    "ae", "ie", "my", "fr", "es", "it", "se", "ch",
]

MAX_DAYS_OLD = 30

# ============================================================
# Thresholds
# ============================================================

MAX_AI_MATCHES = 50
MAX_AI_COMPANIES = 30

ENRICHMENT_THRESHOLD = 20
ALERT_THRESHOLD = 25
HIGH_MATCH_THRESHOLD = 55
MEDIUM_MATCH_THRESHOLD = 40

# ============================================================
# Company enrichment scoring
# ============================================================

COMPANY_VISA_LIKELY_PENALTY = -3
COMPANY_LARGE_FUNDED_PENALTY = -5
COMPANY_REPUTATION_POSITIVE = 3
COMPANY_REPUTATION_NEGATIVE = -5
COMPANY_BONUS_CAP = 8
COMPANY_BONUS_FLOOR = -5

# ============================================================
# Candidate profile (for AI evaluator)
# ============================================================

CANDIDATE_PROFILE = {
    "current_role": "Executive - Customer Service",
    "target_role": "Customer Success Manager / Customer Service Manager",
    "years_experience": 5,
    "min_acceptable_experience": 2,
    "seniority_preference": {
        "customer_success": "mid+",
        "data_analytics": "junior+",
        "business_development": "mid+",
    },
    "location": "Dhaka, Bangladesh",
    "target_locations": [
        "Any country with visa sponsorship (priority)",
        "Remote (priority)",
        "Bangladesh (fallback)",
    ],
    "visa_status": "Requires sponsorship for international roles",
    "core_skills": [
        "customer relationship management", "SAP", "Power BI",
        "Excel", "SQL", "CRM systems", "order management",
        "stakeholder management", "team training",
    ],
    "certifications": [
        "Google Data Analytics Professional Certificate",
        "Business Analytics with Excel (Coursera)",
        "Google Project Management (in progress)",
        "SAP Professional Fundamentals (in progress)",
    ],
    "education": "MBA in MIS (Dhaka University), BSc Software Engineering (AIUB)",
    "languages": "English (Professional, IELTS 6.5), Bengali (Native)",
    "industry": "Open to any industry if role and pay match",
    "deal_breakers": [
        "Roles requiring 10+ years experience",
        "C-level / VP roles",
        "Highly technical engineering roles (software dev, DevOps, ML)",
        "Minimum salary below 40K USD/GBP/EUR equivalent",
    ],
}
