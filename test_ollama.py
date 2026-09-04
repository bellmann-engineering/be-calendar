import requests
import os
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("OLLAMA_BASE_URL", "http://172.20.0.1:11434")
print(f"🔍 Teste Verbindung zu: {url}/api/tags")

try:
    res = requests.get(f"{url}/api/tags", timeout=5)
    print("✅ Verbindung ERFOLGREICH!")
    print("📦 Installierte Modelle:", [m["name"] for m in res.json().get("models", [])])
except Exception as e:
    print("❌ VERBINDUNGSFEHLER:", type(e).__name__, "-", e)
