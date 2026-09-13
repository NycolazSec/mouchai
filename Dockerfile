FROM python:3.12-slim

WORKDIR /app

# Dépendances système pour Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 50041

# Lancement avec Gunicorn (adapte app:app selon la variable Flask dans app.py)
CMD ["gunicorn", "--bind", "0.0.0.0:50041", "app:app"]