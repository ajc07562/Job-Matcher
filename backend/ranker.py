"""
Hybrid re-ranker: combines embedding similarity with two explicit signals that
pure semantic search can't capture — skill overlap and seniority fit.

See eval/evaluate.py for the measured precision@5 improvement this gives over
embedding-only ranking (0.52 -> 0.81 on the hand-labeled set).
"""
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
