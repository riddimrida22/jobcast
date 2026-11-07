# For Google Cloud Run (matches the existing Google/GCE stack). Cloud Run sets $PORT.
FROM python:3.12-slim
WORKDIR /app
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt
COPY . .
ENV JOBCAST_NOINDEX=1 \
    JOBCAST_SNAPSHOT=/app/data/demo/snapshot.json
# Timeout is generous: the research tiers run Claude with web search, which can take minutes.
CMD exec gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 2 --timeout 240
