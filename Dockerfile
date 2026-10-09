FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir '.[discord]'

COPY profiles ./profiles
COPY fixtures ./fixtures

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown app /app/data
USER app

CMD ["haa", "demo"]
