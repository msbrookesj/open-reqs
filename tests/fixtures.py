"""Realistic mock data for jobs.apple.com responses.

The real site embeds JSON inside:
  __staticRouterHydrationData = JSON.parse("...");

These fixtures provide the inner data structures plus helpers to wrap them
into the HTML format that open_reqs parses.
"""
import json
from datetime import datetime, timedelta, timezone


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y")


def _days_ago_str(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%b %d, %Y")


# ── Search result jobs ────────────────────────────────────────────────────────

JOBS = [
    {
        "positionId": "REQ001",
        "postingTitle": "Software Engineer — Python Platform",
        "jobSummary": "Build scalable Python services for cloud infrastructure and APIs.",
        "team": {"teamName": "Cloud Engineering"},
        "locations": [{"name": "Cupertino"}],
        "postingDate": _today_str(),
    },
    {
        "positionId": "REQ002",
        "postingTitle": "iOS Software Engineer",
        "jobSummary": "Develop Swift applications for Apple platforms.",
        "team": {"teamName": "iOS Apps"},
        "locations": [{"name": "Sunnyvale"}],
        "postingDate": _today_str(),
    },
    {
        "positionId": "REQ003",
        "postingTitle": "Senior Hardware Engineer",
        "jobSummary": "Design electrical circuits for next-gen hardware products.",
        "team": {"teamName": "Hardware Technologies"},
        "locations": [{"name": "Cupertino"}],
        "postingDate": _days_ago_str(3),
    },
    {
        "positionId": "REQ004",
        "postingTitle": "Machine Learning Engineer",
        "jobSummary": "Apply machine learning and AI techniques to Siri and search.",
        "team": {"teamName": "AI/ML"},
        "locations": [{"name": "Cupertino"}],
        "postingDate": _days_ago_str(1),
    },
    {
        "positionId": "REQ005",
        "postingTitle": "Intern — Software Engineering",
        "jobSummary": "Summer internship on cloud services team.",
        "team": {"teamName": "Cloud Engineering"},
        "locations": [{"name": "Cupertino"}],
        "postingDate": _today_str(),
    },
    {
        "positionId": "REQ006",
        "postingTitle": "CoreOS Systems Engineer",
        "jobSummary": "Work on the kernel and operating system infrastructure.",
        "team": {"teamName": "CoreOS"},
        "locations": [{"name": "Cupertino"}],
        "postingDate": _days_ago_str(10),
    },
]


def make_search_data(jobs: list[dict] | None = None) -> dict:
    """Build the inner search data dict (what lives under loaderData.search)."""
    if jobs is None:
        jobs = JOBS
    return {
        "searchResults": jobs,
        "totalRecords": len(jobs),
    }


# ── Job detail pages ─────────────────────────────────────────────────────────

JOB_DETAILS = {
    "REQ001": {
        "postingTitle": "Software Engineer — Python Platform",
        "minimumQualifications": "<ul><li>2+ years of experience in software engineering</li>"
                                 "<li>Proficiency in Python and REST APIs</li></ul>",
        "preferredQualifications": "<ul><li>Experience with Flask or FastAPI</li>"
                                   "<li>Familiarity with SQL databases</li></ul>",
        "description": "<p>Join the Cloud Engineering team building scalable Python services.</p>",
        "responsibilities": "<p>Design and implement APIs for Apple cloud infrastructure.</p>",
    },
    "REQ002": {
        "postingTitle": "iOS Software Engineer",
        "minimumQualifications": "<ul><li>3+ years of experience with Swift</li>"
                                 "<li>Published iOS applications</li></ul>",
        "preferredQualifications": "<ul><li>Experience with SwiftUI</li></ul>",
        "description": "<p>Build beautiful, high-performance iOS applications.</p>",
        "responsibilities": "<p>Implement new features for flagship iOS apps.</p>",
    },
    "REQ003": {
        "postingTitle": "Senior Hardware Engineer",
        "minimumQualifications": "<ul><li>8+ years of experience in electrical engineering</li></ul>",
        "preferredQualifications": "<ul><li>ASIC design experience</li></ul>",
        "description": "<p>Design circuits for Apple's next generation of products.</p>",
        "responsibilities": "<p>Lead hardware design reviews.</p>",
    },
    "REQ004": {
        "postingTitle": "Machine Learning Engineer",
        "minimumQualifications": "<ul><li>1+ years of experience in ML or data science</li>"
                                 "<li>Python proficiency</li></ul>",
        "preferredQualifications": "<ul><li>Experience with PyTorch or TensorFlow</li></ul>",
        "description": "<p>Apply ML techniques to improve Apple products.</p>",
        "responsibilities": "<p>Train and deploy models at scale.</p>",
    },
    "REQ005": {
        "postingTitle": "Intern — Software Engineering",
        "minimumQualifications": "<ul><li>Currently enrolled in a CS degree program</li></ul>",
        "preferredQualifications": "<ul><li>Python or Swift experience</li></ul>",
        "description": "<p>12-week summer internship on cloud services.</p>",
        "responsibilities": "<p>Contribute to production services alongside full-time engineers.</p>",
    },
    "REQ006": {
        "postingTitle": "CoreOS Systems Engineer",
        "minimumQualifications": "<ul><li>3+ years in systems programming (C, C++)</li>"
                                 "<li>Experience with operating system internals</li></ul>",
        "preferredQualifications": "<ul><li>Kernel development experience</li></ul>",
        "description": "<p>Work on the lowest-level software that powers every Apple device.</p>",
        "responsibilities": "<p>Develop and maintain kernel extensions and system daemons.</p>",
    },
}


def make_detail_data(req_id: str) -> dict:
    """Build the inner detail data dict (loaderData.jobDetails.jobsData)."""
    return JOB_DETAILS.get(req_id, {})


# ── HTML wrappers ─────────────────────────────────────────────────────────────

def _escape_for_json_parse(data: dict) -> str:
    """Encode data as a JSON string, then escape it the way the real site does.

    The site serves:  JSON.parse("...escaped...")
    So we need to produce the inner escaped string.
    """
    raw_json = json.dumps(data)
    # The site escapes backslashes and double-quotes inside the JSON.parse("...") string
    escaped = raw_json.replace("\\", "\\\\").replace('"', '\\"')
    return escaped


def wrap_search_html(search_data: dict | None = None) -> str:
    """Wrap search data in a realistic HTML page with __staticRouterHydrationData."""
    if search_data is None:
        search_data = make_search_data()
    full = {"loaderData": {"search": search_data}}
    escaped = _escape_for_json_parse(full)
    return (
        '<!DOCTYPE html><html><head></head><body>'
        f'<script>__staticRouterHydrationData = JSON.parse("{escaped}");</script>'
        '</body></html>'
    )


def wrap_detail_html(req_id: str) -> str:
    """Wrap job detail data in a realistic HTML page."""
    detail = make_detail_data(req_id)
    full = {"loaderData": {"jobDetails": {"jobsData": detail}}}
    escaped = _escape_for_json_parse(full)
    return (
        '<!DOCTYPE html><html><head></head><body>'
        f'<script>__staticRouterHydrationData = JSON.parse("{escaped}");</script>'
        '</body></html>'
    )


# ── Test profile ──────────────────────────────────────────────────────────────

TEST_PROFILE = {
    "name": "Test User",
    "email": "test@example.com",
    "locations": ["SCV", "SVL"],
    "queries": ["software engineer", "CoreOS engineer"],
    "pages_per_query": 1,
    "boost_keywords": {
        "strong": ["Python", "Swift", "C"],
        "moderate": ["cloud", "infrastructure"],
        "light": ["machine learning", "AI"],
    },
    "penalty_keywords": {
        "hard": ["intern", "internship"],
        "soft": ["hardware", "firmware"],
    },
    "referrer_name": "Jane Doe",
    "referrer_phone": "+1 (408) 555-0100",
    "referrer_email": "jane@example.com",
    "referral_notes": "Test referral notes.",
}
