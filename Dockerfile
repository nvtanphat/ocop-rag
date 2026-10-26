FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
# sparse: BM25 only. hybrid: also installs dense retrieval dependencies and requires a reachable Qdrant.
ARG OCOP_PROFILE=sparse
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OCOP_RETRIEVAL_PROFILE=${OCOP_PROFILE}
COPY pyproject.toml ./
COPY ai_core ./ai_core
COPY backend ./backend
COPY tools ./tools
COPY configs ./configs
COPY ocop_contracts ./ocop_contracts
COPY --from=frontend /frontend/dist ./frontend/dist
RUN --mount=type=cache,target=/root/.cache/pip \
    case "$OCOP_PROFILE" in \
      sparse) extras="agent" ;; \
      hybrid) extras="agent,retrieval" ;; \
      *) echo "OCOP_PROFILE must be sparse or hybrid" >&2; exit 1 ;; \
    esac \
    && pip install ./ocop_contracts ".[${extras}]"
RUN useradd --create-home --uid 10001 ocop && mkdir -p /app/data && chown ocop:ocop /app/data
USER ocop
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ocop/health')" || exit 1
CMD ["python", "-m", "uvicorn", "backend.api.ocop_main:app", "--host", "0.0.0.0", "--port", "8000"]
