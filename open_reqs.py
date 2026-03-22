#!/usr/bin/env python3
"""
Search open job listings.

Queries the jobs.apple.com API directly and displays matching roles
with Req IDs, titles, teams, and direct links.

Usage:
    # Search with default keywords and locations
    python open_reqs.py

    # Search for a specific role
    python open_reqs.py --query "backend software engineer"

    # Search in a specific location
    python open_reqs.py --query "iOS engineer" --location SVL

    # Show more results
    python open_reqs.py --query "data analyst" --limit 50

    # Output as JSON for scripting
    python open_reqs.py --query "python engineer" --json

    # Run the web UI with built-in proxy server
    python open_reqs.py --serve

    # Run candidate-profile search (multi-query, scored, deduplicated)
    python open_reqs.py --candidate
    python open_reqs.py --candidate --json

    # Email results as a rich HTML digest
    python open_reqs.py --candidate --email user@example.com
"""

import argparse
import json
import math
import os
import re
import smtplib
import ssl
import sys
import textwrap
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).parent

DEFAULT_BASE_URL = "https://jobs.apple.com"

# Allow unverified SSL for corporate proxy environments that intercept HTTPS
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _base_url() -> str:
    """Return the jobs site base URL, preferring the loaded candidate profile."""
    return CANDIDATE_PROFILE.get("base_url", DEFAULT_BASE_URL)

LOCATIONS = {
    "SCV": {"label": "Santa Clara Valley / Cupertino", "slug": "santa-clara-valley-cupertino-SCV"},
    "SVL": {"label": "Sunnyvale", "slug": "sunnyvale-SVL"},
    "SJOS": {"label": "Campbell / San Jose", "slug": "campbell-san-jose-SJOS"},
    "USA": {"label": "All US", "slug": "united-states-USA"},
    "AUS": {"label": "Austin", "slug": "austin-AUS"},
    "SEA": {"label": "Seattle", "slug": "seattle-SEA"},
    "NYC": {"label": "New York City", "slug": "new-york-city-NYC"},
    "SDG": {"label": "San Diego", "slug": "san-diego-SDG"},
    "CUL": {"label": "Culver City", "slug": "culver-city-CUL"},
    "IRV": {"label": "Irvine", "slug": "irvine-IRV"},
}

DEFAULT_LOCATIONS = ["SCV", "SVL"]
DEFAULT_QUERY = "early career software engineer"

def _load_candidate_profile(path: str | Path | None = None) -> dict:
    """Load candidate profile from a YAML file."""
    profile_path = Path(path) if path else SCRIPT_DIR / "candidate_profile.yaml"
    with open(profile_path) as f:
        return yaml.safe_load(f)


CANDIDATE_PROFILE = _load_candidate_profile()


def score_job(job: dict) -> int:
    """Score a job's relevance to the candidate profile (higher = better fit).

    Uses tiered keyword weights based on verified skills:
      - Strong boost (+20): confirmed in public repos (Python, C++, Flask, APIs)
      - Moderate boost (+12): coursework or resume-listed (Java, Swift, SQL)
      - Light boost (+6): adjacent/aspirational (early career, AI keywords)
      - Hard penalty: if keyword appears in job *title* → score 0 (eliminated);
        if in team/summary → -30/-15 point deduction
      - Soft penalty (-15/-8): likely mismatches (hardware, firmware, embedded)
    """
    title = (job.get("postingTitle") or job.get("title") or "").lower()
    team = ((job.get("team") or {}).get("teamName") or "").lower()
    summary = (job.get("jobSummary") or "").lower()

    # Title+team carry full weight; summary carries half (it's noisy)
    primary = f"{title} {team}"
    secondary = summary

    score = 50  # base score

    boosts = CANDIDATE_PROFILE["boost_keywords"]
    for kw in boosts["strong"]:
        kw = kw.lower()
        if kw in primary:
            score += 20
        elif kw in secondary:
            score += 10
    for kw in boosts["moderate"]:
        kw = kw.lower()
        if kw in primary:
            score += 12
        elif kw in secondary:
            score += 6
    for kw in boosts["light"]:
        kw = kw.lower()
        if kw in primary:
            score += 6
        elif kw in secondary:
            score += 3

    penalties = CANDIDATE_PROFILE["penalty_keywords"]
    for kw in penalties["hard"]:
        kw = kw.lower()
        if kw in title:
            return 0  # hard penalty in job title = automatic disqualification
        elif kw in primary:
            score -= 30
        elif kw in secondary:
            score -= 15
    for kw in penalties["soft"]:
        kw = kw.lower()
        if kw in primary:
            score -= 15
        elif kw in secondary:
            score -= 8

    return max(0, min(100, score))


def fetch_job_details(req_id: str, title_slug: str) -> dict:
    """Fetch the full job detail page and extract structured fields."""
    url = f"{_base_url()}/en-us/details/{req_id}/{title_slug}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
        html = resp.read().decode()

    m = re.search(
        r'__staticRouterHydrationData\s*=\s*JSON\.parse\("(.*?)"\);', html
    )
    if not m:
        return {}
    raw = m.group(1).encode().decode("unicode_escape")
    data = json.loads(raw)
    detail = data.get("loaderData", {}).get("jobDetails", {}).get("jobsData", {})
    title = detail.get("postingTitle")
    if title and "\uf8ff" in title:
        detail["postingTitle"] = _fix_logo_emoji(title)
    return detail


def _fix_logo_emoji(text: str) -> str:
    """Replace private-use logo char (U+F8FF) with the 🍎 emoji."""
    return text.replace("\uf8ff", "\U0001f34e")


def _sanitize_job_titles(data: dict) -> dict:
    """Fix logo chars in postingTitle fields within search results."""
    for job in data.get("searchResults", []):
        title = job.get("postingTitle")
        if title and "\uf8ff" in title:
            job["postingTitle"] = _fix_logo_emoji(title)
    return data


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    return " ".join(re.sub(r"<[^>]+>", " ", text).split()).lower()


# Years-of-experience patterns that disqualify early-career candidates
_YOE_PATTERN = re.compile(
    r"(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|relevant|professional|work)",
    re.IGNORECASE,
)


