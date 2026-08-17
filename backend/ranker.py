"""
Hybrid re-ranker: combines embedding similarity with two explicit signals that
pure semantic search can't capture — skill overlap and seniority fit.

See eval/evaluate.py for the measured precision@5 improvement this gives over
embedding-only ranking (0.52 -> 0.81 on the hand-labeled set).
"""
from datetime import datetime
from typing import Optional

from backend.config import (
    SENIORITY_LEVELS,
    WEIGHT_EMBEDDING,
    WEIGHT_SENIORITY,
    WEIGHT_SKILL_OVERLAP,
)
from backend.models import Job, MatchResult
from backend.skills import (
    extract_skills,
    infer_seniority,
    matched_skills,
    missing_skills,
    skill_overlap_score,
)


def seniority_fit_score(resume_seniority: str, job_seniority: str) -> float:
    """
    1.0 for an exact match, decaying with distance in the seniority ladder.
    A 1-level gap (e.g. entry candidate applying to a mid-level role) is only
    mildly penalized since that's a normal, reasonable stretch application.
    Distances of 3+ levels (e.g. entry candidate vs. staff/principal posting)
    are penalized hard — this is the main lever that fixed the "Staff ML
    Engineer surfaced for a new-grad resume" failure mode described in the README.
    """
    try:
        r_idx = SENIORITY_LEVELS.index(resume_seniority)
        j_idx = SENIORITY_LEVELS.index(job_seniority)
    except ValueError:
        return 0.5  # unknown level, neutral score

    distance = abs(r_idx - j_idx)
    if distance == 0:
        return 1.0
    elif distance == 1:
        return 0.75
    elif distance == 2:
        return 0.35
    else:
        return 0.05


def score_job(
    job: Job,
    embedding_score: float,
    resume_skills: set[str],
    resume_seniority: str,
) -> MatchResult:
    job_skills = extract_skills(f"{job.title} {job.requirements} {job.description}")
    job_seniority = job.seniority or infer_seniority(job.title, job.description)

    skill_score = skill_overlap_score(resume_skills, job_skills)
    sen_score = seniority_fit_score(resume_seniority, job_seniority)

    final = (
        WEIGHT_EMBEDDING * embedding_score
        + WEIGHT_SKILL_OVERLAP * skill_score
        + WEIGHT_SENIORITY * sen_score
    )

    return MatchResult(
        job=job,
        embedding_score=round(embedding_score, 4),
        skill_overlap_score=round(skill_score, 4),
        seniority_score=round(sen_score, 4),
        final_score=round(final, 4),
        matched_skills=matched_skills(resume_skills, job_skills),
        missing_skills=missing_skills(resume_skills, job_skills),
        job_seniority=job_seniority,
    )


def rank_jobs(
    candidates: list[tuple[Job, float]],
    resume_text: str,
    resume_seniority: str = "entry",
) -> list[MatchResult]:
    """
    candidates: list of (Job, embedding_score) tuples, typically from vectorstore.search()
    Returns MatchResults sorted by final hybrid score, descending.
    """
    resume_skills = extract_skills(resume_text)
    results = [
        score_job(job, emb_score, resume_skills, resume_seniority)
        for job, emb_score in candidates
    ]
    results.sort(key=lambda r: r.final_score, reverse=True)
    return results


def filter_results(
    results: list[MatchResult],
    location: Optional[str] = None,
    remote_only: bool = False,
    min_score: float = 0.0,
    company: Optional[str] = None,
    seniority: Optional[str] = None,
) -> list[MatchResult]:
    """
    Apply all active filters (None/False/0 = "not applied"). Order doesn't matter
    for correctness here since every check is independent, but cheapest checks
    (numeric comparisons) run before string operations as a minor optimization.
    """
    out = results

    if min_score > 0:
        out = [r for r in out if r.final_score >= min_score]

    if remote_only:
        out = [r for r in out if "remote" in (r.job.location or "").lower()]

    if location:
        needle = location.strip().lower()
        out = [r for r in out if needle in (r.job.location or "").lower()]

    if company:
        needle = company.strip().lower()
        out = [r for r in out if needle == (r.job.company or "").lower()]

    if seniority:
        wanted = seniority.strip().lower()
        out = [r for r in out if r.job_seniority == wanted]

    return out


def _parse_posted_at(value: Optional[str]) -> Optional[datetime]:
    """Best-effort ISO 8601 parse. Returns None for missing/unparseable values —
    callers push those to the end of the sort regardless of direction, since an
    unknown date is neither reliably "newest" nor "oldest"."""
    if not value:
        return None
    try:
        # Python's fromisoformat handles "+HH:MM"/"-HH:MM" offsets natively; it does
        # NOT handle a trailing "Z" before 3.11, so normalize that case explicitly
        # for broader compatibility (this project targets 3.9+, see README).
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None


def sort_results(results: list[MatchResult], sort_by: str = "best_match") -> list[MatchResult]:
    """
    "best_match": no-op — results are assumed already sorted by final_score
    (rank_jobs already does this, and filtering preserves order).
    "newest"/"oldest": sort by job.posted_at. Entries with no parseable date are
    always pushed to the end, regardless of direction, rather than sorted as if
    they were arbitrarily old or new.
    """
    if sort_by not in ("newest", "oldest"):
        return results

    dated = [(r, _parse_posted_at(r.job.posted_at)) for r in results]
    with_date = [(r, d) for r, d in dated if d is not None]
    without_date = [r for r, d in dated if d is None]

    with_date.sort(key=lambda pair: pair[1], reverse=(sort_by == "newest"))
    return [r for r, _ in with_date] + without_date