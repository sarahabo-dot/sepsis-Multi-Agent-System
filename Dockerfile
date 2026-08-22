FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY docs ./docs
COPY tests ./tests
WORKDIR /app/backend
ENV PYTHONPATH=/app/backend
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
