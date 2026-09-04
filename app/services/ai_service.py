import json
import os
import urllib.request
from typing import Optional


class AIService:
    """Zentrale Service-Schicht für die lokale Interaktion mit Ollama."""

    @staticmethod
    def ollama_anfrage_senden(prompt_text: str, model: str = None) -> Optional[str]:
        url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434/api/generate")
        if not model:
            model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        if ":" not in model:
            model = f"{model}:latest"

        data = {"model": model, "prompt": prompt_text, "stream": False}

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # Timeout auf 120 Sekunden erhöht für lokale CPU-Inferenz
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result.get("response", "").strip()
        except Exception as e:
            print(f"Fehler bei der Ollama-Anbindung: {e}")
            return None

    @staticmethod
    def analyze_conflicts(calendar_data_json: str) -> Optional[str]:
        prompt_path = os.path.join(os.getcwd(), "prompts", "conflict_prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        except FileNotFoundError:
            system_prompt = "Analysiere die folgenden Termindaten auf Überschneidungen:"

        full_prompt = (
            f"{system_prompt}\n\nKalenderdaten:\n{calendar_data_json}\n\nKI-Bericht:"
        )
        return AIService.ollama_anfrage_senden(full_prompt)
