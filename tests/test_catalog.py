import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.catalog import EmojiCatalog


def test_search_by_tag():
    catalog = EmojiCatalog('data/emoji_catalog.json')
    results = catalog.search('скелет')
    assert results
    assert results[0].id == 'skeleton_bulb'


def test_top_by_tier():
    catalog = EmojiCatalog('data/emoji_catalog.json')
    results = catalog.top_by_tier('s')
    assert len(results) == 1
    assert results[0].id == 'wifi_king'
