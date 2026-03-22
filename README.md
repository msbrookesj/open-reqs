# open-reqs

Tool for searching open job reqs on `jobs.apple.com`. Runs multi-query, scored, deduplicated candidate searches from the command line or a local web UI — no scraping, no third-party services.

---

## Quick start

```bash
pip install -r requirements.txt

# Search from the command line
python open_reqs.py

# Search for a specific role in specific locations
python open_reqs.py -q "backend software engineer" -l SVL SCV

# Output as JSON for scripting
python open_reqs.py -q "data analyst" --json

# Launch the web UI
python open_reqs.py --serve
# Then open http://localhost:8080
```

---

## Web UI

Run `python open_reqs.py --serve` to start a local proxy server. The UI is a two-column layout: a profile editor sidebar on the left and a scored results panel on the right.

### Profile editor (sidebar)

- **Load Profile** — select any `*_profile.yaml` file from the repo root
- **Save** — writes changes back to the YAML file; enabled only when there are unsaved changes
- **Revert** — discards all unsaved edits and restores the last saved state; enabled only when dirty
- **Dirty indicators** — a small amber dot appears next to any section label whose fields differ from the saved state
- **Tag groups** — Search Queries, Boost Keywords, and Penalty Keywords are editable inline tag inputs. New keywords (not yet saved) render **bold** at the top; removed keywords appear with ~~strikethrough~~ at the bottom and can be clicked to restore them.

### AI Enhanced Search

Uses Claude Opus to analyze the current profile (and optionally the most recent search results) and propose improvements. Requires `ANTHROPIC_API_KEY` in the environment and `pip install anthropic`.

1. Optionally type guidance in the feedback box (e.g. "too many senior roles, focus more on data")
2. Click **Enhance** (no prior results) or **Enhance from Results** (after a search) — the button is disabled until one of those conditions is met
3. Claude returns a **Proposed Changes** panel showing:
   - A plain-English explanation of what changed and why
   - A field-by-field diff (`+ added` / `− removed`) for every changed section
4. **Apply & Search →** applies the changes to the profile (marks it dirty), then runs a full search
5. **Discard** (or ✕) throws the proposal away — nothing changes

Applied changes are never auto-saved. Review the diff in the tag groups, then Save explicitly.

### Running a search

Click **Run Search →** in the top bar at any time. The search always uses the current working profile, including any unsaved edits. A progress bar with rotating encouraging phrases fills while queries run in parallel.

Results are rendered like the email digest: header stats, a collapsible candidate profile summary, and job cards grouped into **Posted Today**, **Posted This Week**, and **All Open Positions**. Each card shows a relevance score (0–100), experience level badge, and the matched detail reasons from the second-pass fetch.

---

## Candidate profile search (CLI)

Run a multi-query, scored, deduplicated search from the command line.

```bash
# Use the default profile (candidate_profile.yaml)
python open_reqs.py --candidate

# Use a specific profile
python open_reqs.py --candidate --profile kevin_katz_profile.yaml

# Limit results and export JSON
python open_reqs.py --candidate --limit 50 --json

# Send results as an HTML email digest
python open_reqs.py --candidate --email user@example.com --cc contact@example.com
```

### Candidate profiles

| File | Candidate | Target level | Locations |
|------|-----------|-------------|-----------|
| `candidate_profile.yaml` | Christine Ryan | Entry-level / early career | SCV, SVL, SJOS |
| `kevin_katz_profile.yaml` | Kevin Katz | Senior / experienced | CUL, IRV |
| `lauren_ernst_profile.yaml` | Lauren Ernst | — | — |
| `simone_donelly_profile.yaml` | Simone Donelly | — | — |
| `yunjian_lu_profile.yaml` | Yunjian Lu | — | — |

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
| Christine's Job Search | `.github/workflows/christine-job-search.yml` | Daily at 12:37 PM PT + manual |
| Kevin's Job Search | `.github/workflows/kevin-katz-job-search.yml` | Manual |
| Lauren's Job Search | `.github/workflows/lauren-ernst-job-search.yml` | Manual |
| Simone's Job Search | `.github/workflows/simone-donelly-job-search.yml` | Manual |
| Yunjian's Job Search | `.github/workflows/yunjian-lu-job-search.yml` | Manual |

When triggered manually, a dropdown lets you choose the email recipient (candidate, referrer, or none).

Email sending requires these repository secrets: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`.

---

## Location codes

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
pip install -r requirements.txt
```

| Package | Required for |
|---------|-------------|
| `pyyaml` | Candidate profile mode (`--candidate`, `--serve`) |
| `anthropic` | AI Enhanced Search in the web UI |

If `anthropic` is not installed, the server still starts and all other features work. A warning is printed at startup and the Enhance button returns an error if clicked.
