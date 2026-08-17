"""Synthetic BFI gait data.

WHY: real gait needs the capture board + enrolled people walking. To prove the model
*architecture learns* before any of that exists, we fabricate "people" as distinct,
repeatable movement signatures with noise. This is NOT real gait and proves nothing about
real-world accuracy â€” it only proves the model can separate classes that are actually
separable, i.e. the learning machinery works end to end.

WHAT: each fake person gets a fixed random "signature" (a per-feature base pattern +
frequency). A walk is that signature unrolled over a random number of timesteps (variable
length, like real walks) plus Gaussian noise, so no two walks are identical.
"""

from __future__ import annotations

import numpy as np
import torch

from presence_platform.bfi.model import BFI_FEATURE_DIM


def _person_signature(rng: np.random.Generator, feature_dim: int) -> dict:
    """A stable per-person fingerprint: base offsets + per-feature sine frequencies."""
    return {
        "base": rng.normal(0, 1, size=feature_dim),
        "freq": rng.uniform(0.05, 0.5, size=feature_dim),
        "phase": rng.uniform(0, 2 * np.pi, size=feature_dim),
    }


def make_walk(sig: dict, length: int, feature_dim: int, rng: np.random.Generator,
              noise: float = 0.3) -> np.ndarray:
    """One variable-length walk for a person: their signature over time + noise."""
    t = np.arange(length)[:, None]  # (length, 1)
    pattern = sig["base"] + np.sin(sig["freq"] * t + sig["phase"])  # (length, feature_dim)
    pattern += rng.normal(0, noise, size=pattern.shape)
    return pattern.astype(np.float32)


def make_dataset(
    num_people: int,
    walks_per_person: int,
    feature_dim: int = BFI_FEATURE_DIM,
    min_len: int = 20,
    max_len: int = 60,
    seed: int = 0,
):
    """Build a toy dataset of variable-length walks.

    Returns (padded_x, lengths, labels):
      padded_x: (N, max_len_in_batch, feature_dim) float tensor
      lengths:  (N,) int tensor of true walk lengths
      labels:   (N,) int tensor of person indices
    """
    rng = np.random.default_rng(seed)
    sigs = [_person_signature(rng, feature_dim) for _ in range(num_people)]

    walks, lengths, labels = [], [], []
    for person in range(num_people):
        for _ in range(walks_per_person):
            length = int(rng.integers(min_len, max_len + 1))
            walks.append(make_walk(sigs[person], length, feature_dim, rng))
            lengths.append(length)
            labels.append(person)

    max_len_batch = max(lengths)
    padded = np.zeros((len(walks), max_len_batch, feature_dim), dtype=np.float32)
    for i, w in enumerate(walks):
        padded[i, : len(w)] = w

    return (
        torch.from_numpy(padded),
        torch.tensor(lengths, dtype=torch.long),
        torch.tensor(labels, dtype=torch.long),
    )
