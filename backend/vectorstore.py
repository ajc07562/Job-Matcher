"""
Thin FAISS wrapper. Uses a flat index with inner product over L2-normalized vectors,
which is equivalent to cosine similarity. Flat index is O(n) per query — fine up to a
few hundred thousand vectors, which comfortably covers this project's scale.
For a larger corpus, swap in IndexIVFFlat (see README tradeoffs section).
"""
import faiss
import numpy as np

from backend.models import Job


class JobVectorStore:
    def __init__(self, dim: int):
        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)
        self.jobs: list[Job] = []
        self.vectors: np.ndarray = np.zeros((0, dim), dtype="float32")

    def build(self, jobs: list[Job], vectors: np.ndarray) -> None:
        assert len(jobs) == vectors.shape[0], "jobs and vectors must align 1:1"
        self.jobs = list(jobs)
        self.vectors = vectors.astype("float32")  # kept for the embedding-space viz (PCA/k-means need the raw matrix, not just FAISS's internal index)
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)

    def search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[Job, float]]:
        if len(self.jobs) == 0:
            return []
        top_k = min(top_k, len(self.jobs))
        query = query_vector.reshape(1, -1).astype("float32")
        scores, indices = self.index.search(query, top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results.append((self.jobs[idx], float(score)))
        return results

    def __len__(self) -> int:
        return len(self.jobs)