"""HTTP-level tests for the web UI: page loads, DOM structure, JS presence."""
import re

from tests.conftest import api_get

import http.client as _http_client
import urllib.parse


def _fetch_html(server_url: str, path: str = "/") -> tuple[int, str]:
    """GET raw HTML from the server."""
    parsed = urllib.parse.urlparse(f"{server_url}{path}")
    conn = _http_client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    conn.request("GET", parsed.path or "/")
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp.status, body


class TestPageLoad:
    def test_index_returns_200(self, server_url):
        status, _ = _fetch_html(server_url, "/")
        assert status == 200

    def test_index_is_html(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert "<!DOCTYPE html>" in html or "<html" in html

    def test_page_title(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert "<title>" in html


class TestDOMElements:
    """Verify all critical form elements and containers exist in the HTML."""

    def test_profile_selector(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="profile-select"' in html

    def test_control_buttons(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="save-btn"' in html
        assert 'id="revert-btn"' in html
        assert 'id="run-btn"' in html
        assert 'id="new-profile-btn"' in html

    def test_candidate_fields(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="f-name"' in html
        assert 'id="f-email"' in html
        assert 'id="f-pages"' in html

    def test_location_chips_container(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="loc-chips"' in html

    def test_tag_groups(self, server_url):
        _, html = _fetch_html(server_url, "/")
        for tg_id in ["tg-queries", "tg-boost-strong", "tg-boost-moderate",
                       "tg-boost-light", "tg-penalty-hard", "tg-penalty-soft"]:
            assert f'id="{tg_id}"' in html, f"Missing tag group: {tg_id}"

    def test_dirty_dots(self, server_url):
        _, html = _fetch_html(server_url, "/")
        for dot_id in ["fdot-name", "fdot-loc", "fdot-queries", "fdot-boost",
                        "fdot-penalty", "fdot-settings", "fdot-referrer",
                        "fdot-notes", "fdot-email"]:
            assert f'id="{dot_id}"' in html, f"Missing dirty dot: {dot_id}"

    def test_referrer_fields(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="f-ref-name"' in html
        assert 'id="f-ref-phone"' in html
        assert 'id="f-ref-email"' in html
        assert 'id="f-notes"' in html

    def test_ai_section(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="ai-btn"' in html
        assert 'id="f-ai-message"' in html
        assert 'id="staged-panel"' in html
        assert 'id="auth-status"' in html

    def test_schedule_section(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="f-cron"' in html
        assert 'id="cron-hint"' in html
        assert 'id="schedule-save-btn"' in html

    def test_results_panel(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="results-panel"' in html
        assert 'id="results-content"' in html
        assert 'id="stale-bar"' in html

    def test_git_bar(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="git-bar"' in html

    def test_new_profile_form(self, server_url):
        _, html = _fetch_html(server_url, "/")
        assert 'id="new-profile-row"' in html
        assert 'id="new-profile-resume"' in html
        assert 'id="new-profile-generate"' in html
        assert 'id="new-profile-blank"' in html
        assert 'id="new-profile-cancel"' in html


class TestJSFunctions:
    """Verify that key JavaScript functions are defined in the page."""

    def test_core_functions(self, server_url):
        _, html = _fetch_html(server_url, "/")
        for fn in ["applyProfile", "loadProfile", "saveProfile",
                    "runSearch", "renderResults", "markDirty", "markClean"]:
            assert f"function {fn}" in html or f"{fn}=" in html, (
                f"JS function '{fn}' not found"
            )

    def test_tag_group_functions(self, server_url):
        _, html = _fetch_html(server_url, "/")
        for fn in ["setupTagGroup", "renderTagGroup", "renderLocChips"]:
            assert f"function {fn}" in html or f"{fn}=" in html, (
                f"JS function '{fn}' not found"
            )

    def test_ai_functions(self, server_url):
        _, html = _fetch_html(server_url, "/")
        for fn in ["aiEnhanceAndSearch", "showStagedChanges",
                    "applyStagedChanges", "dismissStagedChanges",
                    "buildProfileDiff", "renderDiffHtml"]:
            assert f"function {fn}" in html or f"{fn}=" in html, (
                f"JS function '{fn}' not found"
            )

    def test_schedule_functions(self, server_url):
        _, html = _fetch_html(server_url, "/")
        for fn in ["cronToLocalTimeStr", "updateCronHint",
                    "fetchWorkflowInfo", "saveSchedule"]:
            assert f"function {fn}" in html or f"{fn}=" in html, (
                f"JS function '{fn}' not found"
            )

    def test_git_functions(self, server_url):
        _, html = _fetch_html(server_url, "/")
        for fn in ["refreshGitStatus", "gitDeploy"]:
            assert f"function {fn}" in html or f"{fn}=" in html, (
                f"JS function '{fn}' not found"
            )

    def test_new_profile_functions(self, server_url):
        _, html = _fetch_html(server_url, "/")
        for fn in ["createBlankProfile", "generateFromResume", "handleResumeFile"]:
            assert f"function {fn}" in html or f"{fn}=" in html, (
                f"JS function '{fn}' not found"
            )


class TestAPIEndpointWiring:
    """Verify that the JS references the correct API paths."""

    def test_api_paths_in_js(self, server_url):
        _, html = _fetch_html(server_url, "/")
        expected_paths = [
            "/api/locations",
            "/api/profiles",
            "/api/profile/",
            "/api/candidate/search",
            "/api/ai-enhance",
            "/api/workflow/",
            "/api/git/status",
            "/api/git/deploy",
            "/api/auth/status",
        ]
        for path in expected_paths:
            assert path in html, f"API path '{path}' not referenced in HTML/JS"

    def test_fetch_methods(self, server_url):
        """The JS should use POST for search and PUT for saves."""
        _, html = _fetch_html(server_url, "/")
        assert "method:'POST'" in html.replace(" ", "") or 'method:"POST"' in html or "method: 'POST'" in html
        assert "method:'PUT'" in html.replace(" ", "") or 'method:"PUT"' in html or "method: 'PUT'" in html
