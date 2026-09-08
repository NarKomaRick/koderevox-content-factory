# Koderevox AI Content Factory

Self-hosted система, которая превращает Telegram в личный контент-инбокс и помогает собирать
технический контент без AI-slop.

Вы отправляете боту мысль, голосовое, ссылку, документ или видео. Система сохраняет оригинал,
извлекает смысл, предлагает идеи и сценарии, а из видео умеет собрать вертикальный Short с
монтажом, нормализованным звуком и субтитрами. Финальное решение всегда остаётся за человеком.

> Проект можно развернуть на собственном Debian/Linux-сервере. Исходные медиа хранятся у вас,
> а не в стороннем облачном хранилище.

## Содержание

- [Что уже работает](#что-уже-работает)
- [Как это выглядит для пользователя](#как-это-выглядит-для-пользователя)
- [Запуск за 10 минут](#запуск-за-10-минут)
- [Подключение AI](#подключение-ai)
- [Проверка после запуска](#проверка-после-запуска)
- [Telegram-сценарии](#telegram-сценарии)
- [Как устроен проект](#как-устроен-проект)
- [Настройки](#настройки)
- [Команды администратора](#команды-администратора)
- [Разработка и тесты](#разработка-и-тесты)
- [Частые проблемы](#частые-проблемы)
- [Ограничения](#ограничения)
- [Лицензия](#лицензия)

## Что уже работает

### Content Inbox

- Принимает обычный текст, URL, voice, audio, video, video note, изображения и документы.
- Сохраняет оригинальные файлы через абстракцию хранилища `LocalStorage`.
- Извлекает текст из `.txt`, `.md` и PDF с текстовым слоем.
- Безопасно загружает публичные HTTP/HTTPS-страницы и блокирует SSRF-доступ к локальной сети.
- Транскрибирует аудио и видео через `faster-whisper`.
- Хранит timestamps сегментов и отдельных слов для будущего монтажа и субтитров.
- Определяет тему, краткое содержание, ключевые мысли и потенциал материала.
- Помечает, когда для хорошего контента действительно не хватает контекста.
- Позволяет искать, фильтровать, архивировать и повторно использовать материалы.

### Генерация контента

- Создаёт три действительно разных content angle из одного источника.
- Генерирует сценарии для YouTube Shorts и TikTok живым языком.
- Создаёт отдельный Telegram-пост, а не копию транскрипции.
- Сохраняет версии идей и черновиков в PostgreSQL.
- Использует structured output и проверяет ответы LLM через Pydantic.
- Не смешивает факты из источника с предложениями AI.

### Полуавтоматический видеомонтаж

- Находит три возможные концепции Short в длинном видео.
- Выбирает фрагменты только из реальных диапазонов Whisper.
- Валидирует каждый `EditPlan` до запуска FFmpeg.
- Вырезает выбранные фрагменты и только явно длинные паузы.
- Собирает вертикальный MP4 `1080×1920`, H.264/AAC, `yuv420p`, faststart.
- Поддерживает `CENTER_CROP`, `FIT_BLUR`, `SCREEN_FIT` и ручной framing.
- Нормализует громкость и при необходимости уменьшает шум.
- Прожигает стилизованные ASS-субтитры.
- Имеет три спокойных preset: `CLEAN`, `DYNAMIC`, `TECH`.
- Отправляет preview в Telegram и позволяет одобрить или пересобрать ролик.
- Сохраняет один и тот же `EditPlan` при обычном rerender — монтаж не меняется случайно.

## Как это выглядит для пользователя

### Из голосовой мысли в сценарий

```text
Вы отправляете voice
        ↓
Бот сразу отвечает «Получил, обрабатываю»
        ↓
Worker: FFmpeg → Whisper → Content Intelligence
        ↓
Бот показывает тему, summary, score и подходящие форматы
        ↓
Вы нажимаете «Short»
        ↓
Получаете готовый сценарий
```

### Из длинного видео в вертикальный Short

```text
Вы отправляете видео
        ↓
Система сохраняет оригинал и транскрибирует речь
        ↓
AI предлагает три монтажные концепции
        ↓
Вы выбираете одну и проверяете план
        ↓
Render worker собирает ролик через FFmpeg
        ↓
Бот присылает MP4 preview
        ↓
Вы одобряете ролик или меняете монтаж / текст / стиль
```

Видео и аудио не отправляются в LLM. AI получает только транскрипцию, безопасные метаданные,
Content Intelligence и добавленный пользователем контекст.

## Запуск за 10 минут

Этот вариант подходит, даже если вы не Python-разработчик.

### 1. Что понадобится

- Linux-сервер или компьютер с Docker;
- Docker Engine и команда `docker compose`;
- Telegram-бот, созданный через официальный `@BotFather`;
- ваш числовой Telegram user ID;
- минимум несколько гигабайт свободного места для Docker images, Whisper-модели и медиа;
- AI endpoint: локальный LM Studio либо OpenAI-compatible API.

Для первого знакомства настоящий AI необязателен: проект по умолчанию использует
детерминированный `mock` provider.

### 2. Склонируйте проект

```bash
git clone https://github.com/NarKomaRick/koderevox-content-factory.git
cd koderevox-content-factory
```

### 3. Создайте конфигурацию

```bash
cp .env.example .env
```

Откройте `.env` любым текстовым редактором. Для первого запуска достаточно проверить эти поля:

```dotenv
TELEGRAM_BOT_TOKEN=сюда_токен_от_BotFather
TELEGRAM_ALLOWED_USER_IDS=сюда_ваш_числовой_telegram_id
AI_PROVIDER=mock
```

Если разрешённых пользователей несколько, перечислите ID через запятую:

```dotenv
TELEGRAM_ALLOWED_USER_IDS=123456789,987654321
```

Не добавляйте кавычки и пробелы вокруг `=`. Никогда не публикуйте заполненный `.env`.

### 4. Запустите систему

```bash
docker compose up -d --build
```

Первый запуск может занять заметное время: Docker скачивает образы и Python-зависимости.

### 5. Убедитесь, что контейнеры работают

```bash
docker compose ps
```

Нужно увидеть шесть сервисов:

| Сервис | Зачем он нужен |
|---|---|
| `postgres` | хранит пользователей, источники, идеи, черновики и проекты видео |
| `redis` | передаёт фоновые задания worker-ам |
| `api` | FastAPI backend и Swagger |
| `bot` | Telegram-интерфейс |
| `worker` | загрузка, извлечение текста, Whisper и Content Intelligence |
| `render-worker` | тяжёлый FFmpeg-рендер; по умолчанию только один одновременно |

Затем откройте:

- API: <http://localhost:8000>
- Проверка здоровья: <http://localhost:8000/health>
- Swagger: <http://localhost:8000/docs>

Отправьте боту `/start`. Неизвестный пользователь получит `Access denied`.

## Подключение AI

### Самый простой безопасный тест

Оставьте:

```dotenv
AI_PROVIDER=mock
```

Система запустится без внешнего API и позволит проверить интерфейс и инфраструктуру. Результаты
будут тестовыми, поэтому для реальной работы после проверки подключите модель.

### Локальная модель через LM Studio

1. Установите LM Studio на машине, доступной серверу.
2. Загрузите instruct-модель, способную надёжно возвращать JSON.
3. Откройте в LM Studio Local Server и запустите OpenAI-compatible endpoint.
4. Укажите в `.env`:

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=http://host.docker.internal:1234/v1
AI_API_KEY=lm-studio
AI_MODEL=точный_identifier_модели_из_LM_Studio
```

Для Linux имя `host.docker.internal` уже проброшено в нужные контейнеры через Docker Compose.
Если LM Studio находится на другом компьютере, укажите его публично доступный адрес вместо
`host.docker.internal` и настройте firewall самостоятельно.

### Облачный OpenAI-compatible endpoint

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://адрес-провайдера/v1
AI_API_KEY=ваш_секретный_ключ
AI_MODEL=имя_модели
```

Provider должен поддерживать `/chat/completions` и structured JSON output. При временной ошибке,
невалидном JSON или несовпадении схемы приложение выполнит ограниченное число повторов.

Архитектура не привязана к конкретной модели: новый provider можно добавить без изменения
`ContentService`, Telegram handlers или видеоредактора.

## Проверка после запуска

Выполняйте команды по порядку.

### API отвечает

```bash
curl http://localhost:8000/health
```

### Все контейнеры живы

```bash
docker compose ps
```

### Посмотреть последние логи

```bash
docker compose logs --tail=100 api bot worker render-worker
```

### Проверить Telegram

1. Отправьте `/start`.
2. Нажмите `➕ Новая идея`.
3. Напишите короткую техническую мысль.
4. Убедитесь, что появились три варианта.

### Проверить Inbox

1. Выйдите из активного сценария кнопкой отмены, если он открыт.
2. Просто отправьте текст или voice без предварительного выбора команды.
3. Бот должен сразу подтвердить приём.
4. После фоновой обработки материал появится в `/inbox`.

Whisper-модель скачивается при первом реальном распознавании. Это может занять время и требует
доступа в интернет, если модель ещё не находится в cache контейнера.

## Telegram-сценарии

### Новая идея — быстрый путь

1. `/start` → `➕ Новая идея`.
2. Отправьте текст.
3. Выберите один из трёх разных углов подачи.
4. Получите `ContentIdea` и сценарий `ContentDraft`.
5. Одобрите, перегенерируйте, адаптируйте или удалите черновик.

Адаптация создаёт отдельные материалы для YouTube Shorts, TikTok и Telegram.

### Inbox — отправляйте всё подряд

Любой материал вне активного FSM-сценария автоматически становится `SourceItem`:

- текст и URL;
- voice и обычное audio;
- video и video note;
- изображение;
- `.txt`, `.md` или PDF.

Доступные команды:

- `/inbox` — материалы с фильтрами и пагинацией;
- `/search запрос` — простой поиск по теме, summary, transcript и исходному тексту;
- `/digest` — ручная сводка лучших материалов за сегодня.

PDF без текстового слоя сохраняется, но OCR автоматически не запускается. Изображение без vision
provider также сохраняется и предлагает добавить текстовый комментарий.

### Монтаж Short из видео

1. Откройте обработанное видео в Inbox.
2. Нажмите `🎬 Short`.
3. Выберите одну из трёх концепций.
4. Проверьте длительность и число фрагментов.
5. Нажмите `▶️ Собрать`.
6. После получения preview выберите:
   - `✅ Одобрить`;
   - `✂️ Монтаж` и напишите инструкцию вроде «оставь только техническую часть»;
   - `📝 Текст` для прозрачной правки терминов;
   - `🎨 Стиль` для `CLEAN`, `DYNAMIC` или `TECH`;
   - `🔄 Пересобрать` без повторного AI-анализа.

Если нужный момент уже известен, ручной режим принимает диапазон вида `00:45 - 01:23` и создаёт
проект без AI-выбора клипов.

## Как устроен проект

```text
Telegram Bot ──HTTP── FastAPI ── PostgreSQL
                         │
                         ├── Redis → media queue
                         │             └── download / FFmpeg / Whisper / AI enrichment
                         │
                         └── Redis → render queue (concurrency 1)
                                       └── EditPlan → FFmpeg → MP4 → Telegram preview
```

Telegram handler выполняет только быструю регистрацию материала и постановку задания. Тяжёлая
работа идёт в Celery worker-ах, поэтому бот не зависает на время транскрипции или рендера.

### Основные сущности

| Сущность | Что хранит |
|---|---|
| `User` | Telegram-пользователя и роль |
| `Project` | brand context, аудиторию, язык и vocabulary |
| `SourceItem` | входной материал, статус обработки, transcript и Content Intelligence |
| `SourceNote` | дополнительный контекст пользователя, связанный с источником |
| `ContentIdea` | выбранный угол подачи |
| `ContentDraft` | версии сценариев и адаптаций под платформы |
| `VideoProject` | состояние монтажа, настройки, EditPlan, preview и итоговый файл |

### Стадии обработки источника

```text
RECEIVED
   ↓
DOWNLOADED
   ↓
MEDIA_PREPARED
   ↓
TRANSCRIBED / EXTRACTED
   ↓
ENRICHED
   ↓
READY
```

При ошибке сохраняются `FAILED`, безопасное описание причины и стадия, на которой она произошла.
Временные ошибки повторяются ограниченно; повторная доставка Telegram update или Celery task не
создаёт дубликат.

### Безопасный EditPlan

LLM никогда не генерирует shell-команду или FFmpeg-команду. Он возвращает только данные:

```json
{
  "clips": [
    {
      "source_start": 12.4,
      "source_end": 19.8,
      "source_segment_ids": [4, 5],
      "purpose": "hook"
    },
    {
      "source_start": 26.1,
      "source_end": 42.0,
      "source_segment_ids": [8, 9],
      "purpose": "main"
    }
  ],
  "hook_text": "ДВА ОДИНАКОВЫХ ЗАПРОСА",
  "emphasis": [
    {"start": 2.1, "end": 4.2, "text": "два запроса"}
  ],
  "recommended_duration": 23.3,
  "reasoning_summary": "История проблемы и технический вывод",
  "framing": "center_crop",
  "pace": "medium"
}
```

Backend проверяет, что интервалы существуют, пересекаются с указанными STT segments, помещаются
в исходное видео и не содержат бессмысленно коротких клипов. Текстовые акценты должны реально
существовать в речи или субтитрах.

### Структура репозитория

```text
app/
├── ai/                 # provider abstraction и structured prompts
├── api/routes/         # REST endpoints FastAPI
├── bot/                # aiogram handlers, FSM, keyboards и whitelist
├── core/               # настройки и structured logging
├── db/migrations/      # Alembic migrations и начальный проект Koderevox
├── models/             # SQLAlchemy entities и enums состояний
├── schemas/            # Pydantic-контракты API, LLM и EditPlan
├── services/           # бизнес-логика Inbox, STT, контента и видео
├── storage/            # LocalStorage и будущая точка расширения под S3
└── tasks/              # Celery tasks и routing по очередям
tests/                  # unit, integration и реальный FFmpeg smoke test
```

## Настройки

Все настройки читаются из `.env`. Полный и актуальный список находится в `.env.example`.

### Обязательные для Telegram

| Переменная | Пример | Значение |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `123:abc...` | секрет от BotFather |
| `TELEGRAM_ALLOWED_USER_IDS` | `123456789` | кому разрешено пользоваться ботом |

### AI

| Переменная | Значение |
|---|---|
| `AI_PROVIDER` | `mock` или `openai_compatible` |
| `AI_BASE_URL` | адрес API вместе с `/v1` |
| `AI_API_KEY` | секретный ключ; для LM Studio — любое непустое значение |
| `AI_MODEL` | точный identifier модели |
| `AI_TIMEOUT_SECONDS` | timeout одного запроса |
| `AI_MAX_RETRIES` | число повторов при временной/структурной ошибке |

### Whisper и медиа

| Переменная | По умолчанию | Значение |
|---|---:|---|
| `STT_MODEL` | `small` | модель faster-whisper |
| `STT_DEVICE` | `cpu` | `cpu` или `cuda` |
| `STT_COMPUTE_TYPE` | `int8` | тип вычислений, например `int8` или `float16` |
| `MEDIA_ROOT` | `/data/media` | корень хранилища внутри контейнеров |
| `MAX_MEDIA_SIZE_MB` | `200` | максимальный размер входящего Telegram-файла |
| `DOCUMENT_MAX_CHARS` | `100000` | предел текста, извлекаемого из документа |

### Ссылки

| Переменная | По умолчанию | Значение |
|---|---:|---|
| `LINK_FETCH_TIMEOUT_SECONDS` | `15` | timeout HTTP-запроса |
| `LINK_MAX_SIZE_MB` | `10` | максимальный размер ответа |
| `LINK_MAX_REDIRECTS` | `5` | максимум проверяемых redirect |

`LinkProcessor` разрешает только HTTP/HTTPS, отключает environment proxy и проверяет DNS на каждом
redirect. Блокируются localhost, private, loopback, link-local, multicast, reserved, metadata и
прочие non-public IPv4/IPv6 адреса.

### Рендер

| Переменная | По умолчанию | Значение |
|---|---:|---|
| `VIDEO_WIDTH` / `VIDEO_HEIGHT` | `1080` / `1920` | размер вертикального canvas |
| `VIDEO_FPS` | `30` | частота кадров |
| `VIDEO_CRF` | `20` | качество H.264; меньше — качественнее и больше файл |
| `VIDEO_PRESET` | `medium` | компромисс скорости и сжатия x264 |
| `VIDEO_MIN_DURATION` | `5` | минимальная длина Short |
| `VIDEO_MAX_DURATION` | `75` | максимальная длина Short |
| `CELERY_RENDER_CONCURRENCY` | `1` | сколько тяжёлых рендеров выполнять одновременно |
| `TELEGRAM_PREVIEW_MAX_SIZE_MB` | `48` | когда создавать сжатый preview |
| `HOOK_OVERLAY_ENABLED` | `true` | показывать короткий hook overlay |

На домашнем сервере оставьте `CELERY_RENDER_CONCURRENCY=1`, пока не измерите нагрузку CPU и RAM.

### Паузы и звук

| Переменная | По умолчанию | Значение |
|---|---:|---|
| `PAUSE_REMOVAL_ENABLED` | `true` | удалять длинную тишину |
| `PAUSE_MIN_DURATION` | `0.65` | минимальная удаляемая пауза в секундах |
| `PAUSE_KEEP_PADDING` | `0.12` | сколько оставить вокруг склейки |
| `PAUSE_NOISE_DB` | `-35` | порог FFmpeg silencedetect |
| `AUDIO_NORMALIZATION_ENABLED` | `true` | loudness normalization и limiter |
| `AUDIO_NOISE_REDUCTION_ENABLED` | `false` | дополнительный FFmpeg noise reduction |

Настройки намеренно консервативны: редактор не должен превращать естественную речь в нервную
TikTok-нарезку.

## Команды администратора

### Запуск и остановка

```bash
docker compose up -d --build
docker compose stop
docker compose start
docker compose down
```

`docker compose down` удаляет контейнеры и сеть, но не named volumes. Не добавляйте `-v`, если не
хотите удалить базу, Redis data и сохранённые медиа.

### Логи

```bash
docker compose logs -f bot
docker compose logs -f worker
docker compose logs -f render-worker
docker compose logs --tail=200 api
```

### Обновление кода

Перед обновлением сделайте резервную копию важных данных. Затем:

```bash
git pull --ff-only
docker compose up -d --build
```

API автоматически применяет новые Alembic migrations перед стартом.

### Миграции вручную

```bash
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

### Где лежат данные

Docker Compose использует named volumes:

- `postgres_data` — PostgreSQL;
- `redis_data` — очередь и результаты задач;
- `media_data` — оригиналы, обработанные файлы и готовые ролики.

Оригинальные медиа не удаляются автоматически. Временные WAV, клипы, ASS и concat-файлы хранятся
в отдельном workspace проекта и очищаются через `try/finally` после успеха или ошибки.

## REST API

Интерактивная документация всегда доступна на `/docs`. Основные группы endpoints:

```text
/projects                 проекты и brand context
/sources                  входящие материалы и генерация контента
/inbox                    список, фильтры, поиск и digest
/ideas                    content angles
/drafts                   сценарии и адаптации
/video-projects           EditPlan, render, style, approve и archive
```

Backend самодостаточен: Telegram является интерфейсом, а не местом бизнес-логики. В будущем n8n,
web-панель или другой клиент смогут вызывать то же REST API.

## Разработка и тесты

Нужен Python 3.12+ и системный FFmpeg.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app
```

Тесты покрывают ContentService, structured LLM output, permissions, ingestion, idempotency,
обработку media/document/link, SSRF, Content Intelligence, Inbox, EditPlan, pause detection,
субтитры, renderer, API и Telegram workflow. Отдельный smoke test создаёт настоящее видео через
FFmpeg, собирает вертикальный MP4 и проверяет его через ffprobe.

### Очереди Celery

- `default,media` обслуживает обычный `worker`;
- `render` обслуживает отдельный `render-worker`;
- ingestion и render tasks идемпотентны;
- число повторов ограничено;
- тяжёлый encode не блокирует короткие задачи.

### Шрифты и vocabulary

Docker image содержит свободный DejaVu Sans. Для своего лицензированного шрифта смонтируйте файл
read-only и задайте:

```dotenv
VIDEO_FONT_PATH=/data/fonts/MyFont.ttf
```

Коммерческие шрифты не входят в репозиторий.

Project vocabulary используется при транскрипции и подготовке субтитров. Исправления вроде
`Rest → REST` или `Реакт нейтив → React Native` сохраняются отдельно от оригинальной
транскрипции и не меняют timestamps.

## Частые проблемы

### Бот молчит

Проверьте:

```bash
docker compose ps
docker compose logs --tail=200 bot api
```

Обычно причина — неправильный `TELEGRAM_BOT_TOKEN`, отсутствующий user ID в whitelist или
недоступный API.

### Бот отвечает `Access denied`

Добавьте свой числовой ID в `TELEGRAM_ALLOWED_USER_IDS` и перезапустите bot:

```bash
docker compose up -d --force-recreate bot
```

### Материал остаётся в PROCESSING

Проверьте Redis и media worker:

```bash
docker compose ps redis worker
docker compose logs --tail=200 worker redis
```

### LM Studio не отвечает

- Убедитесь, что Local Server действительно запущен.
- Проверьте точное имя модели.
- Разрешите подключения не только с `localhost`, если LM Studio работает вне Docker.
- Проверьте `AI_BASE_URL` из контейнера API.

### Whisper долго запускается

Первый запуск скачивает модель. На слабом CPU используйте:

```dotenv
STT_MODEL=small
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
```

Для `cuda` нужны совместимые NVIDIA drivers, NVIDIA Container Toolkit, CUDA-библиотеки и GPU
mapping в Docker Compose. Одного значения `STT_DEVICE=cuda` недостаточно.

### Рендер слишком тяжёлый

- Оставьте `CELERY_RENDER_CONCURRENCY=1`.
- Увеличьте `VIDEO_CRF` до `22–24`, если допустимо чуть меньшее качество.
- Используйте более быстрый `VIDEO_PRESET`, понимая компромисс размера и качества.
- Посмотрите `render_duration`, `output_size` и другие metrics в `VideoProject`.

### Видео технически готово, но выглядит плохо

Попробуйте другой framing:

- `CENTER_CROP` — talking head по центру;
- `FIT_BLUR` — весь горизонтальный кадр на размытой подложке;
- `SCREEN_FIT` — сохранить интерфейс или код записи экрана.

Затем выберите другой subtitle preset и пересоберите тот же EditPlan.

## Ограничения

Сейчас намеренно не реализованы:

- публикация в YouTube, TikTok и Telegram-каналы;
- scheduler и social analytics;
- web dashboard и полноценный timeline editor;
- face tracking и multi-camera монтаж;
- AI/stock B-roll, музыка, thumbnails и сложная motion graphics;
- OCR сканированных PDF;
- vector database и semantic search;
- S3/MinIO backend.

`CANCEL_REQUESTED` предусмотрен в модели, но текущий MVP гарантированно проверяет отмену между
этапами, а не посылает сигнал уже работающему FFmpeg в середине encode.

Архитектура уже сохраняет исходное видео, извлечённое аудио, timestamps слов, ContentDraft,
validated EditPlan, overrides, framing, render settings, debug frames и approved MP4. Это база для
следующего этапа: B-roll, скриншоты, screen recordings, изображения и brand templates.

## Безопасность и приватность

- Секреты читаются из `.env`, который исключён из Git.
- Telegram доступен только user ID из whitelist.
- API keys не выводятся в structured logs.
- Media blobs не хранятся в PostgreSQL.
- Video/audio bytes не передаются в LLM.
- URL проходят DNS- и redirect-проверки против SSRF.
- Пользовательские имена файлов не используются как доверенные storage paths.

Если вы публикуете сервер в интернете, дополнительно настройте firewall, TLS reverse proxy,
резервное копирование PostgreSQL/media и ограничение доступа к Swagger/API.

## Лицензия

Copyright © 2026 NarKomaRick. All Rights Reserved.

Репозиторий публичный для просмотра исходного кода, но не является open-source проектом. Права на
копирование, изменение, распространение, перепродажу, размещение производного сервиса и иное
использование без отдельного письменного разрешения не предоставляются. Полные условия находятся
в файле [LICENSE](LICENSE).

По вопросам разрешения на использование обращайтесь к владельцу репозитория через GitHub.
