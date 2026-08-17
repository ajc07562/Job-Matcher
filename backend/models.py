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


class MatchRequest(BaseModel):
    resume_text: str
    top_k: int = 10
    explain: bool = True  # whether to call the LLM for explanations


class MatchResult(BaseModel):
    job: Job
    embedding_score: float
    skill_overlap_score: float
    seniority_score: float
    final_score: float
    matched_skills: list[str]
    missing_skills: list[str]
    explanation: Optional[str] = None


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
