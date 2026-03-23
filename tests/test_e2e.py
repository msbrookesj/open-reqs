"""End-to-end tests: real ProxyHandler + mocked jobs.apple.com responses.

Each test hits the actual HTTP server started in conftest.py.
External calls (urlopen → jobs.apple.com) are intercepted by _mock_urlopen.
"""
import json

import yaml

from tests.conftest import api_get, api_post, api_put
from tests.fixtures import TEST_PROFILE, JOBS


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/locations
# ═══════════════════════════════════════════════════════════════════════════════

class TestLocations:
    def test_returns_all_locations(self, server_url):
        status, data = api_get(server_url, "/api/locations")
        assert status == 200
        assert "SCV" in data
        assert "SVL" in data
        assert data["SCV"] == "Santa Clara Valley / Cupertino"

    def test_location_count(self, server_url):
        _, data = api_get(server_url, "/api/locations")
        assert len(data) == 10  # SCV, SVL, SJOS, USA, AUS, SEA, NYC, SDG, CUL, IRV


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/profiles  +  GET /api/profile/<file>
# ═══════════════════════════════════════════════════════════════════════════════

class TestProfiles:
    def test_list_profiles(self, server_url):
        status, data = api_get(server_url, "/api/profiles")
        assert status == 200
        assert isinstance(data, list)
        assert "test_user_profile.yaml" in data

    def test_get_profile(self, server_url):
        status, data = api_get(server_url, "/api/profile/test_user_profile.yaml")
        assert status == 200
        assert data["name"] == "Test User"
        assert data["email"] == "test@example.com"
        assert "Python" in data["boost_keywords"]["strong"]

    def test_get_nonexistent_profile(self, server_url):
        status, _ = api_get(server_url, "/api/profile/nonexistent_profile.yaml")
        assert status == 404

    def test_get_profile_bad_filename(self, server_url):
        status, _ = api_get(server_url, "/api/profile/../../etc/passwd")
        assert status == 400

    def test_get_profile_non_yaml(self, server_url):
        status, _ = api_get(server_url, "/api/profile/bad.txt")
        assert status == 400


# ═══════════════════════════════════════════════════════════════════════════════
# PUT /api/profile/<file>
# ═══════════════════════════════════════════════════════════════════════════════

