"""
LLM layer — used ONLY to generate natural-language explanations for matches that
have already been scored and ranked deterministically (see ranker.py).

Supports two providers so the app can run entirely for free:
  - "anthropic": Claude API (best quality, costs money per call)
  - "ollama":    a local open-source model via Ollama (github.com/ollama/ollama),
                 completely free, no account, runs on your own machine

LLM_PROVIDER="auto" (the default) prefers Anthropic if ANTHROPIC_API_KEY is set,
otherwise tries a local Ollama server, and falls back to a placeholder message if
neither is reachable — the rest of the app (retrieval + ranking) always works
regardless of which path is taken here.

To run for $0: install Ollama (https://ollama.com), run `ollama pull llama3.2`,
leave ANTHROPIC_API_KEY unset in .env, and the app will use it automatically.
"""
import requests

from backend.config import ANTHROPIC_API_KEY, LLM_PROVIDER, OLLAMA_HOST, OLLAMA_MODEL
from backend.models import MatchResult

_anthropic_client = None
if ANTHROPIC_API_KEY:
    import anthropic

    _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _ollama_is_reachable() -> bool:
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=1.5)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def is_available() -> bool:
    """Whether *some* explanation provider is usable right now."""
    if LLM_PROVIDER == "anthropic":
        return _anthropic_client is not None
    if LLM_PROVIDER == "ollama":
        return _ollama_is_reachable()
    # auto
    return _anthropic_client is not None or _ollama_is_reachable()


def _build_prompt(resume_text: str, result: MatchResult) -> str:
    job = result.job
    return f"""You are helping a job seeker understand a ranked job match. Be concise,
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


def _explain_with_anthropic(prompt: str) -> str:
    response = _anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=250,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


def _explain_with_ollama(prompt: str) -> str:
    resp = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "").strip()


def explain_match(resume_text: str, result: MatchResult) -> str:
    """Generate a short, grounded explanation of why a job is (or isn't) a good fit."""
    prompt = _build_prompt(resume_text, result)

    if LLM_PROVIDER == "anthropic":
        provider_order = ["anthropic"]
    elif LLM_PROVIDER == "ollama":
        provider_order = ["ollama"]
    else:
        provider_order = ["anthropic", "ollama"]  # auto: prefer Anthropic, fall back to local

    for provider in provider_order:
        try:
            if provider == "anthropic" and _anthropic_client is not None:
                return _explain_with_anthropic(prompt)
            if provider == "ollama" and _ollama_is_reachable():
                return _explain_with_ollama(prompt)
        except requests.exceptions.RequestException as e:
            # Try the next provider in the chain rather than failing the whole match request
            print(f"[llm] {provider} explanation failed: {e}")
            continue

    return (
        "(No explanation available — set ANTHROPIC_API_KEY in .env, or install Ollama "
        "and run `ollama pull llama3.2` for free local explanations.)"
    )