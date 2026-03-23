"""Playwright browser E2E tests: real headless Chromium + mock server.

Tests exercise actual user flows: clicking buttons, filling forms,
verifying rendered output in the browser DOM.

Requires: playwright, pytest-playwright, chromium browser
"""
import re
import pytest
from playwright.sync_api import Page, expect


def _load_page(page: Page, server_url: str):
    """Navigate to the app and wait for init() to complete."""
    # Block external resources (Google Fonts, etc.) that can't be reached in CI
    page.route("**/*.googleapis.com/**", lambda route: route.abort())
    page.route("**/*.gstatic.com/**", lambda route: route.abort())
    page.goto(server_url, wait_until="domcontentloaded")
    # Wait for JS init() to populate the profile select with real profile options
    # The select starts with just "— select a profile —"; init() adds actual profiles.
    page.wait_for_function(
        "() => document.querySelector('#profile-select').options.length > 1",
        timeout=10000,
    )


def _load_profile(page: Page, server_url: str, filename: str = "test_user_profile.yaml"):
    """Navigate, wait for init, then load a specific profile."""
    _load_page(page, server_url)
    page.select_option("#profile-select", filename)
    # Wait for profile to load by checking the name field gets populated
    page.wait_for_function(
        "() => document.querySelector('#f-name').value.length > 0",
        timeout=5000,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Page initialisation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPageInit:
    def test_page_loads_without_errors(self, page: Page, server_url):
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        _load_page(page, server_url)
        page.wait_for_timeout(500)
        assert errors == [], f"JS errors on load: {errors}"

    def test_profile_select_populated(self, page: Page, server_url):
        _load_page(page, server_url)
        select = page.locator("#profile-select")
        options = select.locator("option")
        assert options.count() >= 1, "No profiles loaded into select"

    def test_location_chips_rendered(self, page: Page, server_url):
        _load_page(page, server_url)
        chips = page.locator("#loc-chips button")
        chips.first.wait_for(timeout=5000)
        assert chips.count() >= 5, "Location chips not rendered"

    def test_auth_status_shown(self, page: Page, server_url):
        _load_page(page, server_url)
        page.wait_for_timeout(500)
        auth = page.locator("#auth-status")
        expect(auth).not_to_be_empty()


# ═══════════════════════════════════════════════════════════════════════════════
# Profile loading
# ═══════════════════════════════════════════════════════════════════════════════

class TestProfileLoading:
    def test_load_profile_populates_name(self, page: Page, server_url):
        _load_profile(page, server_url)
        assert page.locator("#f-name").input_value() == "Test User"

    def test_load_profile_populates_locations(self, page: Page, server_url):
        _load_profile(page, server_url)
        active_chips = page.locator("#loc-chips button.active")
        assert active_chips.count() >= 2, "Locations not selected"

    def test_load_profile_populates_queries(self, page: Page, server_url):
        _load_profile(page, server_url)
        query_tags = page.locator("#tg-queries .tag-item")
        assert query_tags.count() >= 2, "Query tags not rendered"

    def test_load_profile_populates_boost_keywords(self, page: Page, server_url):
        _load_profile(page, server_url)
        strong_tags = page.locator("#tg-boost-strong .tag-item")
        assert strong_tags.count() >= 3, "Strong boost tags not rendered"

    def test_load_profile_populates_pages(self, page: Page, server_url):
        _load_profile(page, server_url)
        assert page.locator("#f-pages").input_value() == "1"


# ═══════════════════════════════════════════════════════════════════════════════
# Dirty state tracking
# ═══════════════════════════════════════════════════════════════════════════════

class TestDirtyState:
    def test_editing_name_marks_dirty(self, page: Page, server_url):
        _load_profile(page, server_url)
        page.fill("#f-name", "Modified Name")
        page.wait_for_timeout(200)
        save_btn = page.locator("#save-btn")
        assert not save_btn.is_disabled(), "Save button should be enabled after edit"

    def test_revert_restores_original(self, page: Page, server_url):
        _load_profile(page, server_url)
        page.fill("#f-name", "Modified Name")
        page.wait_for_timeout(200)
        page.click("#revert-btn")
        page.wait_for_timeout(300)
        assert page.locator("#f-name").input_value() == "Test User"


# ═══════════════════════════════════════════════════════════════════════════════
# Profile save
# ═══════════════════════════════════════════════════════════════════════════════

class TestProfileSave:
    def test_save_profile(self, page: Page, server_url):
        _load_profile(page, server_url)
        page.fill("#f-name", "Saved User")
        page.wait_for_timeout(200)

        with page.expect_response("**/api/profile/**") as resp_info:
            page.click("#save-btn")
        assert resp_info.value.status == 200

        page.wait_for_timeout(300)
        save_btn = page.locator("#save-btn")
        btn_text = save_btn.inner_text()
        assert "Saved" in btn_text or save_btn.is_disabled()

        # Restore original
        page.fill("#f-name", "Test User")
        page.wait_for_timeout(200)
        page.click("#save-btn")
        page.wait_for_timeout(500)


# ═══════════════════════════════════════════════════════════════════════════════
# Run search
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunSearch:
    def test_run_search_shows_results(self, page: Page, server_url):
        _load_profile(page, server_url)

        with page.expect_response("**/api/candidate/search") as resp_info:
            page.click("#run-btn")
        assert resp_info.value.status == 200

        page.wait_for_timeout(500)
        results = page.locator("#results-content")
        assert results.inner_text().strip() != "", "Results panel is empty"

    def test_search_results_contain_job_cards(self, page: Page, server_url):
        _load_profile(page, server_url)
        with page.expect_response("**/api/candidate/search"):
            page.click("#run-btn")
        page.wait_for_timeout(500)
        job_links = page.locator("#results-content a[href*='details']")
        assert job_links.count() >= 1, "No job card links in results"

    def test_search_results_show_scores(self, page: Page, server_url):
        _load_profile(page, server_url)
        with page.expect_response("**/api/candidate/search"):
            page.click("#run-btn")
        page.wait_for_timeout(500)
        results_text = page.locator("#results-content").inner_text()
        assert re.search(r"\d{2,3}", results_text), "No scores visible in results"

    def test_search_results_show_candidate_name(self, page: Page, server_url):
        _load_profile(page, server_url)
        with page.expect_response("**/api/candidate/search"):
            page.click("#run-btn")
        page.wait_for_timeout(500)
        results_text = page.locator("#results-content").inner_text()
        assert "Test User" in results_text

    def test_intern_jobs_filtered_out(self, page: Page, server_url):
        """Hard-penalty keyword 'intern' should filter out intern jobs."""
        _load_profile(page, server_url)
        with page.expect_response("**/api/candidate/search"):
            page.click("#run-btn")
        page.wait_for_timeout(500)
        results_text = page.locator("#results-content").inner_text().lower()
        assert "intern —" not in results_text and "intern–" not in results_text


# ═══════════════════════════════════════════════════════════════════════════════
# Stale banner
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaleBanner:
    def test_stale_banner_appears_after_search_param_edit(self, page: Page, server_url):
        _load_profile(page, server_url)
        with page.expect_response("**/api/candidate/search"):
            page.click("#run-btn")
        page.wait_for_timeout(1000)

        # Toggle a location chip (search-relevant field) to trigger staleness
        inactive_chip = page.locator("#loc-chips button:not(.active)").first
        inactive_chip.click()
        page.wait_for_timeout(500)

        # isStale() should detect the location change
        is_stale = page.evaluate("() => typeof isStale === 'function' ? isStale() : false")
        stale_visible = page.locator("#stale-bar").is_visible()
        assert is_stale or stale_visible, "Location change didn't trigger staleness"


# ═══════════════════════════════════════════════════════════════════════════════
# Location chip toggling
# ═══════════════════════════════════════════════════════════════════════════════

class TestLocationChips:
    def test_click_chip_toggles_active(self, page: Page, server_url):
        _load_profile(page, server_url)
        inactive_chip = page.locator("#loc-chips button:not(.active)").first
        chip_text = inactive_chip.inner_text()
        inactive_chip.click()
        page.wait_for_timeout(200)
        clicked_chip = page.locator(f"#loc-chips button.active:has-text('{chip_text}')")
        assert clicked_chip.count() >= 1, f"Chip '{chip_text}' not activated after click"


# ═══════════════════════════════════════════════════════════════════════════════
# Tag group interaction
# ═══════════════════════════════════════════════════════════════════════════════

class TestTagGroups:
    def test_add_tag_via_enter(self, page: Page, server_url):
        _load_profile(page, server_url)
        initial_count = page.locator("#tg-queries .tag-item").count()
        tag_input = page.locator("#tg-queries .tag-add")
        tag_input.fill("new test query")
        tag_input.press("Enter")
        page.wait_for_timeout(200)
        new_count = page.locator("#tg-queries .tag-item").count()
        assert new_count > initial_count, "Tag was not added"

    def test_remove_tag_via_x_button(self, page: Page, server_url):
        _load_profile(page, server_url)
        initial_html = page.locator("#tg-queries").inner_html()
        first_x = page.locator("#tg-queries .tag-item .x").first
        first_x.click()
        page.wait_for_timeout(300)
        new_html = page.locator("#tg-queries").inner_html()
        assert new_html != initial_html, "Tag group unchanged after remove click"

    def test_add_tag_via_comma(self, page: Page, server_url):
        _load_profile(page, server_url)
        initial_count = page.locator("#tg-boost-strong .tag-item").count()
        tag_input = page.locator("#tg-boost-strong .tag-add")
        tag_input.type("Rust,")
        page.wait_for_timeout(200)
        new_count = page.locator("#tg-boost-strong .tag-item").count()
        assert new_count == initial_count + 1, "Tag not added via comma"


# ═══════════════════════════════════════════════════════════════════════════════
# New profile form
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewProfileForm:
    def test_new_profile_form_opens(self, page: Page, server_url):
        _load_page(page, server_url)
        page.click("#new-profile-btn")
        page.wait_for_timeout(300)
        expect(page.locator("#new-profile-row")).to_be_visible()
        expect(page.locator("#profile-content")).to_be_hidden()

    def test_new_profile_cancel(self, page: Page, server_url):
        _load_page(page, server_url)
        page.click("#new-profile-btn")
        page.wait_for_timeout(300)
        page.click("#new-profile-cancel")
        page.wait_for_timeout(300)
        expect(page.locator("#new-profile-row")).to_be_hidden()
        expect(page.locator("#profile-content")).to_be_visible()


# ═══════════════════════════════════════════════════════════════════════════════
# Schedule / cron
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchedule:
    def test_cron_hint_updates(self, page: Page, server_url):
        _load_profile(page, server_url)
        cron_input = page.locator("#f-cron")
        cron_input.fill("30 14 * * *")
        cron_input.dispatch_event("input")
        page.wait_for_timeout(300)
        hint = page.locator("#cron-hint")
        hint_text = hint.inner_text()
        assert hint_text != "" and ("daily" in hint_text.lower() or ":" in hint_text), (
            f"Cron hint not updated: '{hint_text}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AI enhance button state
# ═══════════════════════════════════════════════════════════════════════════════

class TestAIButton:
    def test_enhance_button_disabled_initially(self, page: Page, server_url):
        _load_profile(page, server_url)
        ai_btn = page.locator("#ai-btn")
        assert ai_btn.is_disabled(), "AI button should be disabled without results or feedback"

    def test_enhance_button_enabled_with_feedback(self, page: Page, server_url):
        _load_profile(page, server_url)
        page.fill("#f-ai-message", "Focus more on backend roles")
        page.wait_for_timeout(300)
        ai_btn = page.locator("#ai-btn")
        assert not ai_btn.is_disabled(), "AI button should be enabled after typing feedback"


# ═══════════════════════════════════════════════════════════════════════════════
# Full round-trip flow: load → edit → search → verify results
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullFlow:
    def test_load_edit_search_flow(self, page: Page, server_url):
        _load_profile(page, server_url)
        assert page.locator("#f-name").input_value() == "Test User"

        with page.expect_response("**/api/candidate/search") as resp_info:
            page.click("#run-btn")
        assert resp_info.value.status == 200

        page.wait_for_timeout(500)
        results_text = page.locator("#results-content").inner_text()
        assert "Test User" in results_text
        assert len(results_text) > 100, "Results content seems too short"

        # Toggle a location to make results stale
        inactive_chip = page.locator("#loc-chips button:not(.active)").first
        inactive_chip.click()
        page.wait_for_timeout(500)
        is_stale = page.evaluate("() => typeof isStale === 'function' ? isStale() : false")
        assert is_stale, "Location toggle didn't trigger staleness"
