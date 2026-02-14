from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

CANVAS_WIDTH = 1000
ICON_SIZE = 72
GRID_PADDING_X = 20
GRID_PADDING_Y = 16
HEADER_HEIGHT = 72
CELL_HEIGHT = ICON_SIZE + 24
BACKGROUND_COLOR = (24, 26, 33)
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


def draw_tier_image(tier_name: str, emotes: Sequence[dict], assets_dir: Path, output_path: Path) -> Path:
    columns = max(1, (CANVAS_WIDTH - GRID_PADDING_X * 2) // (ICON_SIZE + 20))
    rows = max(1, (len(emotes) + columns - 1) // columns)
    canvas_height = HEADER_HEIGHT + GRID_PADDING_Y * 2 + rows * CELL_HEIGHT

    image = Image.new("RGB", (CANVAS_WIDTH, canvas_height), color=BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)

    title_font = _load_font(36)
    rating_font = _load_font(16)

    tier_color = TIER_COLORS.get(tier_name, (127, 127, 127))
    draw.rectangle((0, 0, CANVAS_WIDTH, HEADER_HEIGHT), fill=tier_color)
    title = f"{tier_name}-Tier"
    title_w = draw.textlength(title, font=title_font)
    draw.text(((CANVAS_WIDTH - title_w) / 2, 14), title, fill=(18, 18, 22), font=title_font)

    for idx, emote in enumerate(emotes):
        col = idx % columns
        row = idx // columns
        x = GRID_PADDING_X + col * (ICON_SIZE + 20)
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
        draw.text((x + (ICON_SIZE - rating_w) / 2, y + ICON_SIZE + 2), rating_text, fill=RATING_COLOR, font=rating_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", optimize=True, quality=82, progressive=True)
    return output_path


def draw_tier_set(tiers: dict[str, Sequence[dict]], assets_dir: Path, output_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for tier_name in ("S", "A", "B", "C"):
        tier_items = tiers.get(tier_name, [])
        tier_path = output_dir / f"tier_{tier_name}.jpg"
        paths[tier_name] = draw_tier_image(tier_name, tier_items, assets_dir, tier_path)
    return paths


def draw_top_preview(emotes: Sequence[dict], assets_dir: Path, output_path: Path, max_items: int = 140) -> Path:
    preview_items = list(emotes[:max_items])
    columns = max(1, (CANVAS_WIDTH - GRID_PADDING_X * 2) // (ICON_SIZE + 20))
    rows = max(1, (len(preview_items) + columns - 1) // columns)
    canvas_height = HEADER_HEIGHT + GRID_PADDING_Y * 2 + rows * CELL_HEIGHT

    image = Image.new("RGB", (CANVAS_WIDTH, canvas_height), color=BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)
    title_font = _load_font(30)
    rating_font = _load_font(16)

    title = "TOP preview (быстрый режим)"
    draw.rectangle((0, 0, CANVAS_WIDTH, HEADER_HEIGHT), fill=(66, 96, 171))
    draw.text((24, 18), title, fill=(245, 245, 245), font=title_font)

    for idx, emote in enumerate(preview_items):
        col = idx % columns
        row = idx // columns
        x = GRID_PADDING_X + col * (ICON_SIZE + 20)
        y = HEADER_HEIGHT + GRID_PADDING_Y + row * CELL_HEIGHT

        emote_path = assets_dir / emote["filename"]
        if emote_path.exists():
            with Image.open(emote_path) as source:
                icon = source.convert("RGBA").resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
            image.paste(icon, (x, y), icon)

        rating_text = f"{emote['average_rating']:.1f}"
        rating_w = draw.textlength(rating_text, font=rating_font)
        draw.text((x + (ICON_SIZE - rating_w) / 2, y + ICON_SIZE + 2), rating_text, fill=RATING_COLOR, font=rating_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", optimize=True, quality=80, progressive=True)
    return output_path