def _profile_level_preference() -> str:
    """Derive the candidate's preferred experience level from penalty keywords.

    Returns "entry-level", "mid-level", "senior", or "none".
    """
    hard = " ".join(CANDIDATE_PROFILE.get("penalty_keywords", {}).get("hard", []))
    penalises_entry = "entry level" in hard or "new grad" in hard
    penalises_senior = "senior" in hard
    if penalises_entry and penalises_senior:
        return "mid-level"
    if penalises_entry:
        return "senior"
    if penalises_senior:
        return "entry-level"
    return "none"


def _level_adjustment(detected_level: str, preference: str) -> int:
    """Return a score adjustment based on how well a detected level fits the preference.

    Returns a positive number for a good match, negative for a mismatch, 0 for neutral.
    The mapping is asymmetric: for entry-level/senior preferences, the adjacent
    mid-level is neutral (amber).  For a mid-level preference, both extremes are
    penalised equally since the profile explicitly penalises both.
    """
    # (preference, detected) → adjustment
    _ADJ = {
        ("entry-level", "entry-level"):  15,
        ("entry-level", "mid-level"):     0,   # adjacent — neutral
        ("entry-level", "senior"):      -50,   # opposite end
        ("mid-level",   "entry-level"): -30,   # explicitly penalised
        ("mid-level",   "mid-level"):    15,
        ("mid-level",   "senior"):      -15,   # mild stretch — more realistic than entry
        ("senior",      "entry-level"): -50,   # opposite end
        ("senior",      "mid-level"):     0,   # adjacent — neutral
        ("senior",      "senior"):       15,
    }
    return _ADJ.get((preference, detected_level), 0)


def second_pass_score(job_detail: dict) -> tuple[int, list[str], str]:
    """Score a job based on its full description.

    Returns (adjustment, reasons, experience_level).

    Experience levels:
      - "entry-level": no YOE requirement or explicitly early-career
      - "mid-level": 3-4 years required
      - "senior": 5+ years required
      - "unknown": couldn't determine

    Checks:
      - Years of experience required (scored relative to profile preference)
      - Tech stack match (boost for Python/Flask/JS/TS hits in requirements)
      - Early-career signals (scored relative to profile preference)
      - Job title seniority signals (Senior, Staff, Principal, Lead)
    """
    adjustment = 0
    reasons: list[str] = []
    experience_level = "unknown"
    preference = _profile_level_preference()

    min_qual = _strip_html(job_detail.get("minimumQualifications") or "")
    pref_qual = _strip_html(job_detail.get("preferredQualifications") or "")
    description = _strip_html(job_detail.get("description") or "")
    responsibilities = _strip_html(job_detail.get("responsibilities") or "")
    all_text = f"{min_qual} {pref_qual} {description} {responsibilities}"

    # --- Years of experience check ---
    # Check both minimum and preferred qualifications for YOE requirements
    yoe_matches = _YOE_PATTERN.findall(min_qual) or _YOE_PATTERN.findall(pref_qual)
    if yoe_matches:
        max_yoe = max(int(y) for y in yoe_matches)
        if max_yoe >= 5:
            experience_level = "senior"
            reasons.append(f"requires {max_yoe}+ years experience")
        elif max_yoe >= 3:
            experience_level = "mid-level"
            reasons.append(f"requires {max_yoe}+ years experience")
        elif max_yoe >= 1:
            experience_level = "entry-level"  # 1-2 years is accessible

    # --- Job title seniority signals ---
    job_title = (job_detail.get("postingTitle") or "").lower()
    if experience_level not in ("senior", "mid-level"):
        senior_title_signals = ["senior ", "staff ", "principal ", "lead "]
        for signal in senior_title_signals:
            if signal in job_title:
                experience_level = "senior"
                reasons.append(f"title indicates senior-level: '{signal.strip()}'")
                break

    # --- Early career signals (only if YOE/title didn't already indicate senior/mid) ---
    if experience_level not in ("senior", "mid-level"):
        early_signals = ["entry level", "new grad", "early career", "0-2 years",
                         "1-3 years", "recent graduate", "entry-level"]
        for signal in early_signals:
            if signal in all_text:
                experience_level = "entry-level"
                reasons.append(f"early-career signal: '{signal}'")
                break

    if experience_level == "unknown":
        # No YOE requirement found — likely accessible
        # Check for degree-only requirement (common for entry-level roles)
        if "bachelor" in min_qual or "degree" in min_qual:
            experience_level = "entry-level"
            reasons.append("degree-based requirement (no YOE)")

    # --- Apply profile-relative score adjustment for detected level ---
    if experience_level != "unknown":
        level_adj = _level_adjustment(experience_level, preference)
        if level_adj:
            adjustment += level_adj

    # --- Tech stack match in requirements ---
    tech_boosts = {
        "python": 8, "flask": 6, "fastapi": 6,
        "javascript": 5, "typescript": 5, "node.js": 5,
        "rest": 4, "api": 4, "sql": 4,
        "java": 4, "swift": 3,
        "full stack": 5, "full-stack": 5,
    }
    matched_tech = []
    for tech, boost in tech_boosts.items():
        if tech in min_qual or tech in pref_qual:
            adjustment += boost
            matched_tech.append(tech)
    if matched_tech:
        reasons.append(f"tech match: {', '.join(matched_tech)}")

    return adjustment, reasons, experience_level


def _fetch_with_retry(query: str, location_keys: list[str], page: int,
                      max_retries: int = 2) -> dict:
    """Fetch a search page with retry on timeout."""
    for attempt in range(max_retries + 1):
        try:
            return search_jobs(query, location_keys, page=page)
        except Exception as e:
            if "timed out" in str(e).lower() and attempt < max_retries:
                time.sleep(2 ** attempt)  # 1s, 2s backoff
                continue
            raise


def _collect_results(query: str, location_keys: list[str], pages: int,
                     seen_ids: set[str],
                     seen_ids_lock: "threading.Lock | None" = None,
                     ) -> tuple[list[dict], int, int]:
    """Fetch multiple pages for a query and return (new_jobs, total, new_count)."""
    new_jobs: list[dict] = []
    total = 0
    page_size = 0
    for page in range(1, pages + 1):
        data = _fetch_with_retry(query, location_keys, page=page)
        results = data.get("searchResults", [])
        total = data.get("totalRecords", len(results))
        if not results:
            break
        # Use the first page to learn the page size
        if page == 1:
            page_size = len(results)
        for job in results:
            req_id = job.get("positionId") or job.get("id") or ""
            if req_id:
                if seen_ids_lock:
                    with seen_ids_lock:
                        if req_id in seen_ids:
                            continue
                        seen_ids.add(req_id)
                elif req_id in seen_ids:
                    continue
                else:
                    seen_ids.add(req_id)
                job["_matchedQuery"] = query
                new_jobs.append(job)
        # Stop early when we've fetched all available pages
        if page_size and total and page >= math.ceil(total / page_size):
            break
        if page < pages:
            time.sleep(0.015)
    return new_jobs, total, len(new_jobs)


