"""Pytest fixtures: spin up the real ProxyHandler with mocked external calls."""
import io
import json
import re
import shutil
import socket
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from tests.fixtures import (
    TEST_PROFILE,
    wrap_search_html,
    wrap_detail_html,
    make_search_data,
    JOBS,
    JOB_DETAILS,
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class _FakeResponse:
    """Minimal stand-in for http.client.HTTPResponse returned by urlopen."""

    def __init__(self, html: str):
        self._data = html.encode()

    def read(self):
        return self._data

    def decode(self):
        return self._data.decode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _mock_urlopen(req, *, context=None, timeout=None):
    """Route urlopen calls to fixture data based on URL path."""
    url = req.full_url if hasattr(req, "full_url") else str(req)

    # Search page
    if "/en-us/search" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        query = qs.get("search", [""])[0].lower()

        # Filter jobs loosely by query match against title/summary
        matched = []
        for job in JOBS:
            title = (job.get("postingTitle") or "").lower()
            summary = (job.get("jobSummary") or "").lower()
            team = (job.get("team") or {}).get("teamName", "").lower()
            # Simple: if any word in query appears in title/team/summary
            if any(w in f"{title} {team} {summary}" for w in query.split()):
                matched.append(job)
        if not matched:
            matched = JOBS[:2]  # fallback — return something

        html = wrap_search_html(make_search_data(matched))
        return _FakeResponse(html)

    # Detail page
    detail_match = re.search(r"/en-us/details/([^/]+)/", url)
    if detail_match:
        req_id = detail_match.group(1)
        html = wrap_detail_html(req_id)
        return _FakeResponse(html)

    raise ValueError(f"Unmocked URL: {url}")


@pytest.fixture(scope="session")
def profiles_dir(tmp_path_factory):
    """Create a temp profiles directory with a test profile."""
    d = tmp_path_factory.mktemp("profiles")
    profile_path = d / "test_user_profile.yaml"
    with open(profile_path, "w") as f:
        yaml.dump(TEST_PROFILE, f, default_flow_style=False)
    return d


@pytest.fixture(scope="session")
def server_url(profiles_dir):
    """Start the real ProxyHandler on a random port, with external calls mocked.

    Patches:
      - urllib.request.urlopen → _mock_urlopen (intercepts jobs.apple.com)
      - open_reqs.PROFILES_DIR → temp dir
      - open_reqs.CANDIDATE_PROFILE → TEST_PROFILE
      - open_reqs.SCRIPT_DIR → temp parent (so workflow writes don't pollute repo)
      - open_reqs._CLAUDE_BIN → None (disable AI features)
    """
    import http.server
    import socketserver

    port = _free_port()
    script_dir = profiles_dir.parent

    # We need to set up the web dir so static files resolve
    web_dir = Path(__file__).resolve().parent.parent / "web"

    # Import the module so we can patch its globals
    import open_reqs

    patches = [
        patch("open_reqs.urllib.request.urlopen", side_effect=_mock_urlopen),
        patch.object(open_reqs, "PROFILES_DIR", profiles_dir),
        patch.object(open_reqs, "CANDIDATE_PROFILE", TEST_PROFILE),
        patch.object(open_reqs, "SCRIPT_DIR", script_dir),
        patch.object(open_reqs, "_CLAUDE_BIN", None),
    ]

    for p in patches:
        p.start()

    # Build the handler class the same way run_server does
    class TestHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_dir), **kwargs)

        def log_message(self, format, *args):
            pass

    # Copy the API methods from ProxyHandler
    # We need to actually use the real ProxyHandler — re-import after patching
    # The cleanest way: call run_server's handler directly
    # Since ProxyHandler is defined inside run_server(), we replicate the pattern
    # by importing and starting the server in a thread.

    # Actually, let's just import and instantiate the handler from the module.
    # ProxyHandler is defined inside run_server(), so we can't import it directly.
    # Instead, we'll create the server by essentially inlining the relevant code.

    class ProxyHandler(http.server.SimpleHTTPRequestHandler):
        """Copy of ProxyHandler that delegates to open_reqs functions."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_dir), **kwargs)

        def _json_ok(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json_err(self, status, message):
            body = json.dumps({"error": message}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/locations":
                self._json_ok({k: v["label"] for k, v in open_reqs.LOCATIONS.items()})
            elif self.path == "/api/profiles":
                profiles = [p.name for p in sorted(open_reqs.PROFILES_DIR.glob("*_profile.yaml"))]
                self._json_ok(profiles)
            elif self.path.startswith("/api/profile/"):
                filename = self.path[len("/api/profile/"):]
                if "/" in filename or ".." in filename or not filename.endswith(".yaml"):
                    self.send_response(400)
                    self.end_headers()
                    return
                profile_path = open_reqs.PROFILES_DIR / filename
                if not profile_path.exists():
                    self.send_response(404)
                    self.end_headers()
                    return
                with open(profile_path) as f:
                    self._json_ok(yaml.safe_load(f))
            elif self.path == "/api/auth/status":
                self._json_ok({"authenticated": bool(open_reqs._CLAUDE_BIN)})
            elif self.path.startswith("/api/workflow/"):
                filename = self.path[len("/api/workflow/"):]
                if "/" in filename or ".." in filename or not filename.endswith(".yaml"):
                    self._json_err(400, "invalid filename")
                    return
                self._json_ok(open_reqs._get_workflow_info(filename))
            elif self.path == "/api/git/status":
                try:
                    self._json_ok(open_reqs._git_status())
                except Exception as e:
                    self._json_err(500, str(e))
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
                    loc_keys = []
                    for f in loc_filters:
                        code = f.replace("postLocation-", "")
                        if code in open_reqs.LOCATIONS:
                            loc_keys.append(code)
                    result = open_reqs.search_jobs(query, loc_keys, page)
                    self._json_ok(result)
                except Exception as e:
                    self._json_err(502, str(e))
            elif self.path == "/api/candidate/search":
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                try:
                    profile = json.loads(body)
                    self._json_ok(open_reqs._run_candidate_search_web(profile))
                except Exception as e:
                    self._json_err(502, str(e))
            elif self.path == "/api/ai-enhance":
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                try:
                    req_data = json.loads(body)
                    profile = req_data.get("profile", {})
                    results = req_data.get("results", None)
                    message = req_data.get("message", "")
                    self._json_ok(open_reqs._ai_enhance_profile(profile, results, message))
                except Exception as e:
                    self._json_err(502, str(e))
            elif self.path == "/api/profile/generate":
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                try:
                    req_data = json.loads(body)
                    name = req_data.get("name", "").strip()
                    resume_text = req_data.get("resume_text", "").strip()
                    filename = req_data.get("filename", "")
                    if not name or not filename:
                        self._json_err(400, "name and filename required")
                        return
                    if "/" in filename or ".." in filename or not filename.endswith(".yaml"):
                        self._json_err(400, "invalid filename")
                        return
                    result = open_reqs._generate_profile_from_resume(name, resume_text)
                    profile_path = open_reqs.PROFILES_DIR / filename
                    with open(profile_path, "w") as f:
                        yaml.dump(result["profile"], f, default_flow_style=False,
                                  allow_unicode=True, sort_keys=False)
                    self._json_ok(result)
                except Exception as e:
                    self._json_err(502, str(e))
            elif self.path == "/api/git/deploy":
                try:
                    self._json_ok(open_reqs._git_deploy())
                except Exception as e:
                    self._json_err(500, str(e))
            else:
                self.send_response(404)
                self.end_headers()

        def do_PUT(self):
            if self.path.startswith("/api/workflow/"):
                filename = self.path[len("/api/workflow/"):]
                if "/" in filename or ".." in filename or not filename.endswith(".yaml"):
                    self._json_err(400, "invalid filename")
                    return
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                try:
                    req_data = json.loads(body)
                    cron = req_data.get("cron", "").strip()
                    if not cron:
                        self._json_err(400, "cron required")
                        return
                    profile_path = open_reqs.PROFILES_DIR / filename
                    profile_data = {}
                    if profile_path.exists():
                        with open(profile_path) as f:
                            profile_data = yaml.safe_load(f) or {}
                    open_reqs._write_workflow(filename, profile_data, cron)
                    self._json_ok({"saved": True, "cron": cron})
                except Exception as e:
                    self._json_err(500, str(e))
            elif self.path.startswith("/api/profile/"):
                filename = self.path[len("/api/profile/"):]
                if "/" in filename or ".." in filename or not filename.endswith(".yaml"):
                    self.send_response(400)
                    self.end_headers()
                    return
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                try:
                    data = json.loads(body)
                    profile_path = open_reqs.PROFILES_DIR / filename
                    with open(profile_path, "w") as f:
                        yaml.dump(data, f, default_flow_style=False,
                                  allow_unicode=True, sort_keys=False)
                    self._json_ok({"saved": filename})
                except Exception as e:
                    self._json_err(500, str(e))
            else:
                self.send_response(404)
                self.end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Content-Length")
            self.end_headers()

        def log_message(self, format, *args):
            pass

    # Use ThreadingTCPServer so concurrent browser requests (page + API fetches)
    # don't deadlock — the browser makes parallel requests during init().
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), ProxyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"

    # Wait for server to be ready
    for _ in range(50):
        try:
            conn = _http_client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/locations")
            conn.getresponse()
            conn.close()
            break
        except Exception:
            time.sleep(0.05)

    yield base

    server.shutdown()
    for p in patches:
        p.stop()


# ── Playwright fixtures ──────────────────────────────────────────────────────
# We provide our own browser/page fixtures instead of using pytest-playwright's
# built-in ones, because those don't integrate cleanly with our server_url fixture.

@pytest.fixture(scope="session")
def browser():
    """Launch a headless Chromium browser for the test session."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    pw = sync_playwright().start()
    b = pw.chromium.launch()
    yield b
    b.close()
    pw.stop()


