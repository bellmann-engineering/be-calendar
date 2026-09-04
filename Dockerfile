FROM python:3.12-slim

WORKDIR /app

# System-Pakete (gcc wird für manche Python-Kompilierungen benötigt)
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App-Code kopieren
COPY . .

# Verzeichnis für Prompts sichern (falls es extern gemountet wird)
RUN mkdir -p prompts

EXPOSE 5000

# Gunicorn starten
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "wsgi:app"]
