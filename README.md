# Koderevox AI Content Factory

Self-hosted Content Inbox и AI-фабрика контента для Telegram. Phase 3 превращает сохранённое видео
и timestamped transcript в управляемый человеком вертикальный Short: предлагает три концепции,
создаёт проверяемый `EditPlan`, вырезает выбранные фрагменты и длинные паузы, делает framing,
нормализует звук, прожигает ASS-субтитры и возвращает MP4 preview. Phase 1/2 workflows сохранены.

Система рассчитана на несколько пользователей и проектов, хотя первый deployment может быть
однопользовательским. Проект `Koderevox` с brand context создаётся начальной миграцией.

## Архитектура

```text
Telegram Bot ──HTTP── FastAPI ── PostgreSQL
                         │
                         ├── Redis → media queue → SourceProcessingService
                         │                         ├── FFmpeg / faster-whisper
                         │                         └── Content Intelligence
                         └── Redis → render queue (concurrency 1)
                                                  └── VideoRenderService
                                                       ├── validated EditPlan
                                                       ├── pause/subtitle/framing/audio
                                                       ├── FFmpegVideoEditor
                                                       └── LocalStorage → Telegram preview
```

Telegram handler только регистрирует metadata, ставит job и сразу отвечает. Идемпотентный
`SourceProcessingService` выполняет стадии `RECEIVED → DOWNLOADED → MEDIA_PREPARED → TRANSCRIBED /
EXTRACTED → ENRICHED → READY`. Ошибка сохраняется вместе с точной стадией; temporary failures
повторяются Celery не более трёх раз. Timestamped STT segments и words используются Phase 3.

LLM никогда не получает video/audio bytes и не строит FFmpeg-команды. Он видит transcript,
Content Intelligence, metadata и пользовательский контекст, а возвращает только structured
concepts/EditPlan. Backend валидирует duration, segment IDs, диапазоны и emphasis-текст. Обычный
rerender использует сохранённый план и не вызывает AI повторно.

## Структура

```text
app/
├── ai/                 # provider abstraction, adapters, structured prompts
├── api/routes/         # FastAPI endpoints
├── bot/                # aiogram handlers, FSM, keyboards, whitelist
├── core/               # settings and structured logging
├── db/migrations/      # Alembic and Koderevox seed
├── models/             # SQLAlchemy entities and state enums
├── schemas/            # API and LLM Pydantic contracts
├── services/           # inbox/STT, clip selector, subtitles, framing and video rendering
├── storage/            # LocalStorage abstraction
└── tasks/              # Celery application
tests/                  # service, workflow, provider and permission tests
```

## Быстрый запуск

Требования: Docker Engine с Compose v2 и Telegram bot token от BotFather.

```bash
cp .env.example .env
# заполнить TELEGRAM_BOT_TOKEN и TELEGRAM_ALLOWED_USER_IDS
docker compose up -d --build
docker compose ps
```

После запуска:

- API: <http://localhost:8000>
- Swagger: <http://localhost:8000/docs>
- Healthcheck: <http://localhost:8000/health>

API-контейнер применяет миграции перед запуском. Бот начинает long polling после успешного
healthcheck API.

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | Async SQLAlchemy URL PostgreSQL |
| `REDIS_URL` | Celery broker/result backend |
| `CELERY_TASK_ALWAYS_EAGER` | Только для local/test запуска без Redis |
| `TELEGRAM_BOT_TOKEN` | Секрет Telegram-бота; не коммитить |
| `TELEGRAM_ALLOWED_USER_IDS` | Telegram ID через запятую; остальные получают `Access denied` |
| `BACKEND_URL` | URL API, доступный bot-контейнеру |
| `AI_PROVIDER` | `openai_compatible` или `mock` |
| `AI_BASE_URL` | Base URL с `/v1` |
| `AI_API_KEY` | API key; для LM Studio может быть произвольным непустым значением |
| `AI_MODEL` | Имя модели, передаваемое provider endpoint |
| `AI_TIMEOUT_SECONDS` | Timeout одного LLM-запроса |
| `AI_MAX_RETRIES` | Повторы при HTTP/JSON/schema ошибке |
| `MEDIA_ROOT` | Корень LocalStorage внутри контейнера |
| `MAX_MEDIA_SIZE_MB` | Максимальный Telegram media file |
| `STT_MODEL` | faster-whisper model |
| `STT_DEVICE` | `cpu` или `cuda` |
| `STT_COMPUTE_TYPE` | Например `int8`, `float16` |
| `LINK_FETCH_TIMEOUT_SECONDS` | Timeout HTTP page fetch |
| `LINK_MAX_SIZE_MB` | Максимальный HTML response |
| `LINK_MAX_REDIRECTS` | Максимум проверяемых redirects |
| `DOCUMENT_MAX_CHARS` | Лимит извлечённого текста документа |
| `VIDEO_WIDTH`, `VIDEO_HEIGHT`, `VIDEO_FPS` | Target canvas/fps; default 1080×1920/30 |
| `VIDEO_CRF`, `VIDEO_PRESET` | Качество и x264 preset финального encode |
| `VIDEO_MIN_DURATION`, `VIDEO_MAX_DURATION` | Quality limits валидатора EditPlan |
| `PAUSE_REMOVAL_ENABLED` | Включить консервативное удаление длинной тишины |
| `PAUSE_MIN_DURATION`, `PAUSE_KEEP_PADDING` | Порог тишины и сохраняемый padding |
| `PAUSE_NOISE_DB` | Порог FFmpeg `silencedetect` |
| `AUDIO_NORMALIZATION_ENABLED` | `loudnorm` и limiter для online-video |
| `AUDIO_NOISE_REDUCTION_ENABLED` | Опциональный `afftdn` |
| `HOOK_OVERLAY_ENABLED` | Короткий overlay в первые три секунды |
| `VIDEO_FONT_PATH` | Явный open-source font для overlays |
| `RENDER_TEMP_ROOT` | Временные workspace отдельных VideoProject |
| `TELEGRAM_PREVIEW_MAX_SIZE_MB` | Порог перед сжатием Telegram preview |
| `CELERY_RENDER_CONCURRENCY` | Параллелизм тяжёлой render queue; default `1` |

