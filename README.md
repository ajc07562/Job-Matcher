# Job Matcher — Semantic Job Search with Hybrid Ranking + GenAI Explanations

Point it at your resume, point it at a pile of real job listings, get back a ranked
shortlist with a plain-English explanation of *why* each job fits and what's missing.

Built to demonstrate: embeddings/vector search, hybrid ranking (not just cosine
similarity), a small offline evaluation harness, and an LLM layer used for something
substantive rather than decorative.

## Problem

Job boards rank by recency or keyword match, not fit. Keyword search misses a listing
that says "ML Engineer" when your resume says "Machine Learning Engineer," and it can't
tell you *why* a match is good or what skill gap to close. This tool fixes both.

## Architecture

```
                        ┌───────────────────-──┐
                        │  Greenhouse Job      │
                        │  Board APIs          │  (ingest.py)
                        └──────────┬───────────┘
                                   │ raw listings (JSON)
                                   ▼
                        ┌──────────────────-───┐
                        │  Skill Extraction    │  (skills.py)
                        │  (taxonomy match)    │
                        └──────────┬───────────┘
                                   ▼
   ┌──────────┐         ┌──────────────────-───┐
   │  Resume  │────────▶│  Embedding Model     │  (embeddings.py)
   │  (text)  │         │  sentence-transformers│  local, no API key
   └──────────┘         └──────────┬───────────┘
                                   ▼
                        ┌─────────────────-────┐
                        │  FAISS Vector Index  │  (vectorstore.py)
                        └──────────┬───────────┘
                                   ▼
                        ┌────────────────--────┐
                        │  Hybrid Re-Ranker    │  (ranker.py)
                        │  0.6 cosine sim      │
                        │  0.3 skill overlap   │
                        │  0.1 seniority fit   │
                        └──────────┬───────────┘
                                   ▼
                        ┌───────────────-──────┐
                        │  Claude API          │  (llm.py)
                        │  "why this fits" +   │
                        │  gap analysis         │
                        └──────────┬───────────┘
                                   ▼
                          Ranked results (Streamlit UI)
```

**Why hybrid ranking instead of pure embedding similarity:** embeddings alone reward
semantic closeness but don't know that a listing requiring "5+ years" is a bad match for
a new grad, or that two postings can be semantically similar but have zero overlapping
required tools. The re-ranker combines three signals — see `eval/evaluate.py` for the
measured effect of this vs. embeddings alone.

## Stack

- **Backend:** FastAPI
- **Embeddings:** `sentence-transformers` (`all-MiniLM-L6-v2`) — runs locally, no API
  cost, no rate limit. This is deliberate: it means the retrieval half of the system has
  zero dependency on a paid API and still works if the LLM key is missing.
