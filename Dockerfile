FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY core core
COPY retrieval retrieval
COPY security security
COPY tools tools
COPY rlm rlm
COPY graph graph
COPY api api
COPY mcp_server mcp_server
COPY ui ui
RUN pip install -e ".[ui]"

COPY scripts scripts
COPY data/corpus data/corpus
COPY data/ground_truth.json data/ground_truth.json
COPY evals evals
RUN python -m retrieval.ingest --local

RUN useradd --create-home app && mkdir -p data/state && chown -R app data
USER app

EXPOSE 8000 8001 8501
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
