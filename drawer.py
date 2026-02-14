from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont

CANVAS_WIDTH = 1100
ICON_SIZE = 84
GRID_PADDING_X = 24
GRID_PADDING_Y = 20
HEADER_HEIGHT = 88
CELL_HEIGHT = ICON_SIZE + 30
BACKGROUND_COLOR = (24, 26, 33)
TEXT_COLOR = (245, 245, 245)
RATING_COLOR = (180, 186, 200)

TIER_COLORS = {
    "S": (255, 201, 64),
    "A": (161, 111, 255),
    "B": (111, 186, 98),
    "C": (95, 102, 119),
}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in ("DejaVuSans-Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _chunk(items: Sequence[dict], size: int) -> Iterable[Sequence[dict]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def draw_tier_image(tier_name: str, emotes: Sequence[dict], assets_dir: Path, output_path: Path) -> Path:
    columns = max(1, (CANVAS_WIDTH - GRID_PADDING_X * 2) // (ICON_SIZE + 24))
    rows = max(1, (len(emotes) + columns - 1) // columns)
    canvas_height = HEADER_HEIGHT + GRID_PADDING_Y * 2 + rows * CELL_HEIGHT

    image = Image.new("RGB", (CANVAS_WIDTH, canvas_height), color=BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)

    title_font = _load_font(44)
    rating_font = _load_font(20)

    tier_color = TIER_COLORS.get(tier_name, (127, 127, 127))
    draw.rectangle((0, 0, CANVAS_WIDTH, HEADER_HEIGHT), fill=tier_color)
    title = f"{tier_name}-Tier"
    title_w = draw.textlength(title, font=title_font)
    draw.text(((CANVAS_WIDTH - title_w) / 2, 18), title, fill=(18, 18, 22), font=title_font)

    for idx, emote in enumerate(emotes):
        col = idx % columns
        row = idx // columns
        x = GRID_PADDING_X + col * (ICON_SIZE + 24)
        y = HEADER_HEIGHT + GRID_PADDING_Y + row * CELL_HEIGHT

        emote_path = assets_dir / emote["filename"]
        if emote_path.exists():
            with Image.open(emote_path) as source:
                icon = source.convert("RGBA").resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
            image.paste(icon, (x, y), icon)
        else:
            draw.rectangle((x, y, x + ICON_SIZE, y + ICON_SIZE), outline=(255, 70, 70), width=2)

        rating_text = f"{emote['average_rating']:.1f}"
        rating_w = draw.textlength(rating_text, font=rating_font)
        draw.text((x + (ICON_SIZE - rating_w) / 2, y + ICON_SIZE + 4), rating_text, fill=RATING_COLOR, font=rating_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return output_path


def draw_tier_set(tiers: dict[str, Sequence[dict]], assets_dir: Path, output_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for tier_name in ("S", "A", "B", "C"):
        tier_items = tiers.get(tier_name, [])
        tier_path = output_dir / f"tier_{tier_name}.png"
        paths[tier_name] = draw_tier_image(tier_name, tier_items, assets_dir, tier_path)
    return paths
