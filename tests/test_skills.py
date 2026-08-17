import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.skills import (  # noqa: E402
    extract_skills,
    infer_seniority,
    missing_skills,
    skill_overlap_score,
)


def test_extract_skills_basic():
    text = "We use Python, PyTorch, and Kubernetes. Experience with SQL is a plus."
    skills = extract_skills(text)
    assert "python" in skills
    assert "pytorch" in skills
    assert "kubernetes" in skills
    assert "sql" in skills


def test_extract_skills_aliases():
    text = "Experience with k8s and hugging face transformers required. Familiar with genai."
    skills = extract_skills(text)
    assert "kubernetes" in skills
    assert "huggingface" in skills
    assert "generative ai" in skills


def test_extract_skills_no_false_positive_substring():
    # "r" as a language shouldn't match inside unrelated words like "our" or "for"
    text = "This role is for our growing team."
    skills = extract_skills(text)
    assert "r" not in skills


def test_skill_overlap_score_full_overlap():
    resume = {"python", "sql", "machine learning"}
    job = {"python", "sql"}
    assert skill_overlap_score(resume, job) == 1.0


def test_skill_overlap_score_partial():
    resume = {"python"}
    job = {"python", "kubernetes"}
    assert skill_overlap_score(resume, job) == 0.5


def test_skill_overlap_score_no_job_skills():
    assert skill_overlap_score({"python"}, set()) == 0.5


def test_missing_skills():
    resume = {"python"}
    job = {"python", "kubernetes", "sql"}
    assert missing_skills(resume, job) == ["kubernetes", "sql"]


def test_infer_seniority_entry():
    assert infer_seniority("Software Engineer, New Grad", "") == "entry"


def test_infer_seniority_senior():
    assert infer_seniority("Senior Backend Engineer", "5+ years experience required") == "senior"


def test_infer_seniority_default_mid():
    assert infer_seniority("Backend Engineer", "join our platform team") == "mid"
