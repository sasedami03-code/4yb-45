# Clash Royale Emoji Rating Bot

Бот собирает живой рейтинг эмодзи через голосования в чате и показывает ТОП с кэшируемыми превью-страницами.

## Что реализовано

- `/vote` — отправка случайного эмодзи из `assets/` с кнопками оценки 1..10.
- Хранение голосов в SQLite (`database.db`):
  - `total_score`, `votes_count`, `average_rating`.
- `/top [страница]` — выдача превью рейтинга с пагинацией и обновляемым кэшем.
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
- `CACHE_CHAT_ID` (default: `0`, если указать — превью будут предварительно грузиться в этот чат и переиспользовать `file_id`)
- `TOP_ITEMS_PER_PAGE` (default: `140`)

## Требования к ассетам

Положите изображения эмодзи в `assets/` (png/jpg/jpeg/webp/ppm). При запуске они синхронизируются в БД.
