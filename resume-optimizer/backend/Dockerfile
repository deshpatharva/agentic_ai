FROM python:3.11-slim

WORKDIR /app

# Install system deps needed by pdfplumber / spaCy
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY ../requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        asyncpg \
        sqlalchemy[asyncio] \
        alembic \
        python-jose[cryptography] \
        bcrypt \
        passlib

# Download spaCy model
RUN python -m spacy download en_core_web_sm

COPY . /app/backend
WORKDIR /app/backend

# Runtime directories (outputs/uploads are ephemeral in prod; mount a volume or use blob storage)
RUN mkdir -p uploads outputs

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