# Minimum score to include in final output (filters clearly irrelevant roles)
MIN_SCORE_THRESHOLD = 50


def _parse_posting_date(job: dict) -> datetime | None:
    """Parse a job's postingDate into a datetime, or None if missing/invalid."""
    raw = job.get("postingDate") or job.get("postDateInGMT") or ""
    if not raw:
        return None
    for fmt in ("%b %d, %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw.split(".")[0], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _categorize_jobs(jobs: list[dict]) -> dict[str, list[dict]]:
    """Split jobs into 'today', 'this_week', and 'older' buckets."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    buckets: dict[str, list[dict]] = {"today": [], "this_week": [], "older": []}
    for job in jobs:
        dt = _parse_posting_date(job)
        if dt and dt >= today_start:
            buckets["today"].append(job)
        elif dt and dt >= week_start:
            buckets["this_week"].append(job)
        else:
            buckets["older"].append(job)
    return buckets


def _score_color(score: int) -> str:
    """Return a hex color for a relevance score."""
    if score >= 70:
        return "#1a7f37"  # green
    if score >= 50:
        return "#9a6700"  # amber
    return "#cf222e"  # red


def _job_html_card(job: dict) -> str:
    """Render one job as a mobile-friendly card."""
    req_id = job.get("positionId") or job.get("id") or "—"
    title = job.get("postingTitle") or job.get("title") or "Untitled"
    team = (job.get("team") or {}).get("teamName", "")
    locs = job.get("locations") or []
    location = locs[0].get("name", "") if locs else ""
    score = job.get("_score", 0)
    url = make_job_url(job)
    date_str = job.get("postingDate", "")
    exp = job.get("_experience_level", "")
    reasons = job.get("_detail_reasons", [])

    # Badge color derived from the same scoring logic: green = good fit,
    # red = mismatch, amber = neutral.  Uses _level_adjustment so badge
    # colors and score adjustments always agree.
    preference = _profile_level_preference()
    _BADGE_CLASSES = {"good": "badge-good", "caution": "badge-caution", "bad": "badge-bad"}
    level_tone = {}
    for lvl in ("entry-level", "mid-level", "senior"):
        adj = _level_adjustment(lvl, preference)
        if adj > 0:
            level_tone[lvl] = "good"
        elif adj < 0:
            level_tone[lvl] = "bad"
        else:
            level_tone[lvl] = "caution"
    badge = ""
    if exp in level_tone:
        cls = _BADGE_CLASSES[level_tone[exp]]
        badge = f' <span class="{cls}" style="padding:2px 6px;border-radius:4px;font-size:11px;">{exp}</span>'

    reasons_html = ""
    if reasons:
        reasons_html = f'<div class="muted" style="font-size:12px;margin-top:4px;">{", ".join(reasons)}</div>'

    return f"""<div class="card" style="border-radius:8px;padding:12px;margin-bottom:10px;">
  <div style="display:flex;align-items:flex-start;gap:10px;">
    <div style="min-width:36px;text-align:center;">
      <span style="font-weight:bold;font-size:18px;color:{_score_color(score)};">{score}</span>
    </div>
    <div style="flex:1;min-width:0;">
      <a href="{url}" class="job-link" style="text-decoration:none;font-weight:600;font-size:15px;word-wrap:break-word;">{title}</a>{badge}
      <div class="muted" style="font-size:13px;margin-top:2px;">{req_id} &middot; {team}</div>
      <div class="muted" style="font-size:13px;margin-top:2px;">{location} &middot; {date_str}</div>
      {reasons_html}
    </div>
  </div>
</div>"""


def _section_html(title: str, subtitle: str, jobs: list[dict], accent_class: str,
                   max_jobs: int = 10) -> str:
    """Render a section (Today / This Week / All Open) as HTML."""
    if not jobs:
        return ""
    display_jobs = jobs[:max_jobs]
    hidden = len(jobs) - len(display_jobs)
    cards = "\n".join(_job_html_card(j) for j in display_jobs)
    truncation_note = ""
    if hidden > 0:
        truncation_note = f'<p style="margin:10px 0 0 0;font-size:12px;font-style:italic;" class="muted">Showing top {max_jobs} of {len(jobs)} matches.</p>'
    return f"""
<div style="margin-bottom:24px;">
  <h2 style="margin:0 0 4px 0;font-size:17px;" class="{accent_class}">{title}</h2>
  <p style="margin:0 0 10px 0;font-size:13px;" class="muted">{subtitle}</p>
  {cards}
  {truncation_note}
</div>"""


def build_email_html(jobs: list[dict], candidate_name: str) -> str:
    """Build a complete HTML email from scored job results."""
    buckets = _categorize_jobs(jobs)
    today_date = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%B %d, %Y")

    sections = []
    sections.append(_section_html(
        f"Best Fit — Posted Today",
        f"New listings from {today_date}",
        buckets["today"],
        "accent-green",
    ))
    sections.append(_section_html(
        "Best Fit — Posted This Week",
        "Listings from the past 7 days",
        buckets["this_week"],
        "accent-blue",
    ))
    sections.append(_section_html(
        "All Open Positions",
        "Older listings still worth a look",
        buckets["older"],
        "accent-gray",
    ))

    body_sections = "\n".join(s for s in sections if s)
    if not body_sections:
        body_sections = '<p class="muted">No matching roles found this run.</p>'

    total = len(jobs)
    today_count = len(buckets["today"])
    week_count = len(buckets["this_week"])

    # Build candidate profile summary
    profile = CANDIDATE_PROFILE
    referrer_name = profile.get("referrer_name", "")
    referrer_phone = profile.get("referrer_phone", "")
    boosts = profile.get("boost_keywords", {})
    penalties = profile.get("penalty_keywords", {})

    def _pill_list(keywords, css_class):
        return " ".join(
            f'<span class="pill {css_class}">{k}</span>'
            for k in keywords
        )

    # Build location labels from profile
    location_keys = profile.get("locations", DEFAULT_LOCATIONS)
    location_labels = [LOCATIONS[k]["label"] for k in location_keys if k in LOCATIONS]

    # Build search query list
    queries = profile.get("queries", [])

    profile_pills = f"""
      <div style="margin-bottom:10px;">
        <div class="profile-label">LOCATIONS</div>
        {_pill_list(location_labels, 'pill-location')}
      </div>
      <div style="margin-bottom:10px;">
        <div class="profile-label">SEARCH QUERIES</div>
        {_pill_list(queries, 'pill-neutral')}
      </div>
      <div style="margin-bottom:10px;">
        <div class="profile-label">FILTERS</div>
        {_pill_list([f"min score: {MIN_SCORE_THRESHOLD}", f"pages per query: {profile.get('pages_per_query', 1)}"], 'pill-neutral')}
      </div>
      <div style="margin-bottom:10px;">
        <div class="profile-label">STRONG FIT (confirmed skills)</div>
        {_pill_list(boosts.get('strong', []), 'pill-good')}
      </div>
      <div style="margin-bottom:10px;">
        <div class="profile-label">MODERATE FIT (coursework &amp; resume)</div>
        {_pill_list(boosts.get('moderate', []), 'pill-caution')}
      </div>
      <div style="margin-bottom:10px;">
        <div class="profile-label">LIGHT BOOST (adjacent interest)</div>
        {_pill_list(boosts.get('light', []), 'pill-info')}
      </div>
      <div>
        <div class="profile-label">FILTERED OUT (penalties applied)</div>
        {_pill_list(penalties.get('hard', []) + penalties.get('soft', []), 'pill-bad')}
      </div>"""

    referral_notes = profile.get("referral_notes", "")
    if referral_notes:
        referral_notes_html = f"""<div style="margin-top:14px;padding-top:12px;" class="referral-notes-border">
              <div class="profile-label" style="margin-bottom:6px;">REFERRAL NOTES</div>
              <p style="margin:0;font-size:13px;line-height:1.5;" class="body-text">{referral_notes}</p>
            </div>"""
    else:
        referral_notes_html = ""

    header_byline = (
        f'<p style="margin:6px 0 0 0;color:#a1a1a6;font-size:12px;">Curated by {referrer_name} for {candidate_name}</p>'
        if referrer_name else ""
    )

    if referrer_name and referrer_phone:
        _cta_action = f'then text <a href="sms:{referrer_phone}" class="cta-link">{referrer_name}</a> which position(s) you applied to so they can submit a referral on your behalf.'
    elif referrer_name:
        _cta_action = f'then let {referrer_name} know which position(s) you applied to so they can submit a referral on your behalf.'
    else:
        _cta_action = None
    cta_html = f"""    <!-- Call to action -->
    <div class="cta-box" style="border-radius:12px;padding:16px;margin-bottom:16px;">
      <p style="margin:0 0 6px 0;font-size:14px;font-weight:600;" class="cta-title">Interested in a role?</p>
      <p style="margin:0;font-size:13px;line-height:1.5;" class="cta-text">
        Apply directly on the jobs site as soon as possible, {_cta_action}
      </p>
    </div>""" if _cta_action else ""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    .pill {{ padding:2px 8px; border-radius:10px; font-size:12px; display:inline-block; margin:2px; }}
    .pill-location {{ background:#e8e0f0; color:#6639a6; }}
    .pill-neutral {{ background:#f0f0f0; color:#424245; }}
    .pill-good {{ background:#dafbe1; color:#1a7f37; }}
    .pill-caution {{ background:#fff8c5; color:#9a6700; }}
    .pill-info {{ background:#ddf4ff; color:#0969da; }}
    .pill-bad {{ background:#ffebe9; color:#cf222e; }}
    .badge-good {{ background:#dafbe1; color:#1a7f37; }}
    .badge-caution {{ background:#fff8c5; color:#9a6700; }}
    .badge-bad {{ background:#ffebe9; color:#cf222e; }}
    .accent-green {{ color:#1a7f37; }}
    .accent-blue {{ color:#0969da; }}
    .accent-gray {{ color:#656d76; }}
    .profile-label {{ color:#656d76; font-size:12px; font-weight:600; margin-bottom:4px; }}
    .muted {{ color:#656d76; }}
    .body-text {{ color:#1d1d1f; }}
    .job-link {{ color:#0969da; }}
    .card {{ border:1px solid #d0d7de; }}
    .referral-notes-border {{ border-top:1px solid #d0d7de; }}
    .cta-box {{ background:#ddf4ff; border:1px solid #54aeff; }}
    .cta-title {{ color:#0969da; }}
    .cta-text {{ color:#1d1d1f; }}
    .cta-link {{ color:#0969da; }}
    .jobs-panel {{ background:#ffffff; border:1px solid #d0d7de; }}
    .profile-panel {{ background:#f6f8fa; border:1px solid #d0d7de; }}
    .email-body {{ background:#f6f8fa; }}
    @media (prefers-color-scheme: dark) {{
      .pill-location {{ background:#3b2d5e; color:#c4a8e8; }}
      .pill-neutral {{ background:#3a3a3c; color:#d1d1d6; }}
      .pill-good {{ background:#1a3d2a; color:#7ee8a2; }}
      .pill-caution {{ background:#3d3520; color:#e8c84a; }}
      .pill-info {{ background:#1a2d40; color:#6cb6ff; }}
      .pill-bad {{ background:#3d1a1a; color:#f08080; }}
      .badge-good {{ background:#1a3d2a; color:#7ee8a2; }}
      .badge-caution {{ background:#3d3520; color:#e8c84a; }}
      .badge-bad {{ background:#3d1a1a; color:#f08080; }}
      .accent-green {{ color:#3fb950; }}
      .accent-blue {{ color:#6cb6ff; }}
      .accent-gray {{ color:#a1a1a6; }}
      .profile-label {{ color:#a1a1a6; }}
      .muted {{ color:#a1a1a6; }}
      .body-text {{ color:#e5e5e7; }}
      .job-link {{ color:#6cb6ff; }}
      .card {{ border-color:#48484a; }}
      .referral-notes-border {{ border-color:#48484a; }}
      .cta-box {{ background:#1a2d40; border-color:#2d5a8a; }}
      .cta-title {{ color:#6cb6ff; }}
      .cta-text {{ color:#e5e5e7; }}
      .cta-link {{ color:#6cb6ff; }}
      .jobs-panel {{ background:#1c1c1e; border-color:#48484a; }}
      .profile-panel {{ background:#1c1c1e; border-color:#48484a; }}
      .email-body {{ background:#000000; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;" class="email-body">
  <div style="max-width:600px;margin:0 auto;padding:16px;">
    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1d1d1f 0%,#424245 100%);border-radius:12px;padding:20px;margin-bottom:4px;">
      <h1 style="margin:0 0 4px 0;color:#ffffff;font-size:20px;font-weight:600;">
        Job Matches for {candidate_name}
      </h1>
      <p style="margin:0;color:#a1a1a6;font-size:13px;">{today_date}</p>
      {header_byline}
      <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
        <div style="background:rgba(255,255,255,0.1);border-radius:8px;padding:8px 14px;">
          <div style="color:#ffffff;font-size:18px;font-weight:bold;">{today_count}</div>
          <div style="color:#a1a1a6;font-size:11px;">Today</div>
        </div>
        <div style="background:rgba(255,255,255,0.1);border-radius:8px;padding:8px 14px;">
          <div style="color:#ffffff;font-size:18px;font-weight:bold;">{week_count}</div>
          <div style="color:#a1a1a6;font-size:11px;">This Week</div>
        </div>
        <div style="background:rgba(255,255,255,0.1);border-radius:8px;padding:8px 14px;">
          <div style="color:#ffffff;font-size:18px;font-weight:bold;">{total}</div>
          <div style="color:#a1a1a6;font-size:11px;">Total</div>
        </div>
      </div>
    </div>

    <!-- Candidate Profile -->
    <details style="margin-bottom:12px;cursor:pointer;">
      <summary style="list-style:none;text-align:center;padding:2px 0;" class="muted">
        <span style="font-size:11px;">View candidate profile for {candidate_name} &#9660;</span>
      </summary>
      <div class="profile-panel" style="border-radius:12px;padding:16px;margin-top:6px;">
        <h4 style="margin:0 0 10px 0;font-size:14px;" class="body-text">Candidate Profile: {profile.get('name', candidate_name)}</h4>
        {profile_pills}
        {referral_notes_html}
        <p style="margin:10px 0 0 0;font-size:11px;font-style:italic;" class="muted">This profile was generated collaboratively with AI powered by Claude.</p>
      </div>
    </details>

    {cta_html}

    <!-- Job Sections -->
    <div class="jobs-panel" style="border-radius:12px;padding:16px;">
      {body_sections}
    </div>

    <!-- Footer -->
    <div style="text-align:center;padding:16px 0;font-size:12px;">
      <p style="margin:0;font-size:11px;" class="muted">
        Reply to this email to stop receiving these messages or to request changes to your profile.
      </p>
    </div>
  </div>
</body>
</html>"""


def send_email(html: str, to_addr: str, candidate_name: str,
               cc_addr: str | None = None):
    """Send the HTML email via SMTP.

    Reads config from environment variables:
      SMTP_HOST     — SMTP server (default: smtp.mail.me.com)
      SMTP_PORT     — SMTP port (default: 587)
      SMTP_USER     — iCloud email address (required)
      SMTP_PASSWORD  — app-specific password (required)
      EMAIL_FROM    — From address (defaults to SMTP_USER)
    """
    host = os.environ.get("SMTP_HOST") or "smtp.mail.me.com"
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = os.environ.get("SMTP_USER") or ""
    password = os.environ.get("SMTP_PASSWORD") or ""
    from_addr = os.environ.get("EMAIL_FROM") or user

    if not user or not password:
        print("\n  SMTP credentials not configured.")
        print("  Set SMTP_USER and SMTP_PASSWORD environment variables.")
        print("  (For iCloud, generate an app-specific password in your account settings)")
        print(f"\n  Email saved to open_reqs_email.html instead.")
        with open("open_reqs_email.html", "w", encoding="utf-8") as f:
            f.write(html)
        return False

    today_str = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%b %d")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(f"Job Matches for {candidate_name} — {today_str}", "utf-8")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Reply-To"] = CANDIDATE_PROFILE.get("referrer_email", from_addr)
    recipients = [to_addr]
    if cc_addr:
        msg["Cc"] = cc_addr
        recipients.append(cc_addr)

    # Plain-text fallback
    _referrer_name = CANDIDATE_PROFILE.get("referrer_name", "")
    plain = (
        f"Job Matches for {candidate_name}\n"
        f"View this email in an HTML-capable client for the full report.\n"
        + (f"\nCurated by {_referrer_name} for {candidate_name}\n" if _referrer_name else "")
    )
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    cc_display = f" (cc: {cc_addr})" if cc_addr else ""
    print(f"\n  Sending email to {to_addr}{cc_display} via {host}:{port}...")
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, recipients, msg.as_string())
    print("  Email sent successfully!")
    return True


