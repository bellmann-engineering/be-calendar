import json
import os
import urllib.request
import urllib.error

# Lese die URL direkt aus den Docker-Umgebungsvariablen aus
url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434/api/generate")
model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

print(f"🔍 Sende KI-Anfrage an: {url}")
print(f"📦 Nutze Modell: {model}")

data = {"model": model, "prompt": "Hallo KI, antworte kurz mit 'OK'.", "stream": False}
req = urllib.request.Request(
    url,
    data=json.dumps(data).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    print("⏳ Warte auf Ollama (Timeout: 45 Sekunden)...")
    with urllib.request.urlopen(req, timeout=45) as response:
        result = json.loads(response.read().decode("utf-8"))
        print("✅ ERFOLG! KI sagt:", result.get("response", ""))
except urllib.error.HTTPError as e:
    print(f"❌ HTTP-FEHLER {e.code}: {e.read().decode('utf-8')}")
except Exception as e:
    print(f"❌ SYSTEM-FEHLER: {type(e).__name__} - {e}")
