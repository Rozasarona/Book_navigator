FROM python:3.12-slim
WORKDIR /app
COPY . /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/app/data/book_navigator.db
RUN mkdir -p /app/data
VOLUME /app/data
CMD python main.py bot

