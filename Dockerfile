# cjpa's Notes backend.
#
# The FastAPI app lives at src/backend and is imported as the top-level
# package `backend` (see pyproject.toml's `pythonpath = ["src"]` for the
# equivalent local/test setup). We reproduce that by copying src/backend
# into /app/backend and running uvicorn with /app as the working directory.
FROM python:3.11-slim

# ffmpeg provides ffprobe, used by backend/storage.py to read audio duration.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/backend ./backend

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
