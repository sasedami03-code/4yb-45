import sys
import time

import pytest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw

from bot.core import (
    RateLimiter,
    build_emoji_fingerprint,
    emoji_similarity_score,
    parse_media_urls,
    parse_ordered_labels,
    parse_top_page,
)


def test_parse_top_page_defaults_to_1():
    assert parse_top_page(None) == 1
    assert parse_top_page("/top") == 1
    assert parse_top_page("/top abc") == 1
    assert parse_top_page("/top -3") == 1


def test_parse_top_page_valid_number():
    assert parse_top_page("/top 2") == 2


def test_rate_limiter_blocks_after_limit_and_recovers():
    limiter = RateLimiter(limit=2, window_seconds=1)
    user_id = 123
    assert limiter.allow(user_id) is True
    assert limiter.allow(user_id) is True
    assert limiter.allow(user_id) is False

    time.sleep(1.1)
    assert limiter.allow(user_id) is True


def test_parse_media_urls_mixed_formats():
    by_name, ordered = parse_media_urls(
        [
            "https://example.com/1.png",
            "emoji_001.png,https://example.com/2.png",
            "emoji_002.png|https://example.com/3.png",
            "# comment",
            "   ",
        ]
    )
    assert ordered == ["https://example.com/1.png"]
    assert by_name["emoji_001.png"] == "https://example.com/2.png"
    assert by_name["emoji_002.png"] == "https://example.com/3.png"


def test_parse_media_urls_plain_order():
    by_name, ordered = parse_media_urls([
        'https://example.com/2.png',
        'https://example.com/3.png',
    ])
    assert by_name == {}
    assert ordered == ['https://example.com/2.png', 'https://example.com/3.png']


def test_parse_ordered_labels():
    labels = parse_ordered_labels([
        '# comment',
        '  ',
        'Король',
        'Скелет',
    ])
    assert labels == ['Король', 'Скелет']



def _make_square(color: tuple[int, int, int], accent: tuple[int, int, int] | None = None) -> Image.Image:
    img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((16, 16, 112, 112), radius=22, fill=color)
    if accent:
        draw.ellipse((46, 46, 82, 82), fill=accent)
    return img


def test_emoji_similarity_prefers_visual_match():
    red = _make_square((230, 60, 60), accent=(255, 220, 80))
    red_variant = _make_square((220, 70, 70), accent=(250, 210, 70))
    blue = _make_square((60, 90, 220), accent=(200, 240, 255))

    red_fp = build_emoji_fingerprint(red)
    red_variant_fp = build_emoji_fingerprint(red_variant)
    blue_fp = build_emoji_fingerprint(blue)

    close_score = emoji_similarity_score(red_fp, red_variant_fp)
    far_score = emoji_similarity_score(red_fp, blue_fp)

    assert close_score > far_score
    assert close_score > 0.70


def test_emoji_similarity_with_transparency_body_shape():
    full = Image.new("RGBA", (128, 128), (255, 200, 0, 255))
    sparse = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sparse)
    draw.ellipse((46, 46, 82, 82), fill=(255, 200, 0, 255))

    full_fp = build_emoji_fingerprint(full)
    sparse_fp = build_emoji_fingerprint(sparse)

    score = emoji_similarity_score(full_fp, sparse_fp)
    assert score < 0.75