Для первого безопасного smoke test оставьте `AI_PROVIDER=mock`. Он выдаёт детерминированные
ответы и позволяет проверить весь workflow без передачи данных наружу.

## LM Studio

1. Загрузите модель и запустите Local Server в LM Studio.
2. Разрешите подключения с Docker host при необходимости.
3. В `.env` задайте:

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=http://host.docker.internal:1234/v1
AI_API_KEY=lm-studio
AI_MODEL=<точный identifier загруженной модели>
```

Для Linux alias `host.docker.internal` уже добавлен в API и worker через:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Endpoint должен поддерживать `/chat/completions` и structured output `json_schema`. Если выбранная
модель плохо соблюдает schema, приложение повторит запрос, а затем вернёт явную ошибку.

## Telegram workflow Phase 1

1. `/start` показывает главное меню.
2. Нажмите `➕ Новая идея` и отправьте текст.
3. Бот сохраняет `SourceItem` и показывает три разных подхода.
4. Выберите `1`, `2` или `3`.
5. Бот создаёт `ContentIdea`/`ContentDraft` и показывает hook, сценарий, сцены, экранные
   рекомендации, caption, CTA и длительность.
6. Доступны `Одобрить`, `Перегенерировать`, `Адаптировать`, `Удалить`.

Перегенерация сохраняет предыдущую версию. Адаптация создаёт отдельные drafts для YouTube Shorts,
TikTok и Telegram.

## Telegram workflow Phase 2

- Любой text/voice/audio/video/video note/photo/document вне активного FSM автоматически попадает
  в Inbox. URL внутри текста определяется отдельно.
- Bot немедленно подтверждает регистрацию, а download, FFmpeg, STT, document/link extraction и AI
  enrichment выполняются worker-ом.
- После READY бот показывает тему, summary, score и рекомендуемые форматы. При недостатке контекста
  задаётся не более трёх вопросов; ответ можно связать с item текстом или voice.
- `📥 Контент-инбокс` и `/inbox` показывают фильтры, страницы и карточки. Detail позволяет сделать
  Short/идеи/TG-пост, дополнить, архивировать или удалить материал.
- `/search запрос` ищет через PostgreSQL `ILIKE` по topic, summary, transcript, extracted/original text.
- `/digest` формирует ручную сводку за текущий день.

## Telegram workflow Phase 3

1. Отправьте video/video note и дождитесь Phase 2 transcript и Content Intelligence.
2. В карточке источника нажмите `🎬 Short`: LLM предложит три разные монтажные концепции.
3. Выберите вариант. Backend создаст EditPlan только из реальных STT ranges и покажет количество
   клипов, длительность, hook, framing и pace.
4. Нажмите `▶️ Собрать`. Render worker в отдельной очереди создаст H.264/AAC MP4 и отправит preview.
5. После preview доступны approve, изменение монтажа текстовой инструкцией, прозрачная замена
   терминов, CLEAN/DYNAMIC/TECH, детерминированная пересборка и архив.
6. `✂️ Выбрать фрагмент` принимает диапазон `00:45 - 01:23` и создаёт EditPlan без AI.

Пример сокращённого плана:

```json
{
  "clips": [
    {"source_start": 12.4, "source_end": 19.8, "source_segment_ids": [4, 5], "purpose": "hook"},
    {"source_start": 26.1, "source_end": 42.0, "source_segment_ids": [8, 9], "purpose": "main"}
  ],
  "hook_text": "ДВА ОДИНАКОВЫХ ЗАПРОСА",
  "emphasis": [{"start": 2.1, "end": 4.2, "text": "два запроса"}],
  "recommended_duration": 23.3,
  "reasoning_summary": "История проблемы и технический вывод",
  "framing": "center_crop",
  "pace": "medium"
}
```

`source_segment_ids` обязательны. `CENTER_CROP`, `FIT_BLUR`, `SCREEN_FIT` реализованы через
`StaticFramingProvider`; `MANUAL` хранит нормализованные x/y/zoom. Face tracking остаётся будущей
реализацией `FramingProvider`.

Оригиналы сохраняются в `YYYY/MM/UUID/original`; нормализованный WAV — в `processed`. Временные
FFmpeg-файлы удаляются и при успехе, и при exception. Изображение без vision provider сохраняется
с dimensions и предлагает добавить комментарий. PDF без text layer фиксируется без запуска OCR.

## REST API

Основные endpoints:

```text
GET  /health
GET/POST /projects
GET/POST /sources
GET  /sources/{id}
POST /sources/{id}/generate-ideas
POST /sources/telegram-ingestion
POST /sources/{id}/enqueue
POST /sources/{id}/retry
POST /sources/{id}/notes
POST /sources/{id}/archive
POST /sources/{id}/generate-short
POST /sources/{id}/generate-telegram-post
POST /sources/{id}/video-projects
POST /sources/{id}/video-projects/manual
GET  /video-projects
GET  /video-projects/{id}
POST /video-projects/{id}/generate-edit-plan
POST /video-projects/{id}/regenerate-concepts
PATCH /video-projects/{id}/edit-plan
POST /video-projects/{id}/render
POST /video-projects/{id}/rerender
POST /video-projects/{id}/style
PATCH /video-projects/{id}/transcript-overrides
POST /video-projects/{id}/approve
POST /video-projects/{id}/archive
POST /video-projects/{id}/cancel
GET  /inbox
GET  /inbox/digest
GET  /ideas
GET  /ideas/{id}
POST /ideas/{id}/generate-draft
GET  /drafts
GET  /drafts/{id}
PATCH /drafts/{id}/status
POST /drafts/{id}/regenerate
POST /drafts/{id}/repurpose
DELETE /drafts/{id}
```

Интерактивные контракты доступны в Swagger/OpenAPI.

## Миграции

```bash
docker compose exec api alembic current
docker compose exec api alembic upgrade head
docker compose exec api alembic revision --autogenerate -m "describe change"
```

## Локальная разработка

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app
```

