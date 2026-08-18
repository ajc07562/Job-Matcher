"""
PCA (dimensionality reduction) and k-means (clustering) for the embedding-space
visualization — implemented directly with numpy rather than pulling in scikit-learn.

Both are small, well-understood algorithms. Implementing them directly means this
project's only heavy ML dependency stays sentence-transformers, and the actual math
is inspectable in one file instead of hidden behind a library call — which is
arguably more useful for a feature whose whole point is "show people you understand
what's happening with embeddings," not just "call a library that does it."
"""
import numpy as np


def pca_2d(vectors: np.ndarray) -> np.ndarray:
    """
    Project (N, D) vectors onto their top-2 principal components -> (N, 2).

    Standard PCA via SVD on the mean-centered data: the top singular vectors of the
    centered data matrix are the directions of maximum variance, which is exactly
    what PCA is looking for — no need to explicitly build the (D, D) covariance
    matrix and eigendecompose it, SVD gives the same components directly and is
    numerically better-behaved.
    """
    n = vectors.shape[0]
    if n < 2:
        # Not enough points for "directions of maximum variance" to mean anything.
        return np.zeros((n, 2), dtype="float32")

    mean = vectors.mean(axis=0)
    centered = vectors - mean

    # Economy SVD (full_matrices=False) — we only need the first 2 components,
    # no reason to compute the full D x D matrix for D=384.
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    num_components = min(2, vt.shape[0])
    components = vt[:num_components]  # (num_components, D)

    projected = centered @ components.T  # (N, num_components)
    if num_components < 2:
        # Degenerate case: fewer usable components than 2 (e.g. N=2 total points,
        # or all vectors identical). Pad with zeros so callers always get (N, 2).
        pad = np.zeros((n, 2 - num_components), dtype="float32")
        projected = np.hstack([projected, pad])

    return projected.astype("float32")


def kmeans(vectors: np.ndarray, k: int, iterations: int = 50, seed: int = 42) -> np.ndarray:
    """
    Lloyd's-algorithm k-means. Returns an (N,) int array of cluster labels in [0, k).

    k is clamped to at most N (can't have more clusters than points). Initial
    centroids are chosen with a farthest-point heuristic (pick one point at random,
    then repeatedly pick whichever remaining point is farthest from all chosen
    centroids so far) rather than pure random init — plain random init can leave
    centroids clustered together by chance on small N, which tends to produce empty
    clusters after the first iteration. This is a cheap approximation of k-means++
    that avoids that failure mode without pulling in a clustering library for it.
    """
    n = vectors.shape[0]
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)

    if k == 1 or n == 1:
        return np.zeros(n, dtype=int)

    chosen = [int(rng.integers(0, n))]
    for _ in range(k - 1):
        # Distance from every point to its nearest already-chosen centroid.
        dists_to_chosen = np.stack([np.linalg.norm(vectors - vectors[i], axis=1) for i in chosen])
        min_dists = dists_to_chosen.min(axis=0)
        chosen.append(int(np.argmax(min_dists)))

    centroids = vectors[chosen].copy()
    labels = np.full(n, -1, dtype=int)

    for _ in range(iterations):
        dists = np.linalg.norm(vectors[:, None, :] - centroids[None, :, :], axis=2)  # (N, k)
        new_labels = np.argmin(dists, axis=1)

        if np.array_equal(new_labels, labels):
            break  # converged
        labels = new_labels

        for c in range(k):
            members = vectors[labels == c]
            if len(members) > 0:
                centroids[c] = members.mean(axis=0)
            # An empty cluster keeps its previous centroid rather than resetting —
            # rare in practice with farthest-point init, and this is simpler and
            # more stable than re-seeding mid-run.

    return labels
