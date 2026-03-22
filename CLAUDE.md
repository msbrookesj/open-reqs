# CLAUDE.md — open-reqs

## Project overview

`open-reqs` is a Python CLI and web tool for searching open job listings on `jobs.apple.com`. It runs multi-query, scored, deduplicated candidate searches driven by YAML profile files. Results can be viewed in a local web UI, printed to the terminal, or emailed as an HTML digest.

## Architecture

### `open_reqs.py` — single-file backend

All logic lives here: job fetching, scoring, the web server, the AI enhancement function, and the CLI entry point.

Key functions:

| Function | Purpose |
|----------|---------|
| `search_jobs(query, location_keys, page)` | Fetches a search results page from jobs.apple.com, extracts embedded JSON |
| `fetch_job_details(req_id, slug)` | Fetches a single job detail page for second-pass scoring |
| `score_job(job)` | First-pass scoring using title/team/summary vs. profile keywords |
| `second_pass_score(detail)` | Second-pass scoring using full job text + experience-level signals |
| `_run_candidate_search_web(profile, limit)` | Full two-pass search for the web UI — returns categorized JSON |
| `_ai_enhance_profile(profile, results, message)` | Calls Claude Opus to propose profile improvements |
| `build_email_html(jobs, candidate_name)` | Builds the HTML email digest |
| `run_candidate_search(...)` | CLI candidate search — prints or emails results |
| `run_server(port)` | Starts the local proxy server with `ProxyHandler` |

### `web/index.html` — single-file frontend

Self-contained HTML/CSS/JS. No build step, no framework. Served by the Python proxy.

Key JS components:
- **`setupTagGroup` / `renderTagGroup`** — inline tag editor with dirty-state awareness (bold new, strikethrough removed, click-to-restore)
- **`markDirty` / `markClean` / `refreshDirtyDots`** — tracks unsaved changes per field; updates amber dots on section labels
- **`applyProfile(data)`** — loads profile data into all form fields; always called with the full raw YAML data so non-editable fields are preserved
- **`saveProfile()` / revert** — PUT to `/api/profile/<file>`; revert calls `applyProfile(loadedRawData)`
- **`runSearch(aiExplanation)`** — POSTs to `/api/candidate/search`, renders results
- **`aiEnhanceAndSearch()`** — POSTs to `/api/ai-enhance`, shows staged changes panel
- **`showStagedChanges` / `applyStagedChanges` / `dismissStagedChanges`** — consent flow for AI proposals
- **`buildProfileDiff` / `renderDiffHtml`** — generates the field-by-field diff shown in the staged panel
- **`updateAiBtn()`** — enables/disables and relabels the Enhance button based on whether results exist and whether feedback was typed
- **`generateFromResume()` / `createBlankProfile()`** — new-profile form: calls `/api/profile/generate` (Claude CLI) or creates a blank YAML; POSTs to `/api/profile/<file>` and loads the result
- **`handleResumeFile(file)`** — reads a dropped/selected PDF or .txt file; POSTs to `/api/profile/extract-pdf` for PDFs, reads directly for .txt; populates the resume textarea
- **`fetchWorkflowInfo(filename)`** — GETs `/api/workflow/<file>`, populates the cron field and calls `updateCronHint()`
- **`cronToLocalTimeStr(cronExpr)` / `updateCronHint()`** — parses a `minute hour * * *` expression and displays the equivalent local time using `Date.toLocaleTimeString()`; updates live as the user types
- **`saveSchedule()`** — PUTs to `/api/workflow/<file>` with the cron string; creates or patches the GitHub Actions workflow file
- **`refreshGitStatus()`** — GETs `/api/git/status`, populates the topbar git indicator (modified files / commits ahead)
- **`gitDeploy()`** — POSTs to `/api/git/deploy`; stages profile YAMLs + workflow files, commits, and pushes to `origin/main`

