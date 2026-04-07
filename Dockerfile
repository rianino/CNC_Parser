FROM python:3.12-slim

WORKDIR /app

# System deps for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev libtiff-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY hitex_tool/ hitex_tool/
COPY app/ app/

RUN pip install --no-cache-dir .

# Run as non-root user
RUN adduser --disabled-password --no-create-home --gecos "" appuser
USER appuser

ENV PORT=8080
ENV DOCKER=1

EXPOSE 8080

CMD ["python", "app/server.py"]
