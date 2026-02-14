from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


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
