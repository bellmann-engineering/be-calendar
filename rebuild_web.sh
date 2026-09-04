#!/bin/bash

echo "🔨 Baue Web-Container ohne Cache neu..."
sudo docker compose build --no-cache web

echo "🛑 Stoppe alten Container..."
sudo docker compose kill web

echo "🚀 Starte neuen Container..."
sudo docker compose up -d --force-recreate web

echo "✅ Fertig! Lade dein Dashboard jetzt mit Strg+F5 (oder Cmd+Shift+R) neu."
