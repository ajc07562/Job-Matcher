import json
import re
from pathlib import Path
from typing import Optional

import numpy as np

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend import auth, db
from backend.config import AUTO_REFRESH_JOBS, JOBS_FILE, REFRESH_INTERVAL_HOURS, SAMPLE_JOBS_FILE
from backend.embedding_viz import kmeans, pca_2d
from backend.embeddings import embed_text, embed_texts, job_text_for_embedding
from backend.ingest import fetch_company_jobs, load_default_companies
from backend.llm import explain_match, is_available as llm_available
from backend.models import (
    EmbeddingSpaceRequest,
    EmbeddingSpaceResponse,
    Job,
    LoginRequest,
    MatchRequest,
    MatchResult,
    SavedMatchOut,
    SaveMatchRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from backend.ranker import filter_results, rank_jobs, sort_results
from backend.resume_parser import PdfParseError, extract_text_from_pdf
from backend.scheduler import build_default_scheduler
from backend.skills import infer_seniority
from backend.vectorstore import JobVectorStore

app = FastAPI(title="Job Matcher API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_for_static_assets(request, call_next):
    """Force the browser to always revalidate .js/.css/.html instead of silently
    reusing a stale cached copy. This is a local dev tool that gets updated
    frequently — aggressive default browser caching on static assets caused real,
    hard-to-diagnose bugs here (old JS being served after the underlying file was
    already fixed on disk). ?v= query params on the asset tags handle it going
    forward for existing HTML, but this covers it unconditionally at the server
    level too, including for any page loaded directly without the version param.
    """
    response = await call_next(request)
    if request.url.path.endswith((".js", ".css", ".html")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


_store: Optional[JobVectorStore] = None


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles that tells the browser never to cache — no-store forbids caching
    entirely (not even the "revalidate with the server" kind), so a fixed app.js
    always actually reaches the browser on the next request, no hard-refresh needed.
    Worth the cost of an uncached asset here since this is a local dev tool, not a
    production site serving many users."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

WEB_DIR = Path(__file__).resolve().parent.parent / "frontend_web"


# --- Auth dependency ---

def get_current_user(authorization: Optional[str] = Header(default=None)) -> db.sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization[len("Bearer "):].strip()
    try:
        payload = auth.decode_token(token)
    except auth.TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user = db.get_user_by_id(payload.get("user_id"))
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


def _load_jobs() -> list[Job]:
    path = JOBS_FILE if JOBS_FILE.exists() else SAMPLE_JOBS_FILE
    with open(path) as f:
        raw = json.load(f)
    return [Job(**item) for item in raw]


def _build_store() -> JobVectorStore:
    jobs = _load_jobs()
    texts = [job_text_for_embedding(j.title, j.requirements, j.description) for j in jobs]
    vectors = embed_texts(texts)
    store = JobVectorStore(dim=vectors.shape[1])
    store.build(jobs, vectors)
    return store


def _refresh_and_rebuild() -> None:
    """Re-run ingestion against the default company list, write data/jobs.json,
    and rebuild the in-memory vector index from the fresh data. Used by both the
    manual /reload endpoint and the optional background scheduler."""
    global _store
    companies = load_default_companies()
    all_jobs: list[Job] = []
    for company in companies:
        all_jobs.extend(fetch_company_jobs(company))

    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(JOBS_FILE, "w") as f:
        json.dump([j.model_dump() for j in all_jobs], f, indent=2)

    _store = _build_store()


_scheduler = build_default_scheduler(_refresh_and_rebuild)


@app.on_event("startup")
def startup():
    global _store
    db.init_db()
    _store = _build_store()
    print(f"Loaded {len(_store)} jobs into the vector index.")
    print(f"LLM explanations {'enabled' if llm_available() else 'disabled (no ANTHROPIC_API_KEY)'}.")
    if _scheduler is not None:
        _scheduler.start()
        print(f"Auto-refresh enabled: re-ingesting every {REFRESH_INTERVAL_HOURS}h.")
    else:
        print("Auto-refresh disabled (set AUTO_REFRESH_JOBS=true in .env to enable).")


@app.on_event("shutdown")
def shutdown():
    if _scheduler is not None:
        _scheduler.stop()


@app.get("/health")
def health():
    return {"status": "ok", "jobs_indexed": len(_store) if _store else 0, "llm_available": llm_available()}


# --- Auth endpoints ---

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.post("/auth/signup", response_model=TokenResponse)
def signup(req: SignupRequest):
    if not EMAIL_RE.match(req.email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if db.get_user_by_email(req.email) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    password_hash = auth.hash_password(req.password)
    user = db.create_user(req.email, password_hash)
    token = auth.create_token({"user_id": user["id"]})
    return TokenResponse(access_token=token, user=UserOut(id=user["id"], email=user["email"]))


@app.post("/auth/login", response_model=TokenResponse)
def login(req: LoginRequest):
    user = db.get_user_by_email(req.email)
    if user is None or not auth.verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    token = auth.create_token({"user_id": user["id"]})
    return TokenResponse(access_token=token, user=UserOut(id=user["id"], email=user["email"]))


@app.get("/auth/me", response_model=UserOut)
def me(current_user=Depends(get_current_user)):
    return UserOut(id=current_user["id"], email=current_user["email"])


# --- Saved matches (require auth) ---

@app.post("/matches/save", response_model=SavedMatchOut)
def save_match(req: SaveMatchRequest, current_user=Depends(get_current_user)):
    row = db.save_match(
        current_user["id"], req.job_id, req.company, req.title,
        req.final_score, req.explanation, req.url,
    )
    return SavedMatchOut(**dict(row))


@app.get("/matches/history", response_model=list[SavedMatchOut])
def match_history(current_user=Depends(get_current_user)):
    rows = db.get_saved_matches(current_user["id"])
    return [SavedMatchOut(**dict(r)) for r in rows]


@app.delete("/matches/{job_id}")
def unsave_match(job_id: str, current_user=Depends(get_current_user)):
    db.delete_saved_match(current_user["id"], job_id)
    return {"status": "deleted"}


@app.post("/reload")
def reload_jobs():
    """Rebuild the index from whatever's currently in data/jobs.json (or the sample
    data if that file doesn't exist) — call after manually running ingest.py."""
    global _store
    _store = _build_store()
    return {"status": "reloaded", "jobs_indexed": len(_store)}


@app.post("/jobs/refresh")
def refresh_jobs():
    """Live-fetch the default company list from Greenhouse right now and rebuild the
    index — the on-demand equivalent of what the auto-refresh scheduler does on a timer.
    Synchronous and can take a while depending on how many companies are configured."""
    _refresh_and_rebuild()
    return {"status": "refreshed", "jobs_indexed": len(_store)}


def _guess_resume_seniority(resume_text: str) -> str:
    """Cheap heuristic: look for explicit signals in the resume itself, default to entry."""
    text = resume_text.lower()
    if re.search(r"\bintern(ship)?\b", text) and not re.search(r"\byears? of experience\b", text):
        return "entry"
    return infer_seniority("", resume_text)


@app.post("/resume/extract-text")
async def extract_resume_text(file: UploadFile = File(...)):
    """Extract plain text from an uploaded PDF resume. Returns the text for the
    frontend to drop into the resume textarea — deliberately not wired directly
    into /match, so the user gets a chance to review/fix extraction before matching
    (PDF text extraction is rarely perfect for unusual resume layouts)."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    file_bytes = await file.read()
    try:
        text = extract_text_from_pdf(file_bytes)
    except PdfParseError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"text": text}


@app.get("/jobs/companies")
def list_companies():
    """Distinct company names currently in the index — powers the company filter
    dropdown in the UI so it only ever offers values that actually return results."""
    if _store is None:
        return {"companies": []}
    companies = sorted({job.company for job in _store.jobs})
    return {"companies": companies}


@app.post("/match", response_model=list[MatchResult])
def match(req: MatchRequest):
    if _store is None or len(_store) == 0:
        raise HTTPException(status_code=503, detail="Job index not ready or empty.")

    query_vec = embed_text(req.resume_text)

    # Filtering/sorting happens AFTER ranking, so pulling only a small top-K
    # candidate pool (fine when nothing else narrows results) would silently starve
    # results once filters are active — e.g. asking for remote-only jobs from a
    # pool of 20 best-embedding-match candidates could easily return zero, even if
    # plenty of remote matches exist further down. Pull a much larger pool whenever
    # any filter or non-default sort is active.
    filters_active = any([
        req.location, req.remote_only, req.min_score > 0, req.company,
        req.seniority, req.sort_by != "best_match",
    ])
    pool_size = min(len(_store), 500) if filters_active else max(req.top_k * 3, 20)
    candidates = _store.search(query_vec, top_k=pool_size)
    resume_seniority = _guess_resume_seniority(req.resume_text)

    ranked = rank_jobs(candidates, req.resume_text, resume_seniority)
    filtered = filter_results(
        ranked,
        location=req.location,
        remote_only=req.remote_only,
        min_score=req.min_score,
        company=req.company,
        seniority=req.seniority,
    )
    sorted_results = sort_results(filtered, req.sort_by)
    final = sorted_results[: req.top_k]

    if req.explain and llm_available():
        for result in final:
            result.explanation = explain_match(req.resume_text, result)

    return final


@app.post("/embedding-space", response_model=EmbeddingSpaceResponse)
def embedding_space(req: EmbeddingSpaceRequest):
    """
    2D PCA projection of the job corpus plus the resume, with jobs k-means-clustered
    by embedding — purely a "look inside the black box" visualization, not part of
    the matching/ranking pipeline itself. Reuses the exact same hybrid scoring as
    /match for each point's score (rank_jobs), so a point's color/tooltip score here
    means exactly the same thing it does on the results page.
    """
    if _store is None or len(_store) == 0:
        raise HTTPException(status_code=503, detail="Job index not ready or empty.")

    total = len(_store)
    max_jobs = max(2, min(req.max_jobs, total))

    if total > max_jobs:
        # Fixed seed: re-running with the same resume gives the same scatter plot,
        # rather than a different random subset jumping around on every request.
        indices = np.random.default_rng(42).choice(total, size=max_jobs, replace=False)
    else:
        indices = np.arange(total)

    sampled_jobs = [_store.jobs[i] for i in indices]
    sampled_vectors = _store.vectors[indices]

    resume_vec = embed_text(req.resume_text)
    resume_seniority = _guess_resume_seniority(req.resume_text)

    # Vectors are L2-normalized (see embeddings.py), so a plain dot product IS
    # cosine similarity — same math FAISS's IndexFlatIP does internally.
    embedding_scores = sampled_vectors @ resume_vec
    candidates = list(zip(sampled_jobs, embedding_scores.tolist()))
    scored = rank_jobs(candidates, req.resume_text, resume_seniority)
    score_by_id = {r.job.id: r.final_score for r in scored}

    # PCA over jobs + resume together, so the resume point lands in the same
    # coordinate space as the job points instead of being projected separately.
    combined = np.vstack([sampled_vectors, resume_vec.reshape(1, -1)])
    projected = pca_2d(combined)
    job_points_2d = projected[:-1]
    resume_point_2d = projected[-1]

    cluster_labels = kmeans(sampled_vectors, k=req.num_clusters)

    points = [
        EmbeddingSpacePoint(
            job_id=job.id,
            title=job.title,
            company=job.company,
            x=float(x),
            y=float(y),
            cluster=int(cluster),
            final_score=round(score_by_id.get(job.id, 0.0), 4),
        )
        for job, (x, y), cluster in zip(sampled_jobs, job_points_2d, cluster_labels)
    ]

    return EmbeddingSpaceResponse(
        points=points,
        resume_x=float(resume_point_2d[0]),
        resume_y=float(resume_point_2d[1]),
        num_clusters=int(cluster_labels.max()) + 1 if len(cluster_labels) > 0 else 0,
        total_jobs_in_index=total,
        jobs_shown=len(sampled_jobs),
    )


# Serve the static frontend (login/signup + app UI) last, as a catch-all,
# so it never shadows the API routes registered above.
if WEB_DIR.exists():
    app.mount("/", NoCacheStaticFiles(directory=str(WEB_DIR), html=True), name="frontend")