#!/usr/bin/env python3
"""Generate a sample email digest HTML for visual testing."""

import sys
import os
from datetime import datetime, timedelta, timezone
import yaml

# Make sure we can import open_reqs from the project root
sys.path.insert(0, os.path.dirname(__file__))

import open_reqs

# Load a real profile so the email has realistic data
with open("profiles/brooke_ryan_profile.yaml") as f:
    open_reqs.CANDIDATE_PROFILE = yaml.safe_load(f)

now = datetime.now(timezone.utc)
today = now.strftime("%Y-%m-%dT%H:%M:%SZ")
yesterday = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
older = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")

sample_jobs = [
    # Today bucket
    {
        "positionId": "200591234",
        "postingTitle": "Software Engineer, iCloud CloudKit",
        "team": {"teamName": "iCloud"},
        "locations": [{"name": "Santa Clara Valley, California, United States"}],
        "postingDate": today,
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
        "postingDate": today,
        "_score": 74,
        "_matchedQuery": "platform engineer",
        "_experience_level": "senior",
        "_detail_reasons": ["Kubernetes", "Linux", "infrastructure"],
        "_min_qual": "Experience with container orchestration and Linux systems.",
    },
    # This week bucket
    {
        "positionId": "200589001",
        "postingTitle": "Site Reliability Engineer, Core Services",
        "team": {"teamName": "Apple Services Engineering"},
        "locations": [{"name": "San Jose, California, United States"}],
        "postingDate": yesterday,
        "_score": 68,
        "_matchedQuery": "site reliability engineer",
        "_experience_level": "mid-level",
        "_detail_reasons": ["networking", "reliability", "automation"],
        "_min_qual": "3+ years SRE experience in high-traffic production environments.",
    },
    {
        "positionId": "200589002",
        "postingTitle": "Engineering Manager, Server Infrastructure",
        "team": {"teamName": "iCloud Server"},
        "locations": [{"name": "Santa Clara Valley, California, United States"}],
        "postingDate": yesterday,
        "_score": 55,
        "_matchedQuery": "engineering manager",
        "_experience_level": "senior",
        "_detail_reasons": ["server", "infrastructure"],
        "_min_qual": "7+ years in software engineering with 2+ years managing teams.",
    },
    # Older bucket
    {
        "positionId": "200580099",
        "postingTitle": "Cloud Infrastructure Software Engineer",
        "team": {"teamName": "Apple Cloud Services"},
        "locations": [{"name": "Santa Clara Valley, California, United States"}],
        "postingDate": older,
        "_score": 62,
        "_matchedQuery": "cloud infrastructure engineer",
        "_experience_level": "mid-level",
        "_detail_reasons": ["iCloud", "networking", "C"],
        "_min_qual": "BS/MS in Computer Science or related field.",
    },
]

candidate_name = open_reqs.CANDIDATE_PROFILE["name"]
html = open_reqs.build_email_html(sample_jobs, candidate_name)

output_path = "email_digest_test.html"
with open(output_path, "w") as f:
    f.write(html)

print(f"Email HTML written to {output_path} ({len(html):,} bytes, {len(sample_jobs)} jobs)")
print(f"  Today:     2 jobs")
print(f"  This week: 2 jobs")
print(f"  Older:     1 job")
