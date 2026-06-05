FROM python:3.12-slim

WORKDIR /app

# Install deps first (layer cache — only re-runs when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 13377

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "13377"]
