from typing import Optional
from pydantic import BaseModel


class Job(BaseModel):
    id: str
    company: str
    title: str
    location: Optional[str] = ""
    description: str
    requirements: str = ""
    url: Optional[str] = ""
    seniority: Optional[str] = None  # inferred if not provided
    posted_at: Optional[str] = None  # ISO 8601 string; None for sources that don't provide it


class MatchRequest(BaseModel):
    resume_text: str
    top_k: int = 10
    explain: bool = True  # whether to call the LLM for explanations

    # --- Filters (all optional; None/False/0 means "no filter applied") ---
    location: Optional[str] = None       # case-insensitive substring match against job.location
    remote_only: bool = False            # keep only jobs whose location mentions "remote"
    min_score: float = 0.0               # keep only jobs with final_score >= this (0-1 scale)
    company: Optional[str] = None        # exact match, case-insensitive, against job.company
    seniority: Optional[str] = None      # one of SENIORITY_LEVELS, or None for any level
    sort_by: str = "best_match"          # "best_match" | "newest" | "oldest"


class MatchResult(BaseModel):
    job: Job
    embedding_score: float
    skill_overlap_score: float
    seniority_score: float
    final_score: float
    matched_skills: list[str]
    missing_skills: list[str]
    job_seniority: str  # the level this job was scored against (inferred if not on the posting)
    explanation: Optional[str] = None


# --- Embedding space visualization ---

class EmbeddingSpaceRequest(BaseModel):
    resume_text: str
    max_jobs: int = 300      # cap on how many jobs get projected/clustered, for speed
    num_clusters: int = 6


class EmbeddingSpacePoint(BaseModel):
    job_id: str
    title: str
    company: str
    x: float
    y: float
    cluster: int
    final_score: float  # hybrid score against this resume, for tooltip/color intensity


class EmbeddingSpaceResponse(BaseModel):
    points: list[EmbeddingSpacePoint]
    resume_x: float
    resume_y: float
    num_clusters: int
    total_jobs_in_index: int
    jobs_shown: int


# --- Auth ---

class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --- Saved matches ---

class SaveMatchRequest(BaseModel):
    job_id: str
    company: str
    title: str
    final_score: float
    explanation: Optional[str] = None
    url: Optional[str] = None


class SavedMatchOut(BaseModel):
    job_id: str
    company: str
    title: str
    final_score: float
    explanation: Optional[str] = None
    url: Optional[str] = None
    created_at: int