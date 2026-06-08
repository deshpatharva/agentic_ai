FROM python:3.12-slim

WORKDIR /app

# Install system deps needed by pdfplumber / spaCy / crewai
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt lives one level up from backend/.
# Build context must be resume-optimizer/ — run from there:
#   docker build -f backend/Dockerfile -t resume-optimizer-backend .
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        asyncpg \
        "sqlalchemy[asyncio]"

# spaCy model is installed via the pinned wheel in requirements.txt — no separate download needed

COPY backend/ /app/backend
WORKDIR /app/backend

# Runtime directories (outputs/uploads are ephemeral in prod; mount a volume or use blob storage)
RUN mkdir -p uploads outputs

EXPOSE 8000

# 2 workers: one serves requests while the other runs a pipeline in asyncio.to_thread.
# --timeout 300: SSE streams and 5-min pipelines exceed the default 30s worker timeout.
CMD ["gunicorn", "main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "2", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "300", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
