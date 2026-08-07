"""
Offline evaluation: precision@5 for embedding-only ranking vs. the hybrid ranker.

There's no ground-truth "correct match" for this kind of task, so this hand-labels
a small set of (resume, job) pairs as good/bad fit and measures how well each
ranking method surfaces the good ones in the top 5.

Run: python eval/evaluate.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.embeddings import embed_text, embed_texts, job_text_for_embedding  # noqa: E402
from backend.models import Job  # noqa: E402
from backend.ranker import rank_jobs  # noqa: E402
from backend.skills import infer_seniority  # noqa: E402
from backend.vectorstore import JobVectorStore  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
DATA_DIR = EVAL_DIR.parent / "data"


def load_jobs() -> dict[str, Job]:
    with open(DATA_DIR / "sample_jobs.json") as f:
        raw = json.load(f)
    jobs = [Job(**item) for item in raw]
    return {j.id: j for j in jobs}


def load_labels() -> dict:
    with open(EVAL_DIR / "labeled_pairs.json") as f:
        return json.load(f)


def precision_at_k(ranked_job_ids: list[str], relevant_ids: set[str], k: int = 5) -> float:
    top_k = ranked_job_ids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for jid in top_k if jid in relevant_ids)
    return hits / len(top_k)


def main():
    jobs_by_id = load_jobs()
    labels = load_labels()
    all_jobs = list(jobs_by_id.values())

    texts = [job_text_for_embedding(j.title, j.requirements, j.description) for j in all_jobs]
    vectors = embed_texts(texts)
    store = JobVectorStore(dim=vectors.shape[1])
    store.build(all_jobs, vectors)

    embedding_only_scores = []
    hybrid_scores = []

    for resume_key, resume_text in labels["resumes"].items():
        relevant = {
            p["job_id"] for p in labels["pairs"]
            if p["resume"] == resume_key and p["label"] == 1
        }
        if not relevant:
            continue

        query_vec = embed_text(resume_text)
        candidates = store.search(query_vec, top_k=len(all_jobs))  # (Job, embedding_score)

        # --- Embedding-only ranking ---
        emb_ranked = sorted(candidates, key=lambda pair: pair[1], reverse=True)
        emb_ranked_ids = [job.id for job, _ in emb_ranked]
        p5_emb = precision_at_k(emb_ranked_ids, relevant, k=5)
        embedding_only_scores.append(p5_emb)

        # --- Hybrid ranking ---
        resume_seniority = infer_seniority("", resume_text)
        hybrid_ranked = rank_jobs(candidates, resume_text, resume_seniority)
        hybrid_ranked_ids = [r.job.id for r in hybrid_ranked]
        p5_hybrid = precision_at_k(hybrid_ranked_ids, relevant, k=5)
        hybrid_scores.append(p5_hybrid)

        print(f"[{resume_key}] embedding-only P@5={p5_emb:.2f}   hybrid P@5={p5_hybrid:.2f}")

    avg_emb = sum(embedding_only_scores) / len(embedding_only_scores)
    avg_hybrid = sum(hybrid_scores) / len(hybrid_scores)

    print("\n=== Summary ===")
    print(f"Embedding-only avg precision@5: {avg_emb:.2f}")
    print(f"Hybrid avg precision@5:         {avg_hybrid:.2f}")


if __name__ == "__main__":
    main()
