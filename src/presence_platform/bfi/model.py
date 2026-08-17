"""BFI gait-identification model.

WHY: this is the *body* half of the two-axis design. Login tells us which account is on
the network (certain). This model, once trained, tells us which enrolled *person's* gait
matches the walk we observed (probabilistic). Its output becomes the ``match_score`` that
feeds the confirmation layer.

WHAT: the architecture from the BFId paper (Todt et al., CCS 2025) â€” a standard LSTM
followed by two fully-connected layers (each with batch-norm + ReLU), ending in a
per-identity score. Deliberately simple; the paper shows this simple model already
identifies gait with high accuracy, so we don't over-engineer.

STATUS: architecture only. Untrained, it outputs ~random scores â€” that is expected and
correct. This file proves the model *runs* and (via train_synthetic.py) that it *learns*.
Real accuracy needs real enrolled gait data, which needs the capture hardware.

Key design choice â€” VARIABLE LENGTH: people walk at different speeds, so BFI walks are
different lengths (the paper stresses this). We accept a padded batch + true lengths and
use pack_padded_sequence so the LSTM only reads real timesteps, never the padding.
"""

from __future__ import annotations

import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence

# The paper's BFI feature width: 10 quantized angles x 74 channels = 740 features/timestep.
BFI_FEATURE_DIM = 740


class GaitIdentifier(nn.Module):
    """LSTM + 2 FC identity classifier over BFI walk sequences.

    Args:
        num_identities: how many enrolled people the softmax spans. Configurable so that
            at enrollment time you just set it to the real headcount â€” no code change.
        input_dim: features per timestep (default 740, the paper's BFI width).
        hidden_dim: LSTM hidden size.
        fc_dim: width of the two fully-connected layers.
    """

    def __init__(
        self,
        num_identities: int,
        input_dim: int = BFI_FEATURE_DIM,
        hidden_dim: int = 128,
        fc_dim: int = 128,
    ) -> None:
        super().__init__()
        if num_identities < 2:
            raise ValueError("num_identities must be >= 2 (need at least two people to tell apart).")

        self.lstm = nn.LSTM(input_dim, hidden_dim, batch_first=True)

        # Two FC blocks: Linear -> BatchNorm -> ReLU, exactly as the paper describes.
        self.fc1 = nn.Linear(hidden_dim, fc_dim)
        self.bn1 = nn.BatchNorm1d(fc_dim)
        self.fc2 = nn.Linear(fc_dim, fc_dim)
        self.bn2 = nn.BatchNorm1d(fc_dim)
        self.relu = nn.ReLU()

        self.out = nn.Linear(fc_dim, num_identities)  # -> one logit per identity

    def forward(self, x: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        """
        x:       (batch, max_timesteps, input_dim)  padded walk sequences
        lengths: (batch,)                            true length of each walk
        returns: (batch, num_identities)             logits (softmax applied by the loss)
        """
        # Only read real timesteps, not padding.
        packed = pack_padded_sequence(
            x, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        _, (h_n, _) = self.lstm(packed)
        feat = h_n[-1]  # (batch, hidden_dim) â€” last hidden state summarizes the walk

        feat = self.relu(self.bn1(self.fc1(feat)))
        feat = self.relu(self.bn2(self.fc2(feat)))
        return self.out(feat)

    @torch.no_grad()
    def match_scores(self, x: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        """Inference helper: return per-identity probabilities (0â€“1) via softmax.

        The max of this vector is the ``match_score`` the confirmation layer consumes.
        """
        self.eval()
        return torch.softmax(self.forward(x, lengths), dim=-1)
