"""Tests for build_email_html — verifies structure and content of the email digest."""
from datetime import datetime, timedelta, timezone

import open_reqs
from tests.fixtures import TEST_PROFILE


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y")


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%b %d, %Y")


SAMPLE_JOBS = [
    {
        "positionId": "200591234",
        "postingTitle": "Software Engineer, iCloud CloudKit",
        "team": {"teamName": "iCloud"},
        "locations": [{"name": "Santa Clara Valley, California, United States"}],
        "postingDate": _today(),
        "_score": 87,
        "_matchedQuery": "software engineer",
        "_experience_level": "mid-level",
        "_detail_reasons": ["CloudKit", "distributed systems", "Swift"],
        "_min_qual": "5+ years experience building large-scale distributed systems.",
    },
    {
        "positionId": "200591235",
        "postingTitle": "Platform Infrastructure Engineer",
        "team": {"teamName": "Core OS"},
        "locations": [{"name": "Sunnyvale, California, United States"}],
        "postingDate": _today(),
        "_score": 74,
        "_matchedQuery": "platform engineer",
        "_experience_level": "senior",
        "_detail_reasons": ["Kubernetes", "Linux", "infrastructure"],
        "_min_qual": "",
    },
    {
        "positionId": "200589001",
        "postingTitle": "Site Reliability Engineer, Core Services",
        "team": {"teamName": "Apple Services Engineering"},
        "locations": [{"name": "San Jose, California, United States"}],
        "postingDate": _days_ago(3),
        "_score": 68,
        "_matchedQuery": "site reliability engineer",
        "_experience_level": "mid-level",
        "_detail_reasons": ["networking", "reliability"],
        "_min_qual": "",
    },
    {
        "positionId": "200580099",
        "postingTitle": "Cloud Infrastructure Software Engineer",
        "team": {"teamName": "Apple Cloud Services"},
        "locations": [{"name": "Santa Clara Valley, California, United States"}],
        "postingDate": _days_ago(14),
        "_score": 62,
        "_matchedQuery": "cloud infrastructure engineer",
        "_experience_level": "mid-level",
        "_detail_reasons": ["iCloud", "networking"],
        "_min_qual": "",
    },
]


def _build(jobs=None, profile=None):
    """Helper: set CANDIDATE_PROFILE and call build_email_html."""
    open_reqs.CANDIDATE_PROFILE = profile or TEST_PROFILE
    return open_reqs.build_email_html(jobs if jobs is not None else SAMPLE_JOBS,
                                      (profile or TEST_PROFILE)["name"])


class TestEmailStructure:
    def test_returns_string(self):
        assert isinstance(_build(), str)

    def test_is_html_document(self):
        html = _build()
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_has_style_block(self):
        assert "<style>" in _build()

    def test_candidate_name_in_output(self):
        html = _build()
        assert TEST_PROFILE["name"] in html


class TestDateBuckets:
    def test_today_section_present(self):
        html = _build()
        assert "Best Fit — Posted Today" in html

    def test_this_week_section_present(self):
        html = _build()
        assert "Best Fit — Posted This Week" in html

    def test_older_section_present(self):
        html = _build()
        assert "All Open Positions" in html

    def test_no_matching_roles_message_when_empty(self):
        html = _build(jobs=[])
        assert "No matching roles found" in html

    def test_today_jobs_appear(self):
        html = _build()
        assert "iCloud CloudKit" in html
        assert "Platform Infrastructure Engineer" in html

    def test_older_jobs_appear(self):
        html = _build()
        assert "Cloud Infrastructure Software Engineer" in html


class TestJobCards:
    def test_req_id_shown(self):
        assert "200591234" in _build()

    def test_team_name_shown(self):
        assert "iCloud" in _build()

    def test_score_shown(self):
        assert "87" in _build()

    def test_job_link_present(self):
        html = _build()
        assert "jobs.apple.com" in html

    def test_detail_reasons_shown(self):
        html = _build()
        assert "CloudKit" in html


class TestProfileSummary:
    def test_boost_keywords_present(self):
        html = _build()
        for kw in TEST_PROFILE["boost_keywords"]["strong"]:
            assert kw in html, f"Expected strong boost keyword '{kw}' in email"

    def test_penalty_keywords_present(self):
        html = _build()
        for kw in TEST_PROFILE["penalty_keywords"]["hard"]:
            assert kw in html, f"Expected penalty keyword '{kw}' in email"

    def test_referrer_name_present(self):
        assert TEST_PROFILE["referrer_name"] in _build()

    def test_referral_notes_present(self):
        assert TEST_PROFILE["referral_notes"] in _build()

    def test_cta_shown_with_referrer(self):
        assert "Interested in a role?" in _build()

    def test_no_cta_without_referrer(self):
        profile = {**TEST_PROFILE, "referrer_name": "", "referrer_phone": ""}
        html = _build(profile=profile)
        assert "Interested in a role?" not in html

    def test_location_labels_present(self):
        html = _build()
        # TEST_PROFILE uses SCV and SVL
        assert "Santa Clara Valley" in html or "Sunnyvale" in html
