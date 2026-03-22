# open-reqs

Apple job search tool for employee referrals. Queries the `jobs.apple.com` API directly — no scraping, no third-party services.

---

## Quick start

```bash
# Search from the command line (no dependencies needed)
python apple_jobs.py

# Search for a specific role in specific locations
python apple_jobs.py -q "backend software engineer" -l SVL SCV

# Output as JSON for scripting
python apple_jobs.py -q "data analyst" --json

# Launch the web UI (dark-themed search interface)
python apple_jobs.py --serve
# Then open http://localhost:8080
```

## Candidate profile search

Run a multi-query, scored, deduplicated search tailored to a specific candidate. Each profile defines queries, boost/penalty keywords, preferred locations, and referral notes.

```bash
# Use the default profile (candidate_profile.yaml — Christine)
python apple_jobs.py --candidate

# Use a different profile
python apple_jobs.py --candidate --profile kevin_katz_profile.yaml

# Limit results and export JSON
python apple_jobs.py --candidate --limit 50 --json

# Send results as an HTML email digest
python apple_jobs.py --candidate --email user@example.com --cc referrer@example.com
```

### Candidate profiles

| File | Candidate | Target level | Locations |
|------|-----------|-------------|-----------|
| `candidate_profile.yaml` | Christine Ryan | Entry-level / early career | SCV, SVL, SJOS |
| `kevin_katz_profile.yaml` | Kevin Katz | Senior / experienced | CUL, IRV |
| `lauren_ernst_profile.yaml` | Lauren Ernst | — | — |
| `simone_donelly_profile.yaml` | Simone Donelly | — | — |
| `yunjian_lu_profile.yaml` | Yunjian Lu | — | — |

Profiles are YAML files with these sections:
- **queries** — search terms run against the Apple jobs API
- **boost_keywords** (strong / moderate / light) — terms that increase a job's relevance score
- **penalty_keywords** (hard / soft) — terms that decrease relevance
- **locations** — Apple location codes to search
- **referral_notes** — included in email digests

### GitHub Actions workflows

| Workflow | File | Schedule |
|----------|------|----------|
| Christine's Job Search | `.github/workflows/apple-job-search.yml` | Daily at 12:37 PM PT + manual dispatch |
| Kevin's Job Search | `.github/workflows/kevin-katz-job-search.yml` | Manual dispatch only |
| Lauren's Job Search | `.github/workflows/lauren-ernst-job-search.yml` | Manual dispatch only |
| Simone's Job Search | `.github/workflows/simone-donelly-job-search.yml` | Manual dispatch only |
| Yunjian's Job Search | `.github/workflows/yunjian-lu-job-search.yml` | Manual dispatch only |

When triggered manually, workflows present a **dropdown** for the email recipient — choose the candidate's email, the referrer's email, or "none" to skip sending.

Email sending requires these repository secrets: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`.

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

## Web UI

Run `python apple_jobs.py --serve` to start a local server that:
- Serves a self-contained search interface at `http://localhost:8080`
- Proxies API calls to `jobs.apple.com` (bypasses browser CORS restrictions)
- Shows results with Req IDs (click-to-select), team names, locations, and direct links

## Dependencies

No pip dependencies for basic CLI use. Install `pyyaml` for `--candidate` mode:

```bash
pip install pyyaml
```