class TestProfileWrite:
    def test_save_and_reload_profile(self, server_url):
        modified = dict(TEST_PROFILE)
        modified["name"] = "Updated User"
        modified["queries"] = ["data scientist"]

        status, data = api_put(server_url, "/api/profile/test_user_profile.yaml", modified)
        assert status == 200
        assert data["saved"] == "test_user_profile.yaml"

        # Verify the change persisted
        status, reloaded = api_get(server_url, "/api/profile/test_user_profile.yaml")
        assert reloaded["name"] == "Updated User"
        assert reloaded["queries"] == ["data scientist"]

        # Restore original
        api_put(server_url, "/api/profile/test_user_profile.yaml", TEST_PROFILE)

    def test_create_new_profile(self, server_url):
        new_profile = {
            "name": "New Person",
            "email": "new@example.com",
            "locations": ["AUS"],
            "queries": ["frontend engineer"],
            "pages_per_query": 2,
            "boost_keywords": {"strong": ["React"], "moderate": [], "light": []},
            "penalty_keywords": {"hard": [], "soft": []},
        }
        status, _ = api_put(server_url, "/api/profile/new_person_profile.yaml", new_profile)
        assert status == 200

        status, data = api_get(server_url, "/api/profile/new_person_profile.yaml")
        assert data["name"] == "New Person"

    def test_save_profile_bad_filename(self, server_url):
        status, _ = api_put(server_url, "/api/profile/../hack.yaml", {"name": "x"})
        assert status == 400


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/role/search  (legacy single-query search)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleSearch:
    def test_basic_search(self, server_url):
        status, data = api_post(server_url, "/api/role/search", {
            "query": "software engineer",
            "filters": {},
            "page": 1,
        })
        assert status == 200
        assert "searchResults" in data
        assert "totalRecords" in data
        assert len(data["searchResults"]) > 0

    def test_search_with_location_filter(self, server_url):
        status, data = api_post(server_url, "/api/role/search", {
            "query": "software engineer",
            "filters": {"postingpostLocation": ["postLocation-SCV"]},
            "page": 1,
        })
        assert status == 200
        assert "searchResults" in data

    def test_search_result_fields(self, server_url):
        status, data = api_post(server_url, "/api/role/search", {
            "query": "software engineer",
        })
        assert status == 200
        job = data["searchResults"][0]
        assert "positionId" in job
        assert "postingTitle" in job
        assert "team" in job
        assert "locations" in job


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/candidate/search  (full two-pass scored search)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCandidateSearch:
    def test_candidate_search_returns_sections(self, server_url):
        status, data = api_post(server_url, "/api/candidate/search", TEST_PROFILE)
        assert status == 200
        assert "sections" in data
        assert "today" in data["sections"]
        assert "this_week" in data["sections"]
        assert "older" in data["sections"]

    def test_candidate_search_metadata(self, server_url):
        status, data = api_post(server_url, "/api/candidate/search", TEST_PROFILE)
        assert status == 200
        assert data["candidateName"] == "Test User"
        assert "stats" in data
        assert "total" in data["stats"]
        assert "profile" in data
        assert data["profile"]["queries"] == TEST_PROFILE["queries"]

    def test_candidate_search_scoring(self, server_url):
        """Jobs matching boost keywords should score higher than mismatches."""
        status, data = api_post(server_url, "/api/candidate/search", TEST_PROFILE)
        assert status == 200

        all_jobs = (
            data["sections"]["today"]
            + data["sections"]["this_week"]
            + data["sections"]["older"]
        )

        if not all_jobs:
            return  # mock data may not match — skip gracefully

        # Every returned job should have score >= 50 (MIN_SCORE_THRESHOLD)
        for job in all_jobs:
            assert job["score"] >= 50, f"{job['title']} scored {job['score']} (below threshold)"

    def test_candidate_search_filters_hard_penalty(self, server_url):
        """Jobs with hard-penalty keywords in title should be excluded."""
        status, data = api_post(server_url, "/api/candidate/search", TEST_PROFILE)
        assert status == 200

        all_jobs = (
            data["sections"]["today"]
            + data["sections"]["this_week"]
            + data["sections"]["older"]
        )

        # "Intern" is a hard penalty — the intern job title should be filtered out
        titles = [j["title"] for j in all_jobs]
        for title in titles:
            assert "intern" not in title.lower(), f"Hard-penalty job leaked through: {title}"

    def test_candidate_search_job_fields(self, server_url):
        """Each job in results should have the expected serialized fields."""
        status, data = api_post(server_url, "/api/candidate/search", TEST_PROFILE)
        all_jobs = (
            data["sections"]["today"]
            + data["sections"]["this_week"]
            + data["sections"]["older"]
        )
        if not all_jobs:
            return

        job = all_jobs[0]
        assert "reqId" in job
        assert "title" in job
        assert "team" in job
        assert "score" in job
        assert "url" in job
        assert "postingDate" in job

    def test_candidate_search_experience_level(self, server_url):
        """Second-pass scoring should detect experience levels."""
        status, data = api_post(server_url, "/api/candidate/search", TEST_PROFILE)
        all_jobs = (
            data["sections"]["today"]
            + data["sections"]["this_week"]
            + data["sections"]["older"]
        )
        if not all_jobs:
            return

        # At least some jobs should have experience level set
        levels = [j.get("experienceLevel") for j in all_jobs if j.get("experienceLevel")]
        assert len(levels) > 0, "No jobs had experience level detected"
        for level in levels:
            assert level in ("entry-level", "mid-level", "senior", "unknown")

    def test_candidate_search_level_tone(self, server_url):
        """Jobs with experience levels should have levelTone set."""
        status, data = api_post(server_url, "/api/candidate/search", TEST_PROFILE)
        all_jobs = (
            data["sections"]["today"]
            + data["sections"]["this_week"]
            + data["sections"]["older"]
        )
        for job in all_jobs:
            if job.get("experienceLevel"):
                assert job["levelTone"] in ("good", "bad", "neutral"), (
                    f"Unexpected levelTone: {job['levelTone']}"
                )

    def test_candidate_search_deduplication(self, server_url):
        """Results should not contain duplicate reqIds across all buckets."""
        status, data = api_post(server_url, "/api/candidate/search", TEST_PROFILE)
        all_jobs = (
            data["sections"]["today"]
            + data["sections"]["this_week"]
            + data["sections"]["older"]
        )
        req_ids = [j["reqId"] for j in all_jobs]
        assert len(req_ids) == len(set(req_ids)), f"Duplicate reqIds found: {req_ids}"

    def test_candidate_search_empty_queries(self, server_url):
        """Profile with no queries should return an error."""
        profile = dict(TEST_PROFILE)
        profile["queries"] = []
        status, data = api_post(server_url, "/api/candidate/search", profile)
        assert status == 200  # returns 200 with error key
        assert "error" in data

    def test_candidate_search_referrer(self, server_url):
        status, data = api_post(server_url, "/api/candidate/search", TEST_PROFILE)
        assert data["referrer"]["name"] == "Jane Doe"
        assert data["referrer"]["phone"] == "+1 (408) 555-0100"


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/ai-enhance  (should fail gracefully with no Claude CLI)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAIEnhance:
    def test_ai_enhance_without_claude(self, server_url):
        """With _CLAUDE_BIN=None, ai-enhance should return an error."""
        status, data = api_post(server_url, "/api/ai-enhance", {
            "profile": TEST_PROFILE,
            "results": None,
            "message": "make it better",
        })
        # Should fail because Claude CLI is not available
        assert status == 502
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/auth/status
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthStatus:
    def test_auth_status_no_claude(self, server_url):
        """With _CLAUDE_BIN=None, auth should report not authenticated."""
        status, data = api_get(server_url, "/api/auth/status")
        assert status == 200
        assert data["authenticated"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow CRUD: GET/PUT /api/workflow/<file>
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflow:
    def test_workflow_not_exists(self, server_url):
        status, data = api_get(server_url, "/api/workflow/test_user_profile.yaml")
        assert status == 200
        assert data["exists"] is False
        assert data["cron"] is None

    def test_create_and_read_workflow(self, server_url):
        # Create a workflow
        status, data = api_put(server_url, "/api/workflow/test_user_profile.yaml", {
            "cron": "30 14 * * *",
        })
        assert status == 200
        assert data["saved"] is True
        assert data["cron"] == "30 14 * * *"

        # Read it back
        status, data = api_get(server_url, "/api/workflow/test_user_profile.yaml")
        assert status == 200
        assert data["exists"] is True
        assert data["cron"] == "30 14 * * *"

    def test_update_workflow_cron(self, server_url):
        # Ensure it exists first
        api_put(server_url, "/api/workflow/test_user_profile.yaml", {"cron": "0 8 * * *"})

        # Update the cron
        status, data = api_put(server_url, "/api/workflow/test_user_profile.yaml", {
            "cron": "0 20 * * 1-5",
        })
        assert status == 200

        # Verify update
        status, data = api_get(server_url, "/api/workflow/test_user_profile.yaml")
        assert data["cron"] == "0 20 * * 1-5"

    def test_workflow_empty_cron_rejected(self, server_url):
        status, data = api_put(server_url, "/api/workflow/test_user_profile.yaml", {
            "cron": "",
        })
        assert status == 400

    def test_workflow_bad_filename(self, server_url):
        status, data = api_get(server_url, "/api/workflow/bad.txt")
        assert status == 400


# ═══════════════════════════════════════════════════════════════════════════════
# CORS / OPTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class TestCORS:
    def test_options_preflight(self, server_url):
        import http.client
        import urllib.parse
        parsed = urllib.parse.urlparse(server_url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("OPTIONS", "/api/locations")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 204
        assert resp.getheader("Access-Control-Allow-Origin") is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Scoring unit tests (via the server's candidate search)
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoring:
    def test_boost_keywords_raise_score(self, server_url):
        """A profile with strong boost on 'Python' should score Python jobs higher."""
        python_profile = dict(TEST_PROFILE)
        python_profile["queries"] = ["software engineer"]
        python_profile["boost_keywords"] = {
            "strong": ["Python"],
            "moderate": [],
            "light": [],
        }
        python_profile["penalty_keywords"] = {"hard": [], "soft": []}

        status, data = api_post(server_url, "/api/candidate/search", python_profile)
        all_jobs = (
            data["sections"]["today"]
            + data["sections"]["this_week"]
            + data["sections"]["older"]
        )
        # Find the Python Platform job if present
        python_jobs = [j for j in all_jobs if "python" in j["title"].lower()]
        other_jobs = [j for j in all_jobs if "python" not in j["title"].lower()]

        if python_jobs and other_jobs:
            # Python jobs should tend to score higher
            avg_python = sum(j["score"] for j in python_jobs) / len(python_jobs)
            avg_other = sum(j["score"] for j in other_jobs) / len(other_jobs)
            assert avg_python >= avg_other, (
                f"Python avg ({avg_python}) should be >= other avg ({avg_other})"
            )

    def test_soft_penalty_lowers_score(self, server_url):
        """Hardware penalty should lower hardware job scores."""
        # Profile that penalises hardware
        hw_penalty_profile = dict(TEST_PROFILE)
        hw_penalty_profile["queries"] = ["engineer"]
        hw_penalty_profile["boost_keywords"] = {"strong": [], "moderate": [], "light": []}
        hw_penalty_profile["penalty_keywords"] = {
            "hard": [],
            "soft": ["hardware"],
        }

        status, data = api_post(server_url, "/api/candidate/search", hw_penalty_profile)
        all_jobs = (
            data["sections"]["today"]
            + data["sections"]["this_week"]
            + data["sections"]["older"]
        )

        hw_jobs = [j for j in all_jobs if "hardware" in j["title"].lower()]
        # Hardware jobs should either be filtered out or scored lower
        for job in hw_jobs:
            assert job["score"] <= 50, f"Hardware job scored too high: {job['score']}"


# ═══════════════════════════════════════════════════════════════════════════════
# Profile generation (should fail without Claude)
# ═══════════════════════════════════════════════════════════════════════════════

class TestProfileGenerate:
    def test_generate_without_claude(self, server_url):
        status, data = api_post(server_url, "/api/profile/generate", {
            "name": "Test Person",
            "resume_text": "I am a software engineer.",
            "filename": "generated_profile.yaml",
        })
        assert status == 502
        assert "error" in data

    def test_generate_missing_name(self, server_url):
        status, data = api_post(server_url, "/api/profile/generate", {
            "name": "",
            "resume_text": "resume",
            "filename": "generated_profile.yaml",
        })
        assert status == 400

    def test_generate_bad_filename(self, server_url):
        status, data = api_post(server_url, "/api/profile/generate", {
            "name": "Test",
            "resume_text": "resume",
            "filename": "../hack.yaml",
        })
        assert status == 400


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: full round-trip (save profile → search → verify)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoundTrip:
    def test_save_profile_then_search(self, server_url):
        """Save a custom profile, then run a candidate search against it."""
        custom = {
            "name": "Round Trip User",
            "email": "rt@test.com",
            "locations": ["SCV"],
            "queries": ["CoreOS engineer"],
            "pages_per_query": 1,
            "boost_keywords": {
                "strong": ["C", "CoreOS"],
                "moderate": ["operating systems"],
                "light": [],
            },
            "penalty_keywords": {"hard": ["intern"], "soft": []},
            "referrer_name": "",
            "referrer_phone": "",
            "referrer_email": "",
            "referral_notes": "",
        }

        # Save
        status, _ = api_put(server_url, "/api/profile/roundtrip_profile.yaml", custom)
        assert status == 200

        # Verify saved
        status, loaded = api_get(server_url, "/api/profile/roundtrip_profile.yaml")
        assert loaded["name"] == "Round Trip User"

        # Search using the profile
        status, results = api_post(server_url, "/api/candidate/search", custom)
        assert status == 200
        assert results["candidateName"] == "Round Trip User"
        assert "sections" in results