Media worker слушает `default,media`; отдельный `render-worker` слушает только `render`. Для
домашнего CPU оставьте `CELERY_RENDER_CONCURRENCY=1`. Увеличивайте значение только после измерения
RAM/CPU и `render_duration` в `VideoProject.metrics`.

## Субтитры, vocabulary и шрифты

faster-whisper запускается с `word_timestamps=True`; words хранятся внутри существующего JSONB
segments. Для старого item с segment timestamps SubtitleService безопасно распределяет слова
внутри segment. Оригинальный transcript не меняется: исправления (`REST`, `SQL`, названия проектов)
сохраняются в `VideoProject.transcript_overrides`, не затрагивая время.

Образ содержит свободный DejaVu Sans (`fonts-dejavu-core`). Чтобы использовать собственный
лицензированный шрифт, смонтируйте каталог read-only в `render-worker`, например `/data/fonts`, и
задайте `VIDEO_FONT_PATH=/data/fonts/MyFont.ttf`. Коммерческие шрифты в репозиторий не добавляются.

`STT_DEVICE=cuda` и подходящий `STT_COMPUTE_TYPE` поддерживаются adapter-ом, но Docker host должен
иметь NVIDIA Container Toolkit, совместимые CUDA-библиотеки и явный GPU mapping в Compose.

## Безопасность URL

`LinkProcessor` разрешает только HTTP/HTTPS, отключает environment proxies и автоматические
redirects, проверяет DNS перед каждым запросом и каждый redirect. Блокируются localhost, private,
loopback, link-local, multicast, reserved и прочие non-public IPv4/IPv6 адреса, включая metadata
endpoints. HTML ограничен по размеру и очищается от script/style/nav/footer boilerplate.

## Границы Phase 3

Face tracking, web timeline, multi-camera, музыка, AI/stock B-roll, motion graphics, thumbnails,
publishing и scheduler не реализованы. Cancel state и API предусмотрены, но запущенный FFmpeg MVP
останавливается только между стадиями, а не сигналом посреди encode. `OverlayAsset` уже описывает
будущие image/video/screen/code/screenshot inserts; renderer abstraction допускает будущий Remotion,
но Node.js stack не добавлен: текущие layout/subtitle задачи надёжно решаются FFmpeg и ASS.

Для Phase 4 сохранены original video, extracted audio, segment/word timestamps, ContentDraft,
validated EditPlan, transcript overrides, framing/style/settings, debug frames и approved MP4.
