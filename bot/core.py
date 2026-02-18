from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

_RESAMPLING = getattr(Image, "Resampling", Image)
_BILINEAR = _RESAMPLING.BILINEAR
_LANCZOS = _RESAMPLING.LANCZOS
_ADAPTIVE_PALETTE = getattr(getattr(Image, "Palette", Image), "ADAPTIVE", getattr(Image, "ADAPTIVE", 1))


@dataclass
class TierCache:
    file_ids: list[str] = field(default_factory=list)
    local_paths: list[Path] = field(default_factory=list)
    generated_at: datetime | None = None
    next_update_at: datetime | None = None
    total_votes: int = 0
    skipped_regenerations: int = 0
    preview_file_id: str | None = None
    preview_path: Path | None = None
    preview_page_file_ids: list[str] = field(default_factory=list)
    preview_page_paths: list[Path] = field(default_factory=list)
    total_emotes: int = 0


@dataclass(frozen=True)
class EmojiFingerprint:
    ahash: int
    dhash: int
    color_hist: tuple[float, ...]
    body_ratio: float
    edge_ratio: float


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.events: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, key: int) -> bool:
        now = time.monotonic()
        bucket = self.events[key]
        threshold = now - self.window_seconds
        while bucket and bucket[0] < threshold:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


def parse_top_page(text: str | None) -> int:
    if not text:
        return 1
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return 1
    try:
        return max(1, int(parts[1]))
    except ValueError:
        return 1


def parse_media_urls(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    by_name: dict[str, str] = {}
    ordered: list[str] = []

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue

        if ',' in line:
            left, right = [x.strip() for x in line.split(',', 1)]
            if left and right:
                by_name[left] = right
                continue

        if '|' in line:
            left, right = [x.strip() for x in line.split('|', 1)]
            if left and right:
                by_name[left] = right
                continue

        ordered.append(line)

    return by_name, ordered


def parse_ordered_labels(lines: list[str]) -> list[str]:
    labels: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        labels.append(line)
    return labels


def _ahash(image: Image.Image, size: int = 16) -> int:
    gray = ImageOps.exif_transpose(image).convert("L").resize((size, size), _BILINEAR)
    pixels = list(gray.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for idx, px in enumerate(pixels):
        if px >= avg:
            bits |= 1 << idx
    return bits


def _dhash(image: Image.Image, size: int = 16) -> int:
    gray = ImageOps.exif_transpose(image).convert("L").resize((size + 1, size), _BILINEAR)
    pixels = list(gray.getdata())
    bits = 0
    bit_idx = 0
    row_stride = size + 1
    for y in range(size):
        row = y * row_stride
        for x in range(size):
            if pixels[row + x] <= pixels[row + x + 1]:
                bits |= 1 << bit_idx
            bit_idx += 1
    return bits


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def build_emoji_fingerprint(image: Image.Image) -> EmojiFingerprint:
    prepared = ImageOps.exif_transpose(image).convert("RGBA").resize((128, 128), _LANCZOS)
    alpha = prepared.getchannel("A")
    alpha_data = list(alpha.getdata())
    body_pixels = sum(1 for px in alpha_data if px > 12)
    body_ratio = body_pixels / len(alpha_data)

    rgb = prepared.convert("RGB")
    edge_img = rgb.convert("L").filter(ImageFilter.FIND_EDGES)
    edge_data = list(edge_img.getdata())
    edge_ratio = sum(1 for px in edge_data if px > 45) / len(edge_data)

    quantized = rgb.convert("P", palette=_ADAPTIVE_PALETTE, colors=32)
    hist = quantized.histogram()[:32]
    total = float(sum(hist)) or 1.0
    color_hist = tuple(v / total for v in hist)

    return EmojiFingerprint(
        ahash=_ahash(rgb),
        dhash=_dhash(rgb),
        color_hist=color_hist,
        body_ratio=body_ratio,
        edge_ratio=edge_ratio,
    )


def emoji_similarity_score(query: EmojiFingerprint, candidate: EmojiFingerprint) -> float:
    hash_a = 1.0 - (_hamming(query.ahash, candidate.ahash) / 256.0)
    hash_d = 1.0 - (_hamming(query.dhash, candidate.dhash) / 256.0)

    color_diff = sum(abs(a - b) for a, b in zip(query.color_hist, candidate.color_hist)) / 2.0
    color_score = max(0.0, 1.0 - color_diff)

    body_score = max(0.0, 1.0 - abs(query.body_ratio - candidate.body_ratio) / 0.45)
    edge_score = max(0.0, 1.0 - abs(query.edge_ratio - candidate.edge_ratio) / 0.45)

    forensic_score = (hash_a * 0.35) + (hash_d * 0.25) + (color_score * 0.2) + (body_score * 0.12) + (edge_score * 0.08)
    return max(0.0, min(1.0, forensic_score))
