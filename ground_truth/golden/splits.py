from __future__ import annotations

import random

from ground_truth.golden.schema import Item, Split


def assign_splits(items: list[Item], public_n: int, seed: int) -> list[Item]:
    if public_n > len(items):
        raise ValueError(f"public_n {public_n} exceeds corpus size {len(items)}")
    ordered = sorted(items, key=lambda i: i.item_id)
    rng = random.Random(seed)
    indices = list(range(len(ordered)))
    rng.shuffle(indices)
    public = set(indices[:public_n])
    return [
        item.model_copy(update={"split": Split.PUBLIC if n in public else Split.PRIVATE})
        for n, item in enumerate(ordered)
    ]
