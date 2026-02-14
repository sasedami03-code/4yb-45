from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import random
import tempfile
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InputMediaPhoto,
    InputTextMessageContent,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from PIL import Image

if __package__ in {None, ""}:
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from bot.core import RateLimiter, TierCache, parse_top_page
    from bot.drawer import draw_tier_set, draw_top_preview
else:
    from .core import RateLimiter, TierCache, parse_top_page
    from .drawer import draw_tier_set, draw_top_preview

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ASSETS_DIR = Path(os.getenv("ASSETS_DIR", "assets"))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "database.db"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "cache"))
CACHE_UPDATE_MINUTES = int(os.getenv("CACHE_UPDATE_MINUTES", "1"))
CACHE_CHAT_ID = int(os.getenv("CACHE_CHAT_ID", "0"))
TOP_ITEMS_PER_PAGE = int(os.getenv("TOP_ITEMS_PER_PAGE", "140"))

MAX_UPDATES_PER_USER_WINDOW = int(os.getenv("MAX_UPDATES_PER_USER_WINDOW", "12"))
RATE_WINDOW_SECONDS = int(os.getenv("RATE_WINDOW_SECONDS", "10"))
MAX_GLOBAL_CONCURRENT_SENDS = int(os.getenv("MAX_GLOBAL_CONCURRENT_SENDS", "20"))
MAX_TOP_REQUESTS_PER_WINDOW = int(os.getenv("MAX_TOP_REQUESTS_PER_WINDOW", "3"))
TOP_WINDOW_SECONDS = int(os.getenv("TOP_WINDOW_SECONDS", "20"))
INLINE_RESULTS_LIMIT = int(os.getenv("INLINE_RESULTS_LIMIT", "20"))


