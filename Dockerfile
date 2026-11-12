FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY demo ./demo
COPY experiments ./experiments
COPY data/processed ./data/processed
COPY data/raw/osm/roads.graphml ./data/raw/osm/roads.graphml
COPY app.py ./

RUN pip install --no-cache-dir ".[server]"

EXPOSE 8000

CMD ["uvicorn", "rra.api:app", "--host", "0.0.0.0", "--port", "8000"]
