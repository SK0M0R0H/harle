FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 1000 --shell /bin/bash harle

COPY pyproject.toml ./
COPY src/ ./src/

FROM base AS test

COPY tests/ ./tests/

RUN pip install --no-cache-dir ".[test]" \
    && pytest -q tests/unit

FROM base AS runtime

RUN pip install --no-cache-dir .

USER harle

EXPOSE 8000

CMD ["harle-server"]
