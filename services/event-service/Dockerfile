FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml ./
RUN uv sync --no-dev
COPY app ./app
EXPOSE 5000
CMD ["uv", "run", "flask", "--app", "app", "run", "--host=0.0.0.0"]

