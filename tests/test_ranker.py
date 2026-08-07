import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models import Job  # noqa: E402
from backend.ranker import score_job, seniority_fit_score  # noqa: E402


def make_job(title="ML Engineer", requirements="Python, PyTorch", seniority=None) -> Job:
    return Job(
        id="test-1",
        company="TestCo",
        title=title,
        description=requirements,
        requirements=requirements,
        seniority=seniority,
    )


def test_seniority_fit_exact_match():
    assert seniority_fit_score("entry", "entry") == 1.0


def test_seniority_fit_one_level_gap():
    assert seniority_fit_score("entry", "mid") == 0.75


def test_seniority_fit_large_gap_penalized_hard():
    score_close = seniority_fit_score("entry", "mid")
    score_far = seniority_fit_score("entry", "staff")
    assert score_far < score_close
    assert score_far <= 0.1


def test_seniority_fit_unknown_level_neutral():
    assert seniority_fit_score("entry", "unknown_level") == 0.5


def test_score_job_perfect_skill_match_scores_higher_than_no_match():
    job = make_job(requirements="Python, SQL, Machine Learning", seniority="entry")

    good_resume_skills = {"python", "sql", "machine learning"}
    bad_resume_skills = {"sales", "excel"}

    result_good = score_job(job, embedding_score=0.8, resume_skills=good_resume_skills, resume_seniority="entry")
    result_bad = score_job(job, embedding_score=0.8, resume_skills=bad_resume_skills, resume_seniority="entry")

    assert result_good.final_score > result_bad.final_score
    assert result_good.skill_overlap_score == 1.0
    assert set(result_good.matched_skills) == {"python", "sql", "machine learning"}


def test_score_job_missing_skills_populated():
    job = make_job(requirements="Python, Kubernetes, AWS", seniority="mid")
    resume_skills = {"python"}
    result = score_job(job, embedding_score=0.5, resume_skills=resume_skills, resume_seniority="entry")
    assert "kubernetes" in result.missing_skills
    assert "aws" in result.missing_skills
    assert "python" not in result.missing_skills


def test_score_job_seniority_mismatch_lowers_score():
    job_entry = make_job(seniority="entry")
    job_staff = make_job(seniority="staff")
    skills = {"python", "pytorch"}

    result_entry_fit = score_job(job_entry, 0.7, skills, resume_seniority="entry")
    result_staff_mismatch = score_job(job_staff, 0.7, skills, resume_seniority="entry")

    assert result_entry_fit.final_score > result_staff_mismatch.final_score