def run_candidate_search(location_keys: list[str], limit: int, as_json: bool,
                         email_to: str | None = None,
                         email_cc: str | None = None):
    """Run multiple searches for the candidate profile, deduplicate, and rank."""
    queries = CANDIDATE_PROFILE["queries"]
    seen_ids: set[str] = set()
    all_jobs: list[dict] = []
    pages_per_query = CANDIDATE_PROFILE.get("pages_per_query", 3)

    print(f"\n  Candidate search for {CANDIDATE_PROFILE['name']}", file=sys.stderr)
    locs_display = ", ".join(
        LOCATIONS[k]["label"] for k in location_keys if k in LOCATIONS
    )
    print(f"  Locations: {locs_display}", file=sys.stderr)
    max_search_workers = min(6, len(queries))
    print(f"  Running {len(queries)} searches ({pages_per_query} pages each, {max_search_workers} parallel)...\n", file=sys.stderr)

    seen_ids_lock = threading.Lock()

    def _run_query(idx_query):
        idx, query = idx_query
        try:
            new_jobs, total, new_count = _collect_results(
                query, location_keys, pages_per_query, seen_ids,
                seen_ids_lock=seen_ids_lock,
            )
            return idx, query, new_jobs, total, new_count
        except Exception as e:
            return idx, query, None, 0, e

    with ThreadPoolExecutor(max_workers=max_search_workers) as executor:
        futures = {executor.submit(_run_query, (i, q)): i
                   for i, q in enumerate(queries, 1)}
        for future in as_completed(futures):
            idx, query, new_jobs, total, result = future.result()
            if isinstance(result, Exception):
                print(f"  [{idx}/{len(queries)}] \"{query}\" — error: {result}", file=sys.stderr)
            else:
                all_jobs.extend(new_jobs)
                print(f"  [{idx}/{len(queries)}] \"{query}\" — {total} results, {result} new", file=sys.stderr)

    if not all_jobs:
        print("\n  No results found across all searches.", file=sys.stderr)
        return

    # First pass: score by title/team/summary
    for job in all_jobs:
        job["_score"] = score_job(job)
    all_jobs = [j for j in all_jobs if j["_score"] >= MIN_SCORE_THRESHOLD]
    all_jobs.sort(key=lambda j: j["_score"], reverse=True)

    # Second pass: fetch full details for top candidates and refine scores
    candidates = all_jobs[:limit * 2]  # fetch more than needed, some will drop
    if candidates:
        max_detail_workers = min(10, len(candidates))
        print(f"\n  Fetching details for top {len(candidates)} candidates ({max_detail_workers} parallel)...", file=sys.stderr)

        def _fetch_detail(job):
            req_id = job.get("positionId") or job.get("id") or ""
            title = job.get("postingTitle") or job.get("title") or ""
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            try:
                detail = fetch_job_details(req_id, slug)
                if detail:
                    adj, reasons, exp_level = second_pass_score(detail)
                    job["_score"] = max(0, min(100, job["_score"] + adj))
                    job["_detail_reasons"] = reasons
                    job["_experience_level"] = exp_level
                    job["_min_qual"] = _strip_html(
                        detail.get("minimumQualifications") or ""
                    )[:200]
            except Exception:
                pass  # keep first-pass score on failure

        with ThreadPoolExecutor(max_workers=max_detail_workers) as executor:
            list(executor.map(_fetch_detail, candidates))

    # Re-filter and sort after second pass
    all_jobs = [j for j in candidates if j["_score"] >= MIN_SCORE_THRESHOLD]
    all_jobs.sort(key=lambda j: j["_score"], reverse=True)

    shown = all_jobs[:limit]

    if as_json:
        output = []
        for job in shown:
            entry = {
                "reqId": job.get("positionId") or job.get("id"),
                "title": job.get("postingTitle") or job.get("title"),
                "team": (job.get("team") or {}).get("teamName", ""),
                "location": (job.get("locations") or [{}])[0].get("name", ""),
                "postingDate": job.get("postingDate", ""),
                "url": make_job_url(job),
                "score": job["_score"],
                "matchedQuery": job["_matchedQuery"],
            }
            if job.get("_experience_level"):
                entry["experienceLevel"] = job["_experience_level"]
            if job.get("_detail_reasons"):
                entry["detailReasons"] = job["_detail_reasons"]
            if job.get("_min_qual"):
                entry["minQualifications"] = job["_min_qual"]
            output.append(entry)
        print(json.dumps(output, indent=2))
        return

    # --- Email output ---
    if email_to:
        candidate_name = CANDIDATE_PROFILE["name"]
        html = build_email_html(shown, candidate_name)
        with open("email_digest.html", "w") as f:
            f.write(html)
        print(f"\n  Email HTML saved to email_digest.html")
        send_email(html, email_to, candidate_name, cc_addr=email_cc)
        return

    print(f"\n  Found {len(all_jobs)} unique roles (showing top {len(shown)} by fit)\n")
    print(f"  {'SCORE':<7} {'REQ ID':<14} {'TITLE':<48} {'TEAM':<22} LOCATION")
    print(f"  {'─' * 7} {'─' * 14} {'─' * 48} {'─' * 22} {'─' * 26}")

    for job in shown:
        req_id = job.get("positionId") or job.get("id") or "—"
        title = job.get("postingTitle") or job.get("title") or "Untitled"
        team = (job.get("team") or {}).get("teamName", "")
        locs = job.get("locations") or []
        location = locs[0].get("name", "") if locs else ""
        score = job["_score"]

        title = (title[:45] + "...") if len(title) > 48 else title
        team = (team[:19] + "...") if len(team) > 22 else team

        # Color-code score
        if score >= 70:
            score_str = f"  {score:>3}  "
        elif score >= 50:
            score_str = f"  {score:>3}  "
        else:
            score_str = f"  {score:>3}  "

        print(f"  {score_str} {req_id:<14} {title:<48} {team:<22} {location}")

    print()
    print("  Top links:")
    for job in shown[:20]:
        req_id = job.get("positionId") or job.get("id") or "—"
        score = job["_score"]
        print(f"    [{score:>3}] {req_id}  {make_job_url(job)}")
    print()