### API endpoints (served by `ProxyHandler`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/locations` | Returns `{code: label}` map |
| GET | `/api/profiles` | Lists `*_profile.yaml` files in repo root |
| GET | `/api/profile/<file>` | Returns parsed YAML for a profile |
| PUT | `/api/profile/<file>` | Writes updated profile to disk |
| POST | `/api/profile/generate` | Generates a new profile YAML from resume text via Claude CLI |
| POST | `/api/profile/extract-pdf` | Extracts text from an uploaded PDF (requires `pypdf`) |
| GET | `/api/workflow/<file>` | Returns `{exists, cron}` for the associated GitHub Actions workflow |
| PUT | `/api/workflow/<file>` | Patches the cron expression in (or creates) the workflow file |
| POST | `/api/candidate/search` | Runs full candidate search, returns categorized JSON |
| POST | `/api/ai-enhance` | Calls Claude to propose profile improvements |
| POST | `/api/role/search` | Single-query search (legacy) |
| GET | `/api/git/status` | Returns `{changedFiles, commitsAhead}` for profile/workflow files |
| POST | `/api/git/deploy` | Stages profile YAMLs + workflow files, commits, pushes to `origin/main` |

### Candidate profile YAML structure

```yaml
name: "Full Name"
email: "candidate@example.com"
locations: [SCV, SVL]
queries:
  - "software engineer"
pages_per_query: 3
boost_keywords:
  strong: [Python, Swift]
  moderate: [machine learning]
  light: [data visualization]
penalty_keywords:
  hard: [senior, lead, manager]
  soft: [hardware]
referrer_name: "Referrer Name"
referrer_phone: "+1 (408) 555-0100"
referrer_email: "referrer@example.com"
referral_notes: "Notes shown in email digest."
base_url: "https://jobs.apple.com"   # optional override
```

## SSL / corporate proxy

The tool bypasses SSL certificate verification to work in corporate proxy environments that intercept HTTPS traffic. This is handled at the module level via `_SSL_CTX` (created once, passed to every `urlopen` call).

## Parallelism

Both the web search (`_run_candidate_search_web`) and the CLI search (`run_candidate_search`) use `ThreadPoolExecutor` with `submit` + `as_completed` for parallel query execution. The second-pass detail fetch also uses a thread pool (`executor.map`).

## AI Enhancement

All Claude calls go through `_run_via_claude_cli(prompt)` — a subprocess wrapper that invokes the local `claude` CLI (`claude -p --output-format json`). No Anthropic SDK dependency at runtime.

- **`_ai_enhance_profile(profile, results, message)`** — sends a compact profile summary + up to 30 top job results + optional user feedback; expects `{explanation, profile}` JSON back
- **`_generate_profile_from_resume(name, resume_text)`** — sends name + resume text; expects a fully populated profile YAML dict + explanation

## Workflow management

- **`_workflow_slug(profile_filename)`** — maps `kevin_katz_profile.yaml` → `kevin-katz`
- **`_workflow_path(profile_filename)`** — returns `.github/workflows/<slug>-job-search.yml`
- **`_get_workflow_info(profile_filename)`** — reads the workflow file and extracts the cron expression via regex
- **`_write_workflow(profile_filename, profile, cron)`** — if the file exists, patches only the cron line; if new, fills `_WORKFLOW_TEMPLATE` using `@@PLACEHOLDER@@` substitution (avoids conflicts with `${{ }}` GitHub Actions syntax)

## Git deploy

- **`_git_status()`** — runs `git status --porcelain` + `git rev-list @{u}..HEAD --count`; returns `{changedFiles, commitsAhead}`
- **`_git_deploy()`** — globs `*_profile.yaml` and `.github/workflows/*-job-search.yml`, stages them, commits, and pushes; never stages unrelated files

## Conventions

- All profile reads/writes go through `loadedRawData` in the frontend — the full original YAML object is preserved on load and merged on save, so fields not shown in the UI (base_url, etc.) are never lost.
- The global `CANDIDATE_PROFILE` in Python is swapped temporarily inside `_run_candidate_search_web` so scoring functions pick up the correct profile without threading issues (restored in a `finally` block).
- GitHub Actions workflows only install `pyyaml` — all AI and git features are web-UI-only and not needed in CI.
- Cron schedules are always UTC. The web UI converts to the user's local timezone dynamically via `Date.toLocaleTimeString()` — never hardcode a timezone in the hint text.
