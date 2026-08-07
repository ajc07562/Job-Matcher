"""
LLM layer — used ONLY to generate natural-language explanations for matches that
have already been scored and ranked deterministically (see ranker.py).

Earlier version had the LLM do the ranking itself ("here are 50 jobs and a resume,
rank them"). Dropped that approach: it was slow, cost scaled badly, and re-running
the same inputs gave different orderings since generation isn't deterministic. The
LLM is much better used for the part it's actually suited to — turning a computed
match + skill gap into a readable two-sentence explanation.

If ANTHROPIC_API_KEY isn't set, this degrades gracefully: match_result.explanation
stays None and the rest of the app (retrieval + ranking) works exactly the same.
"""
from backend.config import ANTHROPIC_API_KEY
from backend.models import MatchResult

_client = None
if ANTHROPIC_API_KEY:
    import anthropic

    _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def is_available() -> bool:
    return _client is not None


def explain_match(resume_text: str, result: MatchResult) -> str:
    """Generate a short, grounded explanation of why a job is (or isn't) a good fit."""
    if _client is None:
        return "(Set ANTHROPIC_API_KEY to enable AI-generated match explanations.)"

    job = result.job
    prompt = f"""You are helping a job seeker understand a ranked job match. Be concise,
specific, and grounded ONLY in the information given below — do not invent skills or
experience that isn't stated.

RESUME (excerpt):
{resume_text[:1500]}

JOB: {job.title} at {job.company}
REQUIREMENTS: {job.requirements[:800] or job.description[:800]}

COMPUTED MATCH DATA:
- Matched skills: {', '.join(result.matched_skills) or 'none detected'}
- Missing skills: {', '.join(result.missing_skills) or 'none detected'}
- Overall fit score: {result.final_score:.2f} (0-1 scale)

Write exactly two things, each 1-2 sentences:
1. WHY IT FITS: what makes this a reasonable match, grounded in the matched skills above.
2. GAP TO CLOSE: the single most important missing skill/qualification and a concrete,
   brief suggestion for closing it (e.g. a specific type of project or resource, not just
   "learn X").

Keep the total response under 80 words. No preamble, no headers other than the two labels."""

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=250,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()