def _run_candidate_search_web(profile: dict, limit: int = 50) -> dict:
    """Run a full candidate search for the web UI and return categorized scored results."""
    global CANDIDATE_PROFILE
    old_profile = CANDIDATE_PROFILE
    CANDIDATE_PROFILE = profile
    try:
        location_keys = profile.get("locations", DEFAULT_LOCATIONS)
        queries = profile.get("queries", [])
        if not queries:
            return {"error": "No queries in profile"}

        pages_per_query = profile.get("pages_per_query", 3)
        seen_ids: set[str] = set()
        seen_ids_lock = threading.Lock()
        all_jobs: list[dict] = []
        max_workers = min(6, len(queries))

        def _run_query(idx_query: tuple) -> list[dict]:
            _, query = idx_query
            try:
                new_jobs, _, _ = _collect_results(
                    query, location_keys, pages_per_query, seen_ids,
                    seen_ids_lock=seen_ids_lock,
                )
                return new_jobs
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run_query, (i, q)): q
                       for i, q in enumerate(queries, 1)}
            for future in as_completed(futures):
                jobs = future.result()
                all_jobs.extend(jobs)

        # First pass: score by title/team
        for job in all_jobs:
            job["_score"] = score_job(job)
        all_jobs = [j for j in all_jobs if j["_score"] >= MIN_SCORE_THRESHOLD]
        all_jobs.sort(key=lambda j: j["_score"], reverse=True)

        # Second pass: fetch details for top candidates
        candidates = all_jobs[:limit * 2]
        if candidates:
            def _fetch_detail(job: dict) -> None:
                req_id = job.get("positionId") or job.get("id") or ""
                title = job.get("postingTitle") or job.get("title") or ""
                slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                try:
                    detail = fetch_job_details(req_id, slug)
                    if detail:
                        adj, reasons, exp_level = second_pass_score(detail)
                        job["_score"] = max(0, min(100, job["_score"] + adj))
                        job["_detail_reasons"] = reasons
                        job["_experience_level"] = exp_level
                except Exception:
                    pass

            with ThreadPoolExecutor(max_workers=min(10, len(candidates))) as executor:
                list(executor.map(_fetch_detail, candidates))

        # Re-filter and sort
        all_jobs = [j for j in candidates if j["_score"] >= MIN_SCORE_THRESHOLD]
        all_jobs.sort(key=lambda j: j["_score"], reverse=True)
        shown = all_jobs[:limit]

        # Categorize and serialize
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        preference = _profile_level_preference()

        buckets: dict[str, list] = {"today": [], "this_week": [], "older": []}
        for job in shown:
            dt = _parse_posting_date(job)
            if dt and dt >= today_start:
                bucket = "today"
            elif dt and dt >= week_start:
                bucket = "this_week"
            else:
                bucket = "older"

            exp = job.get("_experience_level", "")
            if exp:
                adj = _level_adjustment(exp, preference)
                level_tone = "good" if adj > 0 else ("bad" if adj < 0 else "neutral")
            else:
                level_tone = ""

            buckets[bucket].append({
                "reqId": job.get("positionId") or job.get("id"),
                "title": job.get("postingTitle") or job.get("title"),
                "team": (job.get("team") or {}).get("teamName", ""),
                "location": (job.get("locations") or [{}])[0].get("name", ""),
                "postingDate": job.get("postingDate", ""),
                "url": make_job_url(job),
                "score": job.get("_score", 0),
                "experienceLevel": exp,
                "levelTone": level_tone,
                "detailReasons": job.get("_detail_reasons", []),
            })

        today_date = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%B %d, %Y")
        location_labels = [LOCATIONS[k]["label"] for k in location_keys if k in LOCATIONS]
        boosts = profile.get("boost_keywords", {})
        penalties = profile.get("penalty_keywords", {})

        return {
            "candidateName": profile.get("name", ""),
            "date": today_date,
            "stats": {
                "today": len(buckets["today"]),
                "week": len(buckets["this_week"]),
                "total": len(shown),
            },
            "profile": {
                "locations": location_labels,
                "queries": profile.get("queries", []),
                "filters": {
                    "minScore": MIN_SCORE_THRESHOLD,
                    "pagesPerQuery": profile.get("pages_per_query", 3),
                },
                "boosts": {
                    "strong": boosts.get("strong", []),
                    "moderate": boosts.get("moderate", []),
                    "light": boosts.get("light", []),
                },
                "penalties": {
                    "hard": penalties.get("hard", []),
                    "soft": penalties.get("soft", []),
                },
                "referralNotes": profile.get("referral_notes", ""),
            },
            "referrer": {
                "name": profile.get("referrer_name", ""),
                "phone": profile.get("referrer_phone", ""),
            },
            "sections": buckets,
        }
    finally:
        CANDIDATE_PROFILE = old_profile


