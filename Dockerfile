FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml ./
COPY ai_core ./ai_core
COPY backend ./backend
COPY tools ./tools
COPY configs ./configs
RUN pip install --no-cache-dir ".[easy_vietocr]"
RUN useradd --create-home --uid 10001 ocop && mkdir -p /app/data && chown ocop:ocop /app/data
USER ocop
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ocop/health')" || exit 1
CMD ["python", "tools/cli.py", "run", "--host", "0.0.0.0", "--port", "8000"]
