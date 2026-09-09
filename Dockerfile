FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-pip \
        ffmpeg espeak-ng curl fonts-dejavu-core libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN python3.12 -m venv $VIRTUAL_ENV \
    && pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/media /tmp/content-factory/render \
    && chown -R appuser:appuser /app /data /tmp/content-factory
USER appuser