def search_jobs(query: str, location_keys: list[str], page: int = 1) -> dict:
    """Search jobs by fetching the search page and extracting embedded data."""
    loc_slugs = [LOCATIONS[k]["slug"] for k in location_keys if k in LOCATIONS]
    params = [("search", query), ("page", str(page))]
    if loc_slugs:
        params.append(("location", " ".join(loc_slugs)))

    query_string = urllib.parse.urlencode(params)
    url = f"{_base_url()}/en-us/search?{query_string}"

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )

    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
        html = resp.read().decode()

    m = re.search(
        r'__staticRouterHydrationData\s*=\s*JSON\.parse\("(.*?)"\);', html
    )
    if not m:
        raise RuntimeError("Could not find job data in page response")

    raw = m.group(1).encode().decode("unicode_escape")
    data = json.loads(raw)
    search_data = data.get("loaderData", {}).get("search", {})
    return _sanitize_job_titles(search_data)


def make_job_url(job: dict) -> str:
    """Build the job posting URL."""
    req_id = job.get("positionId") or job.get("id", "")
    title = job.get("postingTitle") or job.get("title") or ""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{_base_url()}/en-us/details/{req_id}/{slug}"


def print_jobs(data: dict, limit: int):
    """Pretty-print job results to the terminal."""
    jobs = data.get("searchResults", [])
    total = data.get("totalRecords", len(jobs))

    if not jobs:
        print("No results found.")
        return

    shown = min(len(jobs), limit)
    print(f"\n  Found {total} roles (showing {shown})\n")
    print(f"  {'REQ ID':<14} {'TITLE':<52} {'TEAM':<24} LOCATION")
    print(f"  {'─' * 14} {'─' * 52} {'─' * 24} {'─' * 28}")

    for job in jobs[:limit]:
        req_id = job.get("positionId") or job.get("id") or "—"
        title = job.get("postingTitle") or job.get("title") or "Untitled"
        team = (job.get("team") or {}).get("teamName", "")
        locs = job.get("locations") or []
        location = locs[0].get("name", "") if locs else ""

        # Truncate long fields
        title = (title[:49] + "...") if len(title) > 52 else title
        team = (team[:21] + "...") if len(team) > 24 else team

        print(f"  {req_id:<14} {title:<52} {team:<24} {location}")

    print()
    # Print URLs for easy copy-paste
    print("  Links:")
    for job in jobs[:limit]:
        req_id = job.get("positionId") or job.get("id") or "—"
        title = job.get("postingTitle") or job.get("title") or "Untitled"
        title = (title[:60] + "...") if len(title) > 63 else title
        print(f"    {req_id}  {make_job_url(job)}")
    print()


