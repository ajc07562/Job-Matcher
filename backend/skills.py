"""
Extracts a normalized set of skills from free text (resume or job description)
using a curated taxonomy with alias matching.

Why not TF-IDF or NER off the shelf: tried TF-IDF first (see README, "what didn't
work") — it surfaces generic high-frequency words like "experience" and "team" as
top terms because nothing constrains it to actual tools/skills. A fixed taxonomy
with alias matching is less flexible but far more precise for this narrow use case.
"""
import json
import re
from functools import lru_cache

from backend.config import SKILLS_TAXONOMY_FILE


@lru_cache(maxsize=1)
def _load_taxonomy() -> dict[str, list[str]]:
    with open(SKILLS_TAXONOMY_FILE) as f:
        return json.load(f)


def _build_alias_pattern() -> list[tuple[str, re.Pattern]]:
    """Compile one regex per canonical skill, matching any of its aliases as a whole word/phrase."""
    taxonomy = _load_taxonomy()
    patterns = []
    for canonical, aliases in taxonomy.items():
        # Escape special regex chars (matters for things like "c++", "c#")
        escaped = [re.escape(a) for a in aliases]
        # Sort longest-first so "machine learning" matches before a hypothetical shorter alias
        escaped.sort(key=len, reverse=True)
        pattern = re.compile(
            r"(?<![a-zA-Z0-9])(" + "|".join(escaped) + r")(?![a-zA-Z0-9])",
            re.IGNORECASE,
        )
        patterns.append((canonical, pattern))
    return patterns


_ALIAS_PATTERNS = None


def extract_skills(text: str) -> set[str]:
    """Return the set of canonical skill names found in `text`."""
    global _ALIAS_PATTERNS
    if _ALIAS_PATTERNS is None:
        _ALIAS_PATTERNS = _build_alias_pattern()

    found = set()
    for canonical, pattern in _ALIAS_PATTERNS:
        if pattern.search(text):
            found.add(canonical)
    return found


def skill_overlap_score(resume_skills: set[str], job_skills: set[str]) -> float:
    """
    Jaccard-style overlap, but weighted toward the job's required skills:
    what fraction of the job's skills does the resume actually cover?
    This matters more than symmetric Jaccard because a resume having *extra*
    unrelated skills shouldn't hurt its score for a given job.
    """
    if not job_skills:
        return 0.5  # neutral score if the JD had no extractable skills
    overlap = resume_skills & job_skills
    return len(overlap) / len(job_skills)


def missing_skills(resume_skills: set[str], job_skills: set[str]) -> list[str]:
    return sorted(job_skills - resume_skills)


def matched_skills(resume_skills: set[str], job_skills: set[str]) -> list[str]:
    return sorted(resume_skills & job_skills)


SENIORITY_KEYWORDS = {
    "intern": ["intern", "internship"],
    "entry": ["entry level", "entry-level", "new grad", "graduate", "junior", "0-2 years", "associate"],
    "mid": ["mid level", "mid-level", "2-4 years", "3-5 years"],
    "senior": ["senior", "sr.", "5+ years", "6+ years", "7+ years"],
    "staff": ["staff", "8+ years", "9+ years", "10+ years"],
    "principal": ["principal", "distinguished"],
}


def infer_seniority(title: str, description: str) -> str:
    """
    Best-effort seniority inference from title + description text.
    Falls back to 'mid' if nothing matches, which is a deliberately conservative
    default (neither favors nor penalizes strongly against entry-level candidates).
    """
    text = f"{title} {description}".lower()
    # Check most-specific/highest levels first so "Senior" doesn't get masked by
    # an unrelated "2-4 years" mention elsewhere in a long JD.
    for level in ["principal", "staff", "senior", "intern", "entry", "mid"]:
        for kw in SENIORITY_KEYWORDS[level]:
            if kw in text:
                return level
    return "mid"
