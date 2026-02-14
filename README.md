# Clash Royale Emoji Rating Bot

Бот собирает живой рейтинг эмодзи через голосования в чате и показывает ТОП с кэшируемыми превью-страницами.

## Что реализовано

- `/vote` — отправка случайного эмодзи из `assets/` с кнопками оценки 1..10.
- Хранение голосов в SQLite (`database.db`):
  - `total_score`, `votes_count`, `average_rating`.
- `/top [страница]` — выдача превью рейтинга с пагинацией и обновляемым кэшем.
- Инлайн-режим (`@botname`, `@botname miner`) с карточками для голосования в любом чате.
- Автопересборка кэша раз в `CACHE_UPDATE_MINUTES` минут.
- Anti-spam лимиты:
  - на голосования,
  - на частоту запроса `/top`,
  - ограничение глобальной параллельной отправки медиа.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN=<telegram_bot_token>
python -m bot.main
```

## Переменные окружения

- `BOT_TOKEN` — обязательно.
- `ASSETS_DIR` (default: `assets`)
- `DATABASE_PATH` (default: `database.db`)
- `CACHE_DIR` (default: `cache`)
- `CACHE_UPDATE_MINUTES` (default: `1`)
- `CACHE_CHAT_ID` (default: `0`, укажите chat_id канала/чата для прогрева `file_id`, чтобы inline отправлял именно фото, а не только текст)
- `TOP_ITEMS_PER_PAGE` (default: `140`)
- `INLINE_RESULTS_LIMIT` (default: `20`)

## Требования к ассетам

Положите изображения эмодзи в `assets/` (png/jpg/jpeg/webp/ppm). При запуске они синхронизируются в БД.

## Важно для inline-режима

1. В `@BotFather` должна быть включена команда `/setinline`.
2. После включения перезапустите бота.
3. Используйте в чате: `@username_бота` или `@username_бота <поиск>`.


## Определение эмодзи по фото

Отправьте скрин магазина боту как фото. Бот сравнит изображение с ассетами и пришлёт топ-3 совпадения с текущим рейтингом из базы.