def output_json(data: dict, limit: int):
    """Output results as JSON."""
    jobs = data.get("searchResults", [])[:limit]
    output = []
    for job in jobs:
        output.append({
            "reqId": job.get("positionId") or job.get("id"),
            "title": job.get("postingTitle") or job.get("title"),
            "team": (job.get("team") or {}).get("teamName", ""),
            "location": (job.get("locations") or [{}])[0].get("name", ""),
            "postingDate": job.get("postingDate", ""),
            "url": make_job_url(job),
        })
    print(json.dumps(output, indent=2))


def send_email_from_json(json_path: str, email_to: str,
                         email_cc: str | None = None):
    """Build and send an email digest from a previously saved JSON results file."""
    with open(json_path) as f:
        entries = json.load(f)

    # Reconstruct job dicts that _job_html_card and build_email_html expect
    jobs = []
    for entry in entries:
        job = {
            "positionId": entry.get("reqId", ""),
            "postingTitle": _fix_logo_emoji(entry.get("title", "")),
            "team": {"teamName": entry.get("team", "")},
            "locations": [{"name": entry.get("location", "")}],
            "postingDate": entry.get("postingDate", ""),
            "_score": entry.get("score", 0),
            "_matchedQuery": entry.get("matchedQuery", ""),
            "_experience_level": entry.get("experienceLevel", ""),
            "_detail_reasons": entry.get("detailReasons", []),
            "_min_qual": entry.get("minQualifications", ""),
        }
        jobs.append(job)

    candidate_name = CANDIDATE_PROFILE["name"]
    html = build_email_html(jobs, candidate_name)
    with open("email_digest.html", "w") as f:
        f.write(html)
    print(f"\n  Email HTML saved to email_digest.html ({len(jobs)} jobs from {json_path})")
    send_email(html, email_to, candidate_name, cc_addr=email_cc)


