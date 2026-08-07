import json
import re
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend import auth, db
from backend.config import JOBS_FILE, SAMPLE_JOBS_FILE
from backend.embeddings import embed_text, embed_texts, job_text_for_embedding
from backend.llm import explain_match, is_available as llm_available
from backend.models import (
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
from backend.ranker import rank_jobs
from backend.skills import infer_seniority
from backend.vectorstore import JobVectorStore

app = FastAPI(title="Job Matcher API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_store: Optional[JobVectorStore] = None

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


@app.on_event("startup")
def startup():
    global _store
    db.init_db()
    _store = _build_store()
    print(f"Loaded {len(_store)} jobs into the vector index.")
    print(f"LLM explanations {'enabled' if llm_available() else 'disabled (no ANTHROPIC_API_KEY)'}.")


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
    """Rebuild the index — call after running ingest.py to pull in fresh listings."""
    global _store
    _store = _build_store()
    return {"status": "reloaded", "jobs_indexed": len(_store)}


def _guess_resume_seniority(resume_text: str) -> str:
    """Cheap heuristic: look for explicit signals in the resume itself, default to entry."""
    text = resume_text.lower()
    if re.search(r"\bintern(ship)?\b", text) and not re.search(r"\byears? of experience\b", text):
        return "entry"
    return infer_seniority("", resume_text)


@app.post("/match", response_model=list[MatchResult])
def match(req: MatchRequest):
    if _store is None or len(_store) == 0:
        raise HTTPException(status_code=503, detail="Job index not ready or empty.")

    query_vec = embed_text(req.resume_text)
    candidates = _store.search(query_vec, top_k=max(req.top_k * 3, 20))
    resume_seniority = _guess_resume_seniority(req.resume_text)

    ranked = rank_jobs(candidates, req.resume_text, resume_seniority)[: req.top_k]

    if req.explain and llm_available():
        for result in ranked:
            result.explanation = explain_match(req.resume_text, result)

    return ranked


# Serve the static frontend (login/signup + app UI) last, as a catch-all,
# so it never shadows the API routes registered above.
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="frontend")
