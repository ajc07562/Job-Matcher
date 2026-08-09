"""
Pulls real job listings from Greenhouse's public job board API.

Greenhouse exposes a stable, public, no-auth-required JSON endpoint per company:
    https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

`board_token` is usually the company's lowercase name as it appears in their
careers URL (boards.greenhouse.io/<board_token>). This is legitimate, documented,
and widely used — not scraping rendered HTML or bypassing any access controls.

Written as a pluggable source so a Lever/Workday ingester can be added later
without touching downstream code (embeddings/ranker only care about the Job schema).

Usage:
    python backend/ingest.py                       # uses data/companies.json (broad default list)
    python backend/ingest.py --companies stripe airbnb notion figma --out data/jobs.json
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import List

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import DATA_DIR  # noqa: E402
from backend.models import Job  # noqa: E402

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
DEFAULT_COMPANIES_FILE = DATA_DIR / "companies.json"


def load_default_companies() -> List[str]:
    with open(DEFAULT_COMPANIES_FILE) as f:
        return json.load(f)["companies"]


def _strip_html(raw: str) -> str:
    """Greenhouse job content comes back as HTML — strip tags for clean embedding text."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_company_jobs(board_token: str) -> list[Job]:
    url = GREENHOUSE_URL.format(token=board_token)
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        print(f"  [skip] {board_token}: HTTP {resp.status_code}")
        return []

    payload = resp.json()
    jobs = []
    for item in payload.get("jobs", []):
        full_content = _strip_html(item.get("content", ""))
        # Greenhouse doesn't cleanly separate "requirements" from the rest of the
        # posting, so we use the full cleaned content for both fields; ranker.py
        # and embeddings.py both handle a missing/duplicate requirements field fine.
        jobs.append(
            Job(
                id=f"{board_token}-{item['id']}",
                company=board_token,
                title=item.get("title", "").strip(),
                location=(item.get("location") or {}).get("name", ""),
                description=full_content,
                requirements=full_content,
                url=item.get("absolute_url", ""),
            )
        )
    return jobs


def main():
    parser = argparse.ArgumentParser(description="Fetch jobs from Greenhouse job boards")
    parser.add_argument("--companies", nargs="+", default=None,
                         help="Greenhouse board tokens, e.g. stripe airbnb notion. "
                              "Omit to use the default list in data/companies.json.")
    parser.add_argument("--out", default="data/jobs.json")
    args = parser.parse_args()

    companies = args.companies or load_default_companies()
    print(f"Fetching {len(companies)} companies"
          + (" (default list)" if args.companies is None else "") + "...\n")

    all_jobs: list[Job] = []
    skipped = []
    for company in companies:
        print(f"Fetching {company}...")
        jobs = fetch_company_jobs(company)
        print(f"  -> {len(jobs)} listings")
        if not jobs:
            skipped.append(company)
        all_jobs.extend(jobs)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump([j.model_dump() for j in all_jobs], f, indent=2)

    print(f"\nWrote {len(all_jobs)} total jobs to {out_path}")
    if skipped:
        print(f"\n{len(skipped)} board token(s) returned nothing (wrong token, or company "
              f"doesn't use Greenhouse for that name): {', '.join(skipped)}")
        print("Check their careers page for the exact token in the URL "
              "(boards.greenhouse.io/<token>) and fix data/companies.json if you want to keep them.")


if __name__ == "__main__":
    main()