def run_server(port: int):
    """Run a local proxy server that serves the web UI and proxies API calls."""
    import http.server
    import socketserver

    web_dir = SCRIPT_DIR / "web"
    index_path = web_dir / "index.html"
    if not index_path.exists():
        print(f"Web UI not found at {index_path}")
        sys.exit(1)

    class ProxyHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_dir), **kwargs)

        def _json_ok(self, data: object) -> None:
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json_err(self, status: int, message: str) -> None:
            body = json.dumps({"error": message}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/locations":
                self._json_ok({k: v["label"] for k, v in LOCATIONS.items()})
            elif self.path == "/api/profiles":
                profiles = [p.name for p in sorted(SCRIPT_DIR.glob("*_profile.yaml"))]
                if (SCRIPT_DIR / "candidate_profile.yaml").exists():
                    cdf = "candidate_profile.yaml"
                    if cdf not in profiles:
                        profiles.insert(0, cdf)
                self._json_ok(profiles)
            elif self.path.startswith("/api/profile/"):
                filename = self.path[len("/api/profile/"):]
                if "/" in filename or ".." in filename or not filename.endswith(".yaml"):
                    self.send_response(400)
                    self.end_headers()
                    return
                profile_path = SCRIPT_DIR / filename
                if not profile_path.exists():
                    self.send_response(404)
                    self.end_headers()
                    return
                with open(profile_path) as f:
                    self._json_ok(yaml.safe_load(f))
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == "/api/role/search":
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)

                try:
                    req_data = json.loads(body)
                    query = req_data.get("query", "")
                    loc_filters = req_data.get("filters", {}).get("postingpostLocation", [])
                    page = req_data.get("page", 1)

                    # Map old filter IDs to location keys
                    loc_keys = []
                    for f in loc_filters:
                        code = f.replace("postLocation-", "")
                        if code in LOCATIONS:
                            loc_keys.append(code)

                    result = search_jobs(query, loc_keys, page)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode())
                except Exception as e:
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            elif self.path == "/api/candidate/search":
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                try:
                    profile = json.loads(body)
                    self._json_ok(_run_candidate_search_web(profile))
                except Exception as e:
                    self._json_err(502, str(e))
            else:
                self.send_response(404)
                self.end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def log_message(self, format, *args):
            if "/api/" in str(args):
                print(f"  [proxy] {args[0]}")

    with socketserver.TCPServer(("", port), ProxyHandler) as httpd:
        print(f"\n  Job Search running at http://localhost:{port}")
        print(f"  Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="Search open job listings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            location codes:
              SCV   Santa Clara Valley / Cupertino
              SVL   Sunnyvale
              SJOS  Campbell / San Jose
              USA   All US
              AUS   Austin
              SEA   Seattle
              NYC   New York City
              SDG   San Diego
              CUL   Culver City
              IRV   Irvine

            examples:
              python open_reqs.py
              python open_reqs.py -q "backend engineer" -l SVL SCV
              python open_reqs.py -q "data analyst" --limit 50 --json
              python open_reqs.py --candidate
              python open_reqs.py --candidate --limit 30 --json
              python open_reqs.py --candidate --email user@example.com
              python open_reqs.py --candidate --profile kevin_katz_profile.yaml
              python open_reqs.py --serve
        """),
    )
    parser.add_argument("-q", "--query", type=str, default=DEFAULT_QUERY,
                        help=f"Search query (default: '{DEFAULT_QUERY}')")
    parser.add_argument("-l", "--location", nargs="+", default=DEFAULT_LOCATIONS,
                        choices=list(LOCATIONS.keys()), metavar="LOC",
                        help="Location codes (default: SCV SVL)")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max results to display (default: 20)")
    parser.add_argument("--page", type=int, default=1,
                        help="Results page number (default: 1)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--serve", action="store_true",
                        help="Start the web UI with built-in proxy server")
    parser.add_argument("--port", type=int, default=8080,
                        help="Port for web server (default: 8080)")
    parser.add_argument("--candidate", action="store_true",
                        help="Run multi-query candidate-profile search (scored & deduplicated)")
    parser.add_argument("--profile", type=str, metavar="FILE",
                        help="Path to candidate profile YAML (default: candidate_profile.yaml)")
    parser.add_argument("--email", type=str, metavar="ADDR",
                        help="Send results as a rich HTML email (use with --candidate)")
    parser.add_argument("--cc", type=str, metavar="ADDR",
                        help="CC address for the email (use with --email)")
    parser.add_argument("--from-json", type=str, metavar="FILE",
                        help="Build email from a previously saved JSON results file (skip search)")
    args = parser.parse_args()

    if args.serve:
        run_server(args.port)
        return

    if args.profile:
        global CANDIDATE_PROFILE
        CANDIDATE_PROFILE = _load_candidate_profile(args.profile)

    if args.from_json:
        if not args.email:
            print("  --from-json requires --email", file=sys.stderr)
            sys.exit(1)
        send_email_from_json(args.from_json, args.email, email_cc=args.cc)
        return

    if args.candidate:
        locs = CANDIDATE_PROFILE["locations"]
        run_candidate_search(locs, args.limit, args.json, email_to=args.email,
                             email_cc=args.cc)
        return

    locs_display = ", ".join(LOCATIONS[k]["label"] for k in args.location if k in LOCATIONS)
    print(f"\n  Searching: \"{args.query}\"")
    print(f"  Locations: {locs_display}")

    try:
        data = search_jobs(args.query, args.location, args.page)
    except Exception as e:
        print(f"\n  Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        output_json(data, args.limit)
    else:
        print_jobs(data, args.limit)


if __name__ == "__main__":
    main()
