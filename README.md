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


## Video capability smoke test

The repository includes a deterministic end-to-end capability check. It creates a Russian
technical script, synthesizes a local WAV with espeak-ng, runs faster-whisper and alignment,
creates synthetic visual assets, performs voiceover-driven assembly, renders two previews and a
1080x1920 final MP4, and prints a JSON summary.

    python scripts/full_video_capability_test.py

The command requires the project dependencies, ffmpeg, ffprobe, espeak-ng, and a Whisper
model available to faster-whisper. Runtime artifacts are created in a temporary directory and
are not written to Git.

## Windows 11 + WSL2 + NVIDIA RTX

This deployment is intended for Docker Desktop in **Linux containers / WSL2 mode**. Do not
switch Docker Desktop to Windows Containers. The checkout stays separate from all runtime data:

| Location | Purpose |
|---|---|
| `D:\\Code\\For SSH\\koderevox-content-factory` | Git checkout only |
| `D:\\Code\\For SSH\\koderevox-content-factory-data\\postgres\\data` | PostgreSQL data |
| `D:\\Code\\For SSH\\koderevox-content-factory-data\\postgres\\backups` | portable pg_dump backups |
| `D:\\Code\\For SSH\\koderevox-content-factory-data\\redis` | Redis AOF data |
| `D:\\Code\\For SSH\\koderevox-content-factory-data\\media` | incoming and processed media |
| `D:\\Code\\For SSH\\koderevox-content-factory-data\\renders` | render scratch space |
| `D:\\Code\\For SSH\\koderevox-content-factory-data\\logs` | retained service logs |
| `D:\\Code\\For SSH\\koderevox-content-factory-data\\models` | persistent Whisper/Hugging Face model cache |
| `D:\\Code\\For SSH\\koderevox-content-factory-data\\capability-test-artifacts` | capability-test MP4s, report and debug frames |

Install the current NVIDIA Windows driver, WSL2/Ubuntu, and Docker Desktop with the WSL2 backend.
In Docker Desktop, enable the Ubuntu WSL integration. Verify GPU passthrough before building:

```powershell
docker run --rm --gpus all nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04 nvidia-smi
```

Copy `.env.example` to `D:\\Code\\For SSH\\koderevox-content-factory-data\\config\\.env` and fill only the
credentials required for the services you intend to use. For the Windows GPU profile use
`STT_MODEL=small`, `STT_DEVICE=cuda`, and `STT_COMPUTE_TYPE=float16`. The compose file uses an
NVIDIA CUDA + cuDNN runtime and grants GPU access to the media and render workers.

Start the non-Telegram services (the bot is deliberately isolated behind the `telegram` profile):

```powershell
docker compose up -d --build
docker compose ps
curl http://localhost:8000/health
docker compose exec worker nvidia-smi
```

Run the deterministic test inside the GPU-enabled worker and retain its results outside Git:

```powershell
docker compose run --rm -e CAPABILITY_ARTIFACT_DIR=/data/capability-test-artifacts/latest worker python scripts/full_video_capability_test.py
```

The test must be configured with CUDA/STT `small` before it is considered a GPU result. Inspect
the resulting `video_capability_report.json`, `final.mp4`, and `debug-*.png`; use `ffprobe` to
verify 1080x1920 H.264 video, AAC audio and `yuv420p`.

### Safe Telegram cutover and homelab rollback

Keep the homelab bot polling/webhook active while Windows API, migrations, queues, GPU STT and the
full capability test are being verified. Back up the homelab database with `pg_dump` before any
restore, and copy only media and test artifacts after the backup has completed; never commit or
print `.env` values. When every Windows check passes, stop polling/webhook **only on the homelab**,
then start the Windows bot with `docker compose --profile telegram up -d bot` and send `/start`.
If it fails, stop the Windows bot and re-enable the homelab bot; do not delete the homelab data or
stack during rollback.
