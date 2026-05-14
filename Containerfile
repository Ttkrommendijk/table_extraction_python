FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
ENV APP_WORKERS=4
ENV APP_BACKLOG=2048

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api:app --host ${APP_HOST} --port ${APP_PORT} --workers ${APP_WORKERS} --backlog ${APP_BACKLOG}"]
