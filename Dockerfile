FROM python:3.11-slim

# Install curl for container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache requirements layer for fast builds
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY api/ ./api/
COPY seeds/ ./seeds/
COPY reports/ ./reports/

ENV PYTHONUNBUFFERED=1 \
    API_PORT=8080

EXPOSE 8080

CMD ["python", "-m", "api.main"]
