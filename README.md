# Koderevox AI Content Factory

Self-hosted фабрика контента, которая превращает Telegram в рабочий конвейер для видео и публикаций. Система принимает исходные материалы, расшифровывает их, помогает подготовить сценарий и монтажный план, собирает вертикальный ролик через FFmpeg и отправляет preview на согласование.

Проект рассчитан на собственный Debian/Linux-сервер. Медиафайлы хранятся локально, а финальное решение о монтаже и публикации остаётся за человеком.

## Возможности

- Telegram-инбокс для текста, ссылок, голосовых сообщений, аудио, видео, изображений и документов.
- Транскрибация аудио и видео через `faster-whisper` с timestamps сегментов и слов.
- Извлечение текста из TXT, Markdown и PDF.
- AI-анализ материала: тема, summary, ключевые мысли, content angles и сценарии.
- Автоматический монтаж Shorts/TikTok из длинного видео: выбор реальных фрагментов по транскрипции, удаление длинных пауз, экспорт 1080×1920 H.264/AAC, нормализация звука, ASS-субтитры и framing `CENTER_CROP`, `FIT_BLUR`, `SCREEN_FIT`.
- Визуальные ассеты, OCR, thumbnails и voiceover-driven assembly.
- Preview в Telegram, approve/rebuild и публикация в Telegram, YouTube и TikTok.
- Планировщик публикаций, retries, статусы и защита от двойной отправки.
- OpenAI-compatible endpoint и `mock` provider для локальной разработки.

## Архитектура

Docker Compose запускает восемь сервисов:

| Сервис | Назначение |
|---|---|
| `postgres` | данные пользователей, источников, проектов, публикаций и задач |
| `redis` | брокер Celery и очередь фоновых заданий |
| `api` | FastAPI backend, миграции Alembic, `/health` и Swagger |
| `bot` | Telegram-интерфейс |
| `worker` | импорт, извлечение текста, Whisper и AI-анализ |
| `render-worker` | ресурсоёмкий FFmpeg-рендер |
| `publish-worker` | загрузка и статусы публикаций |
| `publish-scheduler` | поиск запланированных публикаций |

Основной код: `app/bot/`, `app/api/`, `app/services/`, `app/tasks/`, `app/models/` и `alembic/`.

## Требования

- Linux-сервер с Docker Engine и Docker Compose plugin;
- Python 3.12+ для локальной разработки;
- Telegram-бот и числовой Telegram user ID;
- место для Docker-образов, Whisper-модели и медиа;
- AI endpoint для реальных результатов. Для первого запуска можно использовать `mock`.

## Быстрый запуск

```bash
git clone https://github.com/NarKomaRick/koderevox-content-factory.git
cd koderevox-content-factory
cp .env.example .env
```

Минимально заполните `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=токен_от_BotFather
TELEGRAM_ALLOWED_USER_IDS=ваш_telegram_id
INITIAL_OWNER_TELEGRAM_ID=ваш_telegram_id
APP_MASTER_KEY=сгенерированный_ключ
AI_PROVIDER=mock
```

Ключ шифрования:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Запуск:

```bash
docker compose up -d --build
docker compose ps
```

После запуска: API — `http://localhost:8000`, healthcheck — `http://localhost:8000/health`, Swagger — `http://localhost:8000/docs`. Откройте бота и отправьте `/start`.

## Настройка AI

Для теста:

```dotenv
AI_PROVIDER=mock
```

Для LM Studio, vLLM или другого совместимого сервера:

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=http://host.docker.internal:1234/v1
AI_API_KEY=lm-studio
AI_MODEL=local-model
```

AI получает транскрипцию и метаданные, а не исходные видео- и аудиофайлы.

## Основные настройки видео

```dotenv
VIDEO_WIDTH=1080
VIDEO_HEIGHT=1920
VIDEO_FPS=30
VIDEO_CRF=20
VIDEO_MAX_DURATION=75
STT_PROVIDER=faster_whisper
STT_MODEL=small
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
PAUSE_REMOVAL_ENABLED=true
AUDIO_NORMALIZATION_ENABLED=true
```

Для CPU-сервера начните с модели Whisper `small`. Более крупные модели требуют больше RAM и времени.

## Локальная разработка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
mypy app
```

Полный интеграционный pipeline требует FFmpeg, PostgreSQL, Redis и настроенного окружения.

## Безопасность

- Не коммитьте `.env`, токены, ключи и OAuth-секреты.
- Ограничивайте доступ через `TELEGRAM_ALLOWED_USER_IDS`.
- Для production используйте HTTPS перед API и отдельные секреты для публикаций.
- Входящие HTTP-ссылки проходят SSRF-защиту и ограничения размера.
- Credential secrets для публикаций шифруются перед сохранением.
- Исходные медиа и рабочие volume находятся на вашем сервере.

## Тесты

В репозитории есть unit- и integration-тесты для Telegram ingestion, AI/STT providers, edit plans, FFmpeg rendering, subtitles, preview delivery, публикаций, scheduler и security checks.

## Лицензия

См. файл [LICENSE](LICENSE).
