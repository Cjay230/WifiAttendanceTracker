"""Prove the BFI model architecture LEARNS â€” on synthetic data, no hardware.

WHY: an untrained model outputs random scores; that only proves plumbing. This script
trains the model on fabricated "people" (distinct-but-noisy signatures) and shows test
accuracy climb from ~chance toward ~100%. That demonstrates the LSTM+FC architecture and
the whole training loop actually work end to end â€” the strongest thing you can show
before real gait data exists.

WHAT IT DOES NOT PROVE: real-world identification accuracy. Synthetic people are cleanly
separable by construction; real gait is far messier. This is an architecture check, not a
performance claim. Say that plainly when you show it.

Run:  PYTHONPATH=src python -m presence_platform.bfi.train_synthetic
"""

from __future__ import annotations

import torch
import torch.nn as nn

from presence_platform.bfi.model import GaitIdentifier
from presence_platform.bfi.synthetic import make_dataset


def run(num_people: int = 10, walks_per_person: int = 40, epochs: int = 30,
        seed: int = 0) -> float:
    torch.manual_seed(seed)

    x, lengths, y = make_dataset(num_people, walks_per_person, seed=seed)

    # 80/20 train/test split (shuffled).
    n = x.shape[0]
    perm = torch.randperm(n, generator=torch.Generator().manual_seed(seed))
    cut = int(n * 0.8)
    tr, te = perm[:cut], perm[cut:]

    model = GaitIdentifier(num_identities=num_people)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.CrossEntropyLoss()

    chance = 1.0 / num_people
    print(f"{num_people} people, {n} walks. Chance level = {chance:.1%}\n")

    for epoch in range(1, epochs + 1):
        model.train()
        opt.zero_grad()
        logits = model(x[tr], lengths[tr])
        loss = loss_fn(logits, y[tr])
        loss.backward()
        opt.step()

        if epoch % 5 == 0 or epoch == 1:
            acc = _accuracy(model, x[te], lengths[te], y[te])
            print(f"epoch {epoch:3d}  loss {loss.item():.3f}  test-acc {acc:.1%}")

    final = _accuracy(model, x[te], lengths[te], y[te])
    print(f"\nFinal test accuracy: {final:.1%}  (started near chance {chance:.1%})")
    return final


@torch.no_grad()
def _accuracy(model, x, lengths, y) -> float:
    model.eval()
    pred = model(x, lengths).argmax(dim=-1)
    return (pred == y).float().mean().item()


if __name__ == "__main__":
    run()
