"""
Local embedding model wrapper. Deliberately not using an API-based embedding model
(e.g. OpenAI's) so the core retrieval pipeline has zero external dependency and zero
per-query cost — the LLM API is reserved for the explanation layer only (see llm.py).
"""
import re
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from backend.config import EMBEDDING_MODEL_NAME


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed_text(text: str) -> np.ndarray:
    """Return a single L2-normalized embedding vector for a piece of text."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype("float32")


def embed_texts(texts: list[str]) -> np.ndarray:
    """Batch-embed a list of texts. Returns an (N, D) float32 matrix, L2-normalized."""
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype="float32")


def _strip_tags_light(text: str) -> str:
    """Minimal tag strip for the description fallback below. `description` now
    keeps real HTML formatting for display (see ingest.py), so if we ever fall back
    to it here (requirements empty), markup shouldn't leak into what gets embedded."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def job_text_for_embedding(title: str, requirements: str, description: str) -> str:
    """
    Build the text that gets embedded for a job. Deliberately weights title +
    requirements over the full description.

    Earlier version embedded the full raw description (including "About us" /
    company-mission boilerplate) and it hurt precision — generic mission-statement
    language is semantically close to almost any resume, which let weak matches
    outscore strong ones. Requirements-first fixed this (see README).
    """
    req = requirements.strip() or _strip_tags_light(description)
    return f"Job title: {title}\nRequirements: {req}"