FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml LICENSE README.md ./
COPY quotedesk ./quotedesk
COPY seeds ./seeds
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir ".[dev]"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "quotedesk.infrastructure.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