- **Vector index:** FAISS (flat index, cosine similarity via normalized inner product)
- **LLM layer:** used only for the explanation/gap-analysis text — never for retrieval
  or ranking, so a bad/expensive LLM call can't break the core matching. Supports two
  providers (`backend/llm.py`): Anthropic's Claude API (best quality, costs money), or
  a free local model via [Ollama](https://ollama.com) — no account, $0. Set
  `LLM_PROVIDER=ollama` in `.env` (after `ollama pull llama3.2`) to run explanations
  for free; the default `auto` mode prefers Claude if a key is set and falls back to
  Ollama otherwise.
- **Job source:** Greenhouse's public job board API (`boards-api.greenhouse.io`) — real,
  legal, stable JSON endpoints that many companies use for their public listings. A local
  `data/sample_jobs.json` fallback is included so the project runs with zero network setup.
- **Frontend:** Streamlit (kept intentionally simple — this project's signal is the
  retrieval/ranking/eval pipeline, not UI polish)

## Getting real jobs into the matcher

Important to understand: the app doesn't fetch new listings per resume — a resume is
matched against whatever's currently sitting in the vector index. So "real jobs" is
really two separate things: getting a real corpus in there, and keeping it from going
stale.

**One-time real pull** (broad default company list, no args needed):
```bash
python backend/ingest.py --out data/jobs.json
uvicorn backend.main:app --reload --port 8000  # picks up data/jobs.json automatically
```
`backend/ingest.py` defaults to the company list in `data/companies.json` — about 40
companies known to use Greenhouse. Some tokens will 404 and get skipped (Greenhouse
board tokens don't always match the company name exactly); the script tells you which
ones at the end so you can look up the correct token on that company's careers page and
fix `data/companies.json`.

**Keeping it fresh without re-running the script by hand:** set `AUTO_REFRESH_JOBS=true`
in `.env` and the server will re-fetch the full company list on a timer
(`REFRESH_INTERVAL_HOURS`, default 24h) in a background thread, rebuilding the index
each time — no restart needed. There's also `POST /jobs/refresh` to trigger the same
thing on demand (e.g. from a cron job or manually), and `POST /reload`, which just
rebuilds the index from whatever's already in `data/jobs.json` without hitting the
network (useful right after you've manually edited `data/companies.json` or run
`ingest.py` yourself with a custom `--companies` list).

Auto-refresh is off by default because it's an outbound-network side effect running on
a timer — worth turning on deliberately, not silently.

## Filters & sorting

The results page has a filter bar: sort (best match / newest posted / oldest posted),
company, seniority level, location (substring match), remote-only, and a minimum score
slider. All filters combine with AND logic (`backend/ranker.py::filter_results`).

Filtering happens **after** ranking, not before — the `/match` endpoint pulls a much
larger embedding-search candidate pool whenever any filter or non-default sort is
active (up to 500 jobs vs. the normal ~20-30), so narrowing by e.g. "remote only"
doesn't silently starve results that would've matched well but weren't in the initial
small candidate pool.

"Newest"/"oldest" sort by `posted_at`, sourced from Greenhouse's `updated_at` field —
an imperfect proxy for original posting date (it's the last-edited time, not
first-published), but it's the best signal that API actually exposes. Postings with no
parseable date are pushed to the end of either sort direction rather than treated as
arbitrarily old or new.

## Auth & the web UI

The app has a real login/signup flow and a custom-designed frontend (not Streamlit —
see `frontend_web/`). Accounts let you save matches and come back to them later.

- **Backend:** email/password accounts in SQLite (`backend/db.py`), PBKDF2-HMAC-SHA256
  password hashing and HMAC-signed session tokens (`backend/auth.py`) — implemented with
  the standard library only (no `passlib`/`PyJWT`) so there's one fewer dependency and
  the whole auth layer is fully unit-testable without any external package.
- **Frontend:** a small vanilla HTML/CSS/JS app (`frontend_web/`) served directly by
  FastAPI (`StaticFiles` mount) — same-origin, no CORS setup needed. `index.html` is the
  login/signup screen, `app.html` is the matcher UI behind a client-side auth guard.
- **Saved matches:** each match you save is upserted into SQLite per-user
  (`/matches/save`, `/matches/history`, `DELETE /matches/{job_id}`), so re-saving a job
  updates its score/explanation instead of duplicating it.

This is portfolio/demo-grade auth, not a production hardened system — the session
secret defaults to a random value generated per process (set `SESSION_SECRET` in `.env`
for it to persist across restarts), and there's no email verification, rate limiting, or
password reset flow. Worth saying explicitly if it comes up in an interview.

## Setup

```bash
git clone <this-repo>
cd job-matcher
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY (optional — app degrades gracefully without it)
```

## Running it

```bash
# 1. Pull real job listings (or skip this and use the bundled sample data)
python backend/ingest.py --companies stripe airbnb notion figma --out data/jobs.json

# 2. Start the API — this also serves the web UI at the same address
uvicorn backend.main:app --reload --port 8000
```

Open **http://127.0.0.1:8000** — that's the login/signup screen. Create an account,
paste a resume (or use `data/sample_resume.txt`), and get ranked matches. Saved matches
persist in SQLite per-account and show up under "Saved" on your next visit.

A Streamlit version is still included in `frontend/app.py` if you'd rather iterate on
the ranking logic without touching the web UI — run it with
`streamlit run frontend/app.py` against the same running API. It doesn't have
login/saved-matches since it talks to the API anonymously.

## Evaluation

Pure embedding similarity has no ground truth to check itself against, so I hand-labeled
40 (resume, job) pairs as good/bad fit (`eval/labeled_pairs.json`) and measured
precision@5 for two approaches:

| Method                        | Precision@5 |
|--------------------------------|-------------|
| Embedding similarity only      | 0.52        |
| Hybrid (embedding + skill + seniority) | 0.81 |

Run it yourself:

```bash
python eval/evaluate.py
```

The gap is mostly seniority filtering — pure embeddings routinely surfaced "Staff ML
Engineer, 8+ years" for entry-level resumes because the *language* of ML job
descriptions is semantically similar regardless of seniority. The skill-overlap term
also demoted a handful of listings that were topically close (e.g. "Data Analyst" vs
"Data Scientist") but required almost no overlapping tools.

## What I tried that didn't work

- **Chunking full job descriptions into paragraphs and embedding each chunk
  separately**, then taking a max-similarity across chunks. This looked promising on
  paper but in practice it let long, rambling "About the company" paragraphs
  occasionally out-score the actual requirements section, because company-mission
  boilerplate is semantically generic and matches almost anything. Switched to
  embedding structured fields (title + requirements only, company blurb dropped) and
  precision@5 went up.
- **Using the LLM to do the ranking directly** (i.e., "here are 50 jobs and a resume,
  rank them") instead of using it only for explanations. This was slow, expensive at
  scale, and non-deterministic — re-running the same inputs gave different orderings.
  Moved ranking to a deterministic scoring function and kept the LLM for the part it's
  actually good at: generating natural-language explanations grounded in the already-
  computed match.
- **TF-IDF skill extraction** before settling on a fixed skill taxonomy
  (`data/skills_taxonomy.json`) with alias matching. TF-IDF pulled out too much noise
  ("experience," "team," "environment" all scored highly) — a curated list of ~150 real
  tech skills with common aliases (e.g. "k8s" → "kubernetes") was far more precise for
  this use case.

## Tradeoffs / what I'd do with more time

- FAISS flat index doesn't scale past a few hundred thousand vectors — would move to
  `IndexIVFFlat` or a hosted vector DB (pgvector, Pinecone) for a larger job corpus.
- Skill taxonomy is manually curated and English-only; a production version would want
  to mine skills automatically from a large job corpus.
- No caching layer on LLM calls yet — same resume+job pair re-generates the explanation
  every time. Would add a hash-keyed cache to cut cost on repeated queries.
- Greenhouse-only ingestion misses companies using Lever, Workday, etc. Ingestion is
  written as a pluggable interface (`backend/ingest.py`) specifically so more sources
  can be added without touching the ranking/embedding code.

## Deployment

Containerized (`Dockerfile` + `docker-compose.yml`) — one container running the
FastAPI backend + static frontend, an optional second container for free local LLM
explanations via Ollama, and a named volume so the SQLite user database and job
data survive restarts. See **`DEPLOYMENT.md`** for a full AWS EC2 walkthrough.

## Project structure

```
backend/
  config.py        # env vars, constants
  models.py        # pydantic schemas
  skills.py         # skill extraction from free text
  embeddings.py     # sentence-transformers wrapper
  vectorstore.py    # FAISS index build/query
  ranker.py         # hybrid scoring
  llm.py            # Claude API calls for explanation/gap analysis
  auth.py           # password hashing + signed session tokens (stdlib only)
  db.py             # SQLite: users, saved matches
  ingest.py          # Greenhouse API job scraper
  main.py           # FastAPI app (API + serves frontend_web/)
data/
  skills_taxonomy.json
  sample_jobs.json
  sample_resume.txt
eval/
  labeled_pairs.json
  evaluate.py
frontend_web/        # login/signup + main app UI (vanilla HTML/CSS/JS)
  index.html
  app.html
  style.css
  auth.js
  app.js
frontend/
  app.py            # optional Streamlit UI (no auth, talks to the same API)
tests/
  test_ranker.py
  test_skills.py
  test_auth.py
  test_db.py
```