import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.core import RateLimiter, parse_media_urls, parse_ordered_labels, parse_top_page


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

