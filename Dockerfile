FROM python:3.12-slim
RUN pip install --no-cache-dir uv==0.13.1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY moolai ./moolai
COPY queries ./queries
COPY config ./config
RUN uv sync --frozen --no-dev
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "moolai.api:app", "--host", "0.0.0.0", "--port", "8000"]
