from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .catalog import EmojiCatalog, EmojiEntry


@dataclass(frozen=True)
class ScanMatch:
    emoji: EmojiEntry
    score: float


class ShopScanner:
    def __init__(self, catalog: EmojiCatalog):
        self.catalog = catalog

    def scan(self, image_path: str | Path, top_k: int = 3) -> list[ScanMatch]:
        screen = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if screen is None:
            return []

        matches: list[ScanMatch] = []
        for entry in self.catalog.items:
            template = cv2.imread(entry.asset, cv2.IMREAD_GRAYSCALE)
            if template is None:
                continue

            if screen.shape[0] < template.shape[0] or screen.shape[1] < template.shape[1]:
                continue

            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            score = float(np.max(result))
            matches.append(ScanMatch(emoji=entry, score=score))

        matches.sort(key=lambda x: x.score, reverse=True)
        filtered = [m for m in matches if m.score >= 0.35]
        return filtered[:top_k] if filtered else matches[:top_k]
