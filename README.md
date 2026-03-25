# open-reqs

Tool for searching open job reqs on `jobs.apple.com`. Runs multi-query, scored, deduplicated candidate searches from the command line or a local web UI — no scraping, no third-party services.

---

## Quick start

```bash
# 1. Install Claude Code (required for AI features)
#    Create a free account at https://claude.ai/ if you don't have one.
#    Sign in with that account below — no API key needed or wanted
#    (API keys charge per request; the claude.ai account is free/subscription).
npm install -g @anthropic-ai/claude-code
export PATH="$(npm prefix -g)/bin:$PATH"  # ensure claude is on PATH in this session
claude auth login  # opens browser to sign in with your claude.ai account; exits when complete

# 2. Install Python dependencies
pip3 install -r requirements.txt

# 3. Start the web UI
python3 open_reqs.py --serve
# Then open http://localhost:8080
```

---

## Web UI

Run `python3 open_reqs.py --serve` to start a local proxy server. The UI is a two-column layout: a profile editor sidebar on the left and a scored results panel on the right.

### Profile editor (sidebar)

- **Load Profile** — select any `*_profile.yaml` file from the `profiles/` directory
- **+ New** — create a new profile. Enter a name, optionally paste a resume (or drop a PDF/txt file), then click **Generate with Claude →** for an AI-generated profile or **Create blank** for an empty one
- **Save** — writes changes back to the YAML file; enabled only when there are unsaved changes
- **Revert** — discards all unsaved edits and restores the last saved state; enabled only when dirty
- **Dirty indicators** — a small amber dot appears next to any section label whose fields differ from the saved state
- **Tag groups** — Search Queries, Boost Keywords, and Penalty Keywords are editable inline tag inputs. New keywords (not yet saved) render **bold** at the top; removed keywords appear with ~~strikethrough~~ at the bottom and can be clicked to restore them.
- **Email & Notifications** — candidate email and referrer email fields; saved to the profile YAML and used by GitHub Actions workflows
- **Schedule** — configure the cron expression for the associated GitHub Actions workflow. The hint text shows the equivalent time in your local timezone (updates live as you type). Click **Save Schedule** to write the change to the workflow file; the top bar shows the deployment status

### AI Enhanced Search

Uses the locally installed `claude` CLI to analyze the current profile (and optionally the most recent search results) and propose improvements. Requires [Claude Code](https://claude.ai/download) to be installed and signed in.

1. Optionally type guidance in the feedback box (e.g. "too many senior roles, focus more on data")
2. Click **Enhance** (no prior results) or **Enhance from Results** (after a search) — the button is disabled until one of those conditions is met
3. Claude returns a **Proposed Changes** panel showing:
   - A plain-English explanation of what changed and why
   - A field-by-field diff (`+ added` / `− removed`) for every changed section
4. **Apply** applies the changes to the profile (marks it dirty)
5. **Discard** (or ✕) throws the proposal away — nothing changes

Applied changes are never auto-saved. Review the diff in the tag groups, then Save explicitly.

### Deploy to GitHub (git status bar)

The top bar shows a git status indicator for profile and workflow files:

- **✓ deployed** — all saved changes are live on GitHub Actions
- **● N files modified / ↑ N ahead** — there are local changes or committed-but-not-pushed commits
- **Deploy →** — stages all profile YAMLs and workflow files, commits with an auto-message, and pushes to `origin/main`. This makes schedule changes take effect on GitHub Actions.

### Running a search

Click **Run Search →** in the top bar at any time. The search always uses the current working profile, including any unsaved edits. A progress bar with rotating encouraging phrases fills while queries run in parallel.

Results are rendered like the email digest: header stats, a collapsible candidate profile summary, and job cards grouped into **Posted Today**, **Posted This Week**, and **All Open Positions**. Each card shows a relevance score (0–100), experience level badge, and the matched detail reasons from the second-pass fetch.

---

## Candidate profile search (CLI)

Run a multi-query, scored, deduplicated search from the command line.

```bash
# Use the default profile (candidate_profile.yaml)
python3 open_reqs.py --candidate

# Use a specific profile
python3 open_reqs.py --candidate --profile profiles/brooke_ryan_profile.yaml

# Limit results and export JSON
python3 open_reqs.py --candidate --limit 50 --json

# Send results as an HTML email digest
python3 open_reqs.py --candidate --email user@example.com --cc contact@example.com
```

### Candidate profiles

| File | Candidate | Target level | Locations |
|------|-----------|-------------|-----------|
| `profiles/brooke_ryan_profile.yaml` | Brooke Ryan | Senior / experienced | SCV, SVL, SJOS |

Profile YAML fields:

| Field | Description |
|-------|-------------|
| `name` | Candidate full name |
| `email` | Candidate email address |
| `locations` | List of location codes to search |
| `queries` | Search terms run against the jobs API |
| `boost_keywords.strong` | Confirmed skills — largest score boost |
| `boost_keywords.moderate` | Coursework / resume items — moderate boost |
| `boost_keywords.light` | Adjacent interests — small boost |
| `penalty_keywords.hard` | Disqualifiers — large penalty |
| `penalty_keywords.soft` | Mild penalties |
| `pages_per_query` | Number of result pages to fetch per query (default: 3) |
| `referrer_name` | Name of the referring employee |
| `referrer_phone` | Referrer's phone number (used for SMS link in email) |
| `referrer_email` | Referrer's email (used as Reply-To in email) |
| `referral_notes` | Notes included in the email digest |
| `base_url` | Override the jobs site base URL (default: `https://jobs.apple.com`) |

---

## GitHub Actions workflows

Each candidate has a workflow that can run the search and optionally email results.

| Workflow | File | Schedule |
|----------|------|----------|
| Brooke's Job Search | `.github/workflows/brooke-ryan-job-search.yml` | Daily at 7:00 AM PT + manual |

When triggered manually, a dropdown lets you choose the email recipient (candidate, referrer, or none).

Email sending requires these repository secrets: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`.

---

## Location codes

Location codes come from `jobs.apple.com`. The following are common examples; more may need to be added:

| Code | Location |
|------|----------|
| SCV  | Santa Clara Valley / Cupertino |
| SVL  | Sunnyvale |
| SJOS | Campbell / San Jose |
| USA  | All US |
| AUS  | Austin |
| SEA  | Seattle |
| NYC  | New York City |
| SDG  | San Diego |
| CUL  | Culver City |
| IRV  | Irvine |

---

## Scoring

Jobs are scored in two passes:

1. **First pass** — title, team name, and summary text are matched against boost and penalty keywords. Each strong boost adds 15 points, moderate adds 8, light adds 3. Hard penalties subtract 30, soft penalties subtract 10.
2. **Second pass** — full job detail pages are fetched for the top candidates. Minimum qualifications text is scanned for additional keyword matches and experience-level signals (entry-level vs. senior). The score is adjusted up or down based on the candidate's target level preference.

Jobs below the minimum score threshold are filtered out before display.

---

## Dependencies

```bash
pip3 install -r requirements.txt
```

| Package | Required for |
|---------|-------------|
| `pyyaml` | Candidate profile mode (`--candidate`, `--serve`) |
| `anthropic` | (unused; retained for legacy imports) |
| `pypdf` | PDF text extraction in the **+ New** profile form |

If `pypdf` is not installed, PDF upload in the new-profile form returns an error; paste-text still works. All other features are unaffected.
