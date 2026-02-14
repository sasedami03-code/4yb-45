from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EmojiEntry:
    id: str
    name: str
    tier: str
    rating: float
    tags: tuple[str, ...]
    asset: str


class EmojiCatalog:
    def __init__(self, source: str | Path):
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
        self.items = [
            EmojiEntry(
                id=item["id"],
                name=item["name"],
                tier=item["tier"],
                rating=float(item["rating"]),
                tags=tuple(item["tags"]),
                asset=item["asset"],
            )
            for item in raw
        ]

    def random(self) -> EmojiEntry:
        return random.choice(self.items)

    def by_id(self, emoji_id: str) -> EmojiEntry | None:
        return next((item for item in self.items if item.id == emoji_id), None)

    def search(self, query: str) -> list[EmojiEntry]:
        q = query.strip().lower()
        if not q:
            return sorted(self.items, key=lambda x: x.rating, reverse=True)

        matched = []
        for item in self.items:
            haystack = " ".join((item.name.lower(), item.tier.lower(), *[t.lower() for t in item.tags]))
            if q in haystack:
                matched.append(item)
        return sorted(matched, key=lambda x: x.rating, reverse=True)

    def top_by_tier(self, tier: str) -> list[EmojiEntry]:
        t = tier.strip().upper()
        return sorted((x for x in self.items if x.tier.upper() == t), key=lambda x: x.rating, reverse=True)
