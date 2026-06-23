FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_SYSTEM_PYTHON=1

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 의존성 레이어 (소스 변경 시 캐시 재사용)
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --no-dev --frozen


EXPOSE 8000

CMD ["uv", "run", "uvicorn", "agenttrace.app.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
