import sys
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.config as config  # noqa: E402
import backend.llm as llm  # noqa: E402
from backend.models import Job, MatchResult  # noqa: E402

CONN_ERR = requests.exceptions.ConnectionError("connection refused")


def _sample_result() -> MatchResult:
    job = Job(id="j1", company="Acme", title="ML Engineer", location="",
              description="Python required", requirements="Python required", url="")
    return MatchResult(job=job, embedding_score=0.8, skill_overlap_score=0.7,
                        seniority_score=1.0, final_score=0.78,
                        matched_skills=["python"], missing_skills=["aws"])


def test_auto_mode_unavailable_when_nothing_reachable():
    config.LLM_PROVIDER = "auto"
    with patch("backend.llm.requests.get", side_effect=CONN_ERR):
        assert llm.is_available() is False


def test_auto_mode_available_when_ollama_reachable():
    config.LLM_PROVIDER = "auto"
    with patch("backend.llm.requests.get", return_value=Mock(status_code=200)):
        assert llm.is_available() is True


def test_explain_match_falls_back_to_ollama():
    config.LLM_PROVIDER = "auto"
    result = _sample_result()

    fake_resp = Mock(status_code=200)
    fake_resp.json.return_value = {"response": "WHY IT FITS: matches python. GAP TO CLOSE: learn aws."}
    fake_resp.raise_for_status = Mock()

    with patch("backend.llm.requests.get", return_value=Mock(status_code=200)), \
         patch("backend.llm.requests.post", return_value=fake_resp) as mock_post:
        explanation = llm.explain_match("resume text", result)
        assert "learn aws" in explanation
        assert mock_post.call_args.kwargs["json"]["model"] == config.OLLAMA_MODEL


def test_explain_match_graceful_placeholder_when_nothing_available():
    config.LLM_PROVIDER = "auto"
    result = _sample_result()
    with patch("backend.llm.requests.get", side_effect=CONN_ERR), \
         patch("backend.llm.requests.post", side_effect=CONN_ERR):
        explanation = llm.explain_match("resume", result)
        assert "ollama pull llama3.2" in explanation


def test_forced_ollama_mode_reports_available():
    config.LLM_PROVIDER = "ollama"
    with patch("backend.llm.requests.get", return_value=Mock(status_code=200)):
        assert llm.is_available() is True
    config.LLM_PROVIDER = "auto"  # reset for any other tests that import this module
