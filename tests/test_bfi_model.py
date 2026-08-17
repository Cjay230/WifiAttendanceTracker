"""Tests for the BFI gait model.

Three levels of "works":
  1. PLUMBING  â€” a variable-length batch runs a forward pass, right output shape.
  2. BRIDGE    â€” the model's match score flows into the confirmation layer.
  3. LEARNING  â€” (smoke) a few epochs on synthetic data beat chance.
"""

from __future__ import annotations

import torch

from presence_platform.bfi.model import GaitIdentifier, BFI_FEATURE_DIM
from presence_platform.bfi.synthetic import make_dataset
from presence_platform.bfi.train_synthetic import run as train_run

from presence_platform.pipeline.presence_engine import PresenceRecord, PresenceState
from presence_platform.pipeline.confirmation import (
    confirm, GaitObservation, ConfirmationState,
)


# --- 1. plumbing ---------------------------------------------------------------

def test_forward_pass_shape():
    model = GaitIdentifier(num_identities=5)
    x, lengths, _ = make_dataset(num_people=5, walks_per_person=2, seed=1)
    out = model(x, lengths)
    assert out.shape == (10, 5)  # (batch, num_identities)

def test_accepts_variable_lengths():
    # walks of genuinely different lengths in one batch must not error
    model = GaitIdentifier(num_identities=3)
    x, lengths, _ = make_dataset(num_people=3, walks_per_person=4, min_len=10, max_len=55, seed=2)
    assert len(set(lengths.tolist())) > 1  # lengths really do vary
    model.eval()
    out = model(x, lengths)
    assert out.shape[0] == x.shape[0]

def test_match_scores_are_probabilities():
    model = GaitIdentifier(num_identities=4)
    x, lengths, _ = make_dataset(num_people=4, walks_per_person=1, seed=3)
    scores = model.match_scores(x, lengths)
    assert torch.allclose(scores.sum(dim=-1), torch.ones(scores.shape[0]), atol=1e-5)
    assert (scores >= 0).all() and (scores <= 1).all()

def test_rejects_too_few_identities():
    try:
        GaitIdentifier(num_identities=1)
        assert False, "should reject <2 identities"
    except ValueError:
        pass


# --- 2. bridge: model output -> confirmation layer -----------------------------

def test_model_score_feeds_confirmation():
    """The whole point: a gait score becomes a GaitObservation and drives confirm()."""
    model = GaitIdentifier(num_identities=4)
    x, lengths, _ = make_dataset(num_people=4, walks_per_person=1, seed=4)

    scores = model.match_scores(x[:1], lengths[:1])
    top_score = scores.max().item()  # best-matching identity's probability

    gait = GaitObservation("alice", "ap-3", match_score=top_score, timestamp=1000)
    record = PresenceRecord("alice", "ap-3", check_in=0, last_seen=1000,
                            state=PresenceState.PRESENT, source="freeradius")

    cp = confirm(record, gait, now=1000, pending_timeout_ms=5*60*1000)
    # untrained scores are ~uniform, so we don't assert WHICH band â€” only that the
    # pipe connects and produces a valid verdict.
    assert cp.confirmation_state in ConfirmationState
    assert cp.confidence == top_score


# --- 3. learning (smoke) -------------------------------------------------------

def test_learns_above_chance():
    acc = train_run(num_people=5, walks_per_person=20, epochs=8, seed=0)
    assert acc > 0.5  # chance is 20%; must clearly beat it
