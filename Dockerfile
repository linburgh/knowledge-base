FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    OS_CONFIG_DIR=/etc/app

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY workers ./workers
COPY scripts ./scripts
COPY etc/app.yaml.example /etc/app/app.yaml
COPY etc/gunicorn.conf.py ./etc/gunicorn.conf.py

EXPOSE 28003

CMD ["gunicorn", "-c", "etc/gunicorn.conf.py", "app.main:app"]
