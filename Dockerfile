FROM python:3.12-slim

# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p instance/uploads backups

EXPOSE 8000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "run:app"]
