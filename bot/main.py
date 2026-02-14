from __future__ import annotations

import os
import tempfile
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from .catalog import EmojiCatalog
from .scanner import ShopScanner

CATALOG = EmojiCatalog(Path("data/emoji_catalog.json"))
SCANNER = ShopScanner(CATALOG)
VOTES = defaultdict(lambda: defaultdict(int))
PACK_LINKS = {
    "S": "https://t.me/addstickers/TopSTierEmojiPack",
    "TRASH": "https://t.me/addstickers/TrashEmojiPack",
}


def rating_keyboard(emoji_id: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for score in range(1, 11):
        row.append(InlineKeyboardButton(str(score), callback_data=f"rate:{emoji_id}:{score}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def duel_keyboard(left_id: str, right_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("👈 Левый", callback_data=f"duel:{left_id}"), InlineKeyboardButton("👉 Правый", callback_data=f"duel:{right_id}")]]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Используй инлайн-режим: @botname <тег> или @botname duel.\n"
        "Команды: /pack S, /pack trash.\n"
        "Отправь скрин магазина — я попробую распознать эмодзи и показать рейтинг."
    )


async def pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    arg = context.args[0].upper() if context.args else "S"
    link = PACK_LINKS.get(arg)
    if not link:
        await update.message.reply_text("Доступно: /pack S или /pack trash")
        return
    await update.message.reply_text(f"Стикерпак {arg}: {link}")


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = (update.inline_query.query or "").strip()
    results = []

    if query.lower().startswith(("duel", "versus", "сравнить")):
        left = CATALOG.random()
        right = CATALOG.random()
        while right.id == left.id:
            right = CATALOG.random()
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title=f"Дуэль: {left.name} vs {right.name}",
                input_message_content=InputTextMessageContent(f"⚔️ Дуэль эмодзи\n{left.name} VS {right.name}"),
                reply_markup=duel_keyboard(left.id, right.id),
                description="Выберите победителя в чате",
            )
        )
    else:
        candidates = CATALOG.search(query)[:10]
        if not candidates:
            candidates = [CATALOG.random()]
        for item in candidates:
            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"{item.name} • {item.rating}/10",
                    description=f"{item.tier}-tier • теги: {', '.join(item.tags)}",
                    input_message_content=InputTextMessageContent(
                        f"🎲 Оценим эмодзи: {item.name}\nТекущий рейтинг: {item.rating}/10 ({item.tier}-tier)"
                    ),
                    reply_markup=rating_keyboard(item.id),
                )
            )

    await update.inline_query.answer(results, cache_time=1)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    payload = query.data.split(":")
    key = f"{query.message.chat_id}:{query.message.message_id}"

    if payload[0] == "rate":
        _, emoji_id, score = payload
        VOTES[key][int(score)] += 1
        total_votes = sum(VOTES[key].values())
        weighted = sum(s * c for s, c in VOTES[key].items()) / total_votes
        emoji = CATALOG.by_id(emoji_id)
        name = emoji.name if emoji else emoji_id
        await query.edit_message_text(
            f"🎯 {name}\nГолосов: {total_votes}\nСредняя оценка: {weighted:.2f}/10",
            reply_markup=rating_keyboard(emoji_id),
        )
    elif payload[0] == "duel":
        _, winner_id = payload
        winner = CATALOG.by_id(winner_id)
        winner_name = winner.name if winner else winner_id
        await query.edit_message_text(f"🏆 Победил: {winner_name}")


async def scan_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.photo:
        return

    photo = update.message.photo[-1]
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as tmp:
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(custom_path=tmp.name)
        matches = SCANNER.scan(tmp.name, top_k=3)

    if not matches:
        await update.message.reply_text("Не смог распознать эмодзи. Добавьте шаблоны в папку assets/ и попробуйте снова.")
        return

    lines = ["🛒 Анализ магазина:"]
    for m in matches:
        verdict = "🔥 НАДО БРАТЬ!" if m.emoji.rating >= 8 else "норм" if m.emoji.rating >= 6 else "мусор"
        lines.append(f"• {m.emoji.name}: {m.emoji.rating}/10 ({m.emoji.tier}-Tier) — {verdict}")
    await update.message.reply_text("\n".join(lines))


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Set BOT_TOKEN env var")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pack", pack))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, scan_photo))
    app.run_polling()


if __name__ == "__main__":
    main()