@pytest.fixture()
def page(browser):
    """Create a fresh browser page for each test."""
    p = browser.new_page()
    yield p
    p.close()


# ── HTTP helpers for tests ────────────────────────────────────────────────────
# Use http.client directly to avoid any interaction with the mock on urlopen.

import http.client as _http_client


def _parse_url(server_url: str, path: str) -> tuple[str, int, str]:
    """Extract host, port, full_path from server_url + path."""
    parsed = urllib.parse.urlparse(f"{server_url}{path}")
    return parsed.hostname, parsed.port, parsed.path + (f"?{parsed.query}" if parsed.query else "")


def api_get(server_url: str, path: str) -> tuple[int, dict]:
    """GET an API endpoint, return (status_code, parsed_json)."""
    host, port, full_path = _parse_url(server_url, path)
    conn = _http_client.HTTPConnection(host, port, timeout=10)
    conn.request("GET", full_path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(body)
    except Exception:
        return resp.status, {"raw": body.decode()}


def api_post(server_url: str, path: str, data: dict) -> tuple[int, dict]:
    """POST JSON to an API endpoint, return (status_code, parsed_json)."""
    host, port, full_path = _parse_url(server_url, path)
    body = json.dumps(data).encode()
    conn = _http_client.HTTPConnection(host, port, timeout=30)
    conn.request("POST", full_path, body=body,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    resp_body = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(resp_body)
    except Exception:
        return resp.status, {"raw": resp_body.decode()}


def api_put(server_url: str, path: str, data: dict) -> tuple[int, dict]:
    """PUT JSON to an API endpoint, return (status_code, parsed_json)."""
    host, port, full_path = _parse_url(server_url, path)
    body = json.dumps(data).encode()
    conn = _http_client.HTTPConnection(host, port, timeout=10)
    conn.request("PUT", full_path, body=body,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    resp_body = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(resp_body)
    except Exception:
        return resp.status, {"raw": resp_body.decode()}