class EmojiRatingBot:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.db: aiosqlite.Connection | None = None
        self.assets: list[str] = []
        self.cache = TierCache()
        self.cache_lock = asyncio.Lock()
        self.refresh_task: asyncio.Task | None = None
        self.emote_file_ids: dict[str, str] = {}
        self.last_known_total_votes: int = -1
        self.asset_hashes: dict[str, int] = {}
        self.global_send_semaphore = asyncio.Semaphore(MAX_GLOBAL_CONCURRENT_SENDS)
        self.vote_rate_limiter = RateLimiter(MAX_UPDATES_PER_USER_WINDOW, RATE_WINDOW_SECONDS)
        self.top_rate_limiter = RateLimiter(MAX_TOP_REQUESTS_PER_WINDOW, TOP_WINDOW_SECONDS)

    async def init(self) -> None:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(DATABASE_PATH)
        await self.db.execute("PRAGMA journal_mode=WAL;")
        await self.db.execute("PRAGMA synchronous=NORMAL;")
        await self.db.execute("PRAGMA temp_store=MEMORY;")
        await self.db.execute("PRAGMA cache_size=-20000;")
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS emotes (
                filename TEXT PRIMARY KEY,
                total_score INTEGER NOT NULL DEFAULT 0,
                votes_count INTEGER NOT NULL DEFAULT 0,
                average_rating REAL NOT NULL DEFAULT 0
            )
            """
        )
        await self.db.commit()
        await self._sync_assets_to_db()
        self._build_asset_hashes()
        if CACHE_CHAT_ID:
            await self._warmup_emote_file_ids()

    async def close(self) -> None:
        if self.refresh_task:
            self.refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.refresh_task
        if self.db:
            await self.db.close()

    async def _sync_assets_to_db(self) -> None:
        files = sorted(
            file.name
            for file in ASSETS_DIR.iterdir()
            if file.is_file() and file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".ppm"}
        )
        self.assets = files
        if not self.db:
            return
        for filename in files:
            await self.db.execute("INSERT OR IGNORE INTO emotes(filename) VALUES (?)", (filename,))
        await self.db.commit()

    @staticmethod
    def _ahash(image: Image.Image, size: int = 8) -> int:
        gray = image.convert("L").resize((size, size), Image.Resampling.BILINEAR)
        pixels = list(gray.getdata())
        avg = sum(pixels) / len(pixels)
        bits = 0
        for idx, px in enumerate(pixels):
            if px >= avg:
                bits |= 1 << idx
        return bits

    @staticmethod
    def _hamming(a: int, b: int) -> int:
        return (a ^ b).bit_count()

    def _build_asset_hashes(self) -> None:
        self.asset_hashes.clear()
        for filename in self.assets:
            path = ASSETS_DIR / filename
            try:
                with Image.open(path) as img:
                    self.asset_hashes[filename] = self._ahash(img)
            except OSError:
                continue

    async def _warmup_emote_file_ids(self) -> None:
        for filename in self.assets:
            if filename in self.emote_file_ids:
                continue
            try:
                async with self.global_send_semaphore:
                    sent = await self.bot.send_photo(chat_id=CACHE_CHAT_ID, photo=FSInputFile(ASSETS_DIR / filename))
                if sent.photo:
                    self.emote_file_ids[filename] = sent.photo[-1].file_id
            except Exception:  # noqa: BLE001
                logging.exception("Не удалось прогреть file_id для %s", filename)

    def _vote_keyboard(self, filename: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        for score in range(1, 11):
            kb.add(InlineKeyboardButton(text=str(score), callback_data=f"rate:{score}:{filename}"))
        kb.adjust(5)
        return kb.as_markup()

    @staticmethod
    def _display_name(filename: str) -> str:
        stem = Path(filename).stem
        return stem.replace("_", " ").replace("-", " ").title()

    def search_assets(self, query: str, limit: int = INLINE_RESULTS_LIMIT) -> list[str]:
        if not self.assets:
            return []

        q = query.strip().lower()
        if not q:
            shuffled = self.assets[:]
            random.shuffle(shuffled)
            return shuffled[:limit]

        matched = [name for name in self.assets if q in Path(name).stem.lower() or q in name.lower()]
        if matched:
            return matched[:limit]

        shuffled = self.assets[:]
        random.shuffle(shuffled)
        return shuffled[: min(limit, 5)]

    async def detect_by_photo(self, image_bytes: bytes, top_k: int = 3) -> list[tuple[str, float]]:
        if not self.asset_hashes:
            return []

        try:
            with Image.open(BytesIO(image_bytes)) as img:
                query_hash = self._ahash(img)
        except OSError:
            return []

        scored: list[tuple[str, float]] = []
        for filename, h in self.asset_hashes.items():
            dist = self._hamming(query_hash, h)
            similarity = max(0.0, 1.0 - (dist / 64.0))
            scored.append((filename, similarity))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    async def send_random_vote(self, message: Message) -> None:
        if not self.assets:
            await message.answer("Папка assets пуста. Добавьте изображения эмодзи.")
            return

        filename = random.choice(self.assets)
        photo_source: str | FSInputFile = self.emote_file_ids.get(filename, FSInputFile(ASSETS_DIR / filename))
        async with self.global_send_semaphore:
            sent_message = await message.answer_photo(
                photo=photo_source,
                caption="Оцените эмодзи от 1 до 10:",
                reply_markup=self._vote_keyboard(filename),
            )

        if sent_message.photo:
            self.emote_file_ids[filename] = sent_message.photo[-1].file_id

    async def add_vote(self, filename: str, score: int) -> float:
        if not self.db:
            raise RuntimeError("DB is not initialized")
        async with self.db.execute(
            """
            UPDATE emotes
            SET total_score = total_score + :score,
                votes_count = votes_count + 1,
                average_rating = CAST(total_score + :score AS REAL) / (votes_count + 1)
            WHERE filename = :filename
            RETURNING average_rating
            """,
            {"score": score, "filename": filename},
        ) as cursor:
            row = await cursor.fetchone()
        await self.db.commit()
        return float(row[0]) if row else 0.0

    async def fetch_sorted_emotes(self) -> list[dict]:
        if not self.db:
            return []
        async with self.db.execute(
            "SELECT filename, total_score, votes_count, average_rating FROM emotes ORDER BY average_rating DESC, votes_count DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "filename": row[0],
                "total_score": row[1],
                "votes_count": row[2],
                "average_rating": float(row[3] or 0),
            }
            for row in rows
        ]

    async def fetch_total_votes(self) -> int:
        if not self.db:
            return 0
        async with self.db.execute("SELECT COALESCE(SUM(votes_count), 0) FROM emotes") as cursor:
            row = await cursor.fetchone()
        return int(row[0] or 0)

    async def regenerate_cache(self) -> None:
        total_votes = await self.fetch_total_votes()

        async with self.cache_lock:
            has_cache = bool(self.cache.preview_page_file_ids or self.cache.preview_page_paths)
            unchanged = has_cache and total_votes == self.last_known_total_votes
            if unchanged:
                now = datetime.now()
                self.cache.generated_at = now
                self.cache.next_update_at = now + timedelta(minutes=CACHE_UPDATE_MINUTES)
                self.cache.total_votes = total_votes
                self.cache.skipped_regenerations += 1
                return

        emotes = await self.fetch_sorted_emotes()
        tiers = {"S": [], "A": [], "B": [], "C": []}
        for emote in emotes:
            rating = emote["average_rating"]
            if rating >= 9.0:
                tiers["S"].append(emote)
            elif rating >= 7.0:
                tiers["A"].append(emote)
            elif rating >= 5.0:
                tiers["B"].append(emote)
            else:
                tiers["C"].append(emote)

        tier_paths_map = await asyncio.to_thread(draw_tier_set, tiers, ASSETS_DIR, CACHE_DIR)
        ordered_paths = [tier_paths_map[key] for key in ("S", "A", "B", "C")]

        total_emotes = len(emotes)
        pages_count = max(1, math.ceil(total_emotes / TOP_ITEMS_PER_PAGE))
        page_paths: list[Path] = []
        for page_idx in range(pages_count):
            start = page_idx * TOP_ITEMS_PER_PAGE
            page_path = await asyncio.to_thread(
                draw_top_preview,
                emotes,
                ASSETS_DIR,
                CACHE_DIR / f"top_preview_{page_idx + 1}.jpg",
                TOP_ITEMS_PER_PAGE,
                start,
                page_idx + 1,
                pages_count,
            )
            page_paths.append(page_path)

        page_file_ids: list[str] = []
        if CACHE_CHAT_ID:
            for page_path in page_paths:
                async with self.global_send_semaphore:
                    sent = await self.bot.send_photo(chat_id=CACHE_CHAT_ID, photo=FSInputFile(page_path))
                if sent.photo:
                    page_file_ids.append(sent.photo[-1].file_id)

        async with self.cache_lock:
            self.cache.local_paths = ordered_paths
            self.cache.file_ids = []
            self.cache.preview_page_paths = page_paths
            self.cache.preview_page_file_ids = page_file_ids
            self.cache.preview_path = page_paths[0] if page_paths else None
            self.cache.preview_file_id = page_file_ids[0] if page_file_ids else None
            self.cache.total_votes = total_votes
            self.cache.total_emotes = total_emotes
            self.cache.generated_at = datetime.now()
            self.cache.next_update_at = self.cache.generated_at + timedelta(minutes=CACHE_UPDATE_MINUTES)
            self.last_known_total_votes = total_votes
            self.cache.skipped_regenerations = 0

    async def refresh_loop(self) -> None:
        while True:
            try:
                await self.regenerate_cache()
            except Exception:  # noqa: BLE001
                logging.exception("Ошибка обновления tier-кэша")
            await asyncio.sleep(CACHE_UPDATE_MINUTES * 60)


router = Router()
service: EmojiRatingBot | None = None


def _build_top_caption(cache_snapshot: TierCache, page: int, total_pages: int) -> str:
    generated = cache_snapshot.generated_at.strftime("%H:%M") if cache_snapshot.generated_at else "-"
    next_update = cache_snapshot.next_update_at.strftime("%H:%M") if cache_snapshot.next_update_at else "-"
    start_index = (page - 1) * TOP_ITEMS_PER_PAGE + 1
    end_index = min(page * TOP_ITEMS_PER_PAGE, cache_snapshot.total_emotes)

    return (
        "🏆 Текущий рейтинг эмодзи (быстрое превью)\n"
        f"📄 Страница: {page}/{total_pages} (позиции {start_index}-{end_index})\n"
        f"🔄 Данные обновляются раз в {CACHE_UPDATE_MINUTES} минут.\n"
        f"🕒 Последнее обновление: {generated}\n"
        f"⏳ Следующее обновление: {next_update}\n\n"
        f"Всего голосов в базе: {cache_snapshot.total_votes}\n"
        f"⚡ Пропущено пересборок без новых голосов: {cache_snapshot.skipped_regenerations}"
    )


def _top_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if page > 1:
        kb.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"top_page:{page - 1}"))
    if page < total_pages:
        kb.add(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"top_page:{page + 1}"))
    kb.adjust(2)
    return kb.as_markup()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот рейтинга эмодзи Clash Royale.\n"
        "Команды:\n"
        "/vote — оценить случайный эмодзи\n"
        "/top [страница] — быстрый топ-превью рейтинг\n"
        "Инлайн: @your_bot или @your_bot miner"
    )


@router.message(Command("vote"))
@router.message(F.text == "🎲 Оценить")
async def cmd_vote(message: Message) -> None:
    if not service:
        return
    user_id = message.from_user.id if message.from_user else 0
    if not service.vote_rate_limiter.allow(user_id):
        await message.answer("Слишком часто. Подождите пару секунд и попробуйте снова.")
        return
    await service.send_random_vote(message)


@router.inline_query()
async def on_inline_query(inline_query: InlineQuery) -> None:
    if not service:
        await inline_query.answer([], cache_time=1, is_personal=True)
        return

    found = service.search_assets(inline_query.query, limit=INLINE_RESULTS_LIMIT)
    results: list[InlineQueryResultArticle] = []

    for filename in found:
        display_name = service._display_name(filename)
        file_id = service.emote_file_ids.get(filename)
        if file_id:
            results.append(
                InlineQueryResultCachedPhoto(
                    id=f"inline-photo:{filename}",
                    photo_file_id=file_id,
                    title=f"🎲 {display_name}",
                    description="Отправить фото и собрать оценки 1..10",
                    caption=f"🎲 Оцените эмодзи: {display_name}\nФайл: {filename}",
                    reply_markup=service._vote_keyboard(filename),
                )
            )
        else:
            results.append(
                InlineQueryResultArticle(
                    id=f"inline-text:{filename}",
                    title=f"🎲 {display_name}",
                    description="Пока без превью фото (укажите CACHE_CHAT_ID для прогрева)",
                    input_message_content=InputTextMessageContent(
                        message_text=f"🎲 Оцените эмодзи: {display_name}\nФайл: {filename}"
                    ),
                    reply_markup=service._vote_keyboard(filename),
                )
            )

    if not results:
        results.append(
            InlineQueryResultArticle(
                id="inline:empty",
                title="Нет подходящих эмодзи",
                description="Добавьте файлы в assets/",
                input_message_content=InputTextMessageContent(
                    message_text="Не нашёл эмодзи по запросу. Попробуйте другой тег."
                ),
            )
        )

    await inline_query.answer(results, cache_time=1, is_personal=True)



@router.callback_query(F.data.startswith("rate:"))
async def on_rate(callback: CallbackQuery) -> None:
    if not service or not callback.message or not callback.data:
        return

    user_id = callback.from_user.id if callback.from_user else 0
    if not service.vote_rate_limiter.allow(user_id):
        await callback.answer("Слишком часто. Немного подождите.", show_alert=False)
        return

    _, score_str, filename = callback.data.split(":", 2)
    score = int(score_str)
    await callback.answer("Голос сохранен")
    avg = await service.add_vote(filename, score)

    next_vote_task = asyncio.create_task(service.send_random_vote(callback.message))
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=f"Принято! Ваша оценка: {score}. Средний рейтинг: {avg:.2f}",
            reply_markup=None,
        )
    else:
        await callback.message.edit_text(
            text=f"Принято! Ваша оценка: {score}. Средний рейтинг: {avg:.2f}",
            reply_markup=None,
        )
    await next_vote_task


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    if not service:
        return

    user_id = message.from_user.id if message.from_user else 0
    if not service.top_rate_limiter.allow(user_id):
        await message.answer("/top сейчас вызывается слишком часто. Подождите немного.")
        return

    requested_page = parse_top_page(message.text)

    async with service.cache_lock:
        cache_snapshot = TierCache(
            file_ids=list(service.cache.file_ids),
            local_paths=list(service.cache.local_paths),
            generated_at=service.cache.generated_at,
            next_update_at=service.cache.next_update_at,
            total_votes=service.cache.total_votes,
            skipped_regenerations=service.cache.skipped_regenerations,
            preview_file_id=service.cache.preview_file_id,
            preview_path=service.cache.preview_path,
            preview_page_file_ids=list(service.cache.preview_page_file_ids),
            preview_page_paths=list(service.cache.preview_page_paths),
            total_emotes=service.cache.total_emotes,
        )

    if not cache_snapshot.preview_page_file_ids and not cache_snapshot.preview_page_paths:
        await message.answer("Рейтинг еще не готов, попробуйте через минуту.")
        return

    total_pages = max(1, len(cache_snapshot.preview_page_paths) or len(cache_snapshot.preview_page_file_ids))
    page = min(max(1, requested_page), total_pages)
    page_idx = page - 1

    photo: str | FSInputFile
    if page_idx < len(cache_snapshot.preview_page_file_ids):
        photo = cache_snapshot.preview_page_file_ids[page_idx]
    else:
        photo = FSInputFile(cache_snapshot.preview_page_paths[page_idx])

    caption = _build_top_caption(cache_snapshot, page, total_pages)
    reply_markup = _top_keyboard(page, total_pages)

    async with service.global_send_semaphore:
        await message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup)


@router.message(F.photo)
async def on_photo_scan(message: Message) -> None:
    if not service or not message.photo:
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
        await message.bot.download_file(file.file_path, destination=tmp.name)
        data = Path(tmp.name).read_bytes()

    matches = await service.detect_by_photo(data, top_k=3)
    if not matches:
        await message.answer("Не смог распознать эмодзи на фото.")
        return

    lines = ["🛒 Анализ скрина:"]
    if not service.db:
        await message.answer("\n".join(lines))
        return

    for filename, sim in matches:
        async with service.db.execute(
            "SELECT average_rating, votes_count FROM emotes WHERE filename = ?", (filename,)
        ) as cursor:
            row = await cursor.fetchone()
        rating = float(row[0] or 0.0) if row else 0.0
        votes = int(row[1] or 0) if row else 0
        verdict = "🔥 НАДО БРАТЬ" if rating >= 8 else "👍 норм" if rating >= 6 else "🗑 мусор"
        lines.append(
            f"• {service._display_name(filename)}: {rating:.2f}/10 ({votes} голосов), совпадение {sim*100:.1f}% — {verdict}"
        )

    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("top_page:"))
async def on_top_page(callback: CallbackQuery) -> None:
    if not service or not callback.message or not callback.data:
        return

    user_id = callback.from_user.id if callback.from_user else 0
    if not service.top_rate_limiter.allow(user_id):
        await callback.answer("Слишком часто. Подождите немного.", show_alert=False)
        return

    try:
        page = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная страница", show_alert=False)
        return

    async with service.cache_lock:
        cache_snapshot = TierCache(
            file_ids=list(service.cache.file_ids),
            local_paths=list(service.cache.local_paths),
            generated_at=service.cache.generated_at,
            next_update_at=service.cache.next_update_at,
            total_votes=service.cache.total_votes,
            skipped_regenerations=service.cache.skipped_regenerations,
            preview_file_id=service.cache.preview_file_id,
            preview_path=service.cache.preview_path,
            preview_page_file_ids=list(service.cache.preview_page_file_ids),
            preview_page_paths=list(service.cache.preview_page_paths),
            total_emotes=service.cache.total_emotes,
        )

    total_pages = max(1, len(cache_snapshot.preview_page_paths) or len(cache_snapshot.preview_page_file_ids))
    page = min(max(1, page), total_pages)
    page_idx = page - 1

    if page_idx < len(cache_snapshot.preview_page_file_ids):
        media = InputMediaPhoto(
            media=cache_snapshot.preview_page_file_ids[page_idx],
            caption=_build_top_caption(cache_snapshot, page, total_pages),
        )
    elif page_idx < len(cache_snapshot.preview_page_paths):
        media = InputMediaPhoto(
            media=FSInputFile(cache_snapshot.preview_page_paths[page_idx]),
            caption=_build_top_caption(cache_snapshot, page, total_pages),
        )
    else:
        await callback.answer("Страница недоступна", show_alert=False)
        return

    await callback.message.edit_media(media=media, reply_markup=_top_keyboard(page, total_pages))
    await callback.answer()


async def on_startup(bot: Bot) -> None:
    global service
    service = EmojiRatingBot(bot)
    await service.init()
    service.refresh_task = asyncio.create_task(service.refresh_loop())


async def on_shutdown(bot: Bot) -> None:
    del bot
    if service:
        await service.close()


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Укажите BOT_TOKEN в переменных окружения")

    logging.basicConfig(level=logging.INFO)
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
