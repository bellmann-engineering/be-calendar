#!/usr/bin/env python3
"""
Erweiterter Diagnose- & Test-Runner
Phase 1: Umgebungs- und Netzwerkvalidierung (PostgreSQL, Ollama, Modelle)
Phase 2: Flask-Interzeptoren (Logs 4xx/5xx)
Phase 3: Dynamische Ausführung von Unit-Tests
"""

import importlib.util
import os
import sys
import traceback
import unittest
import socket
import urllib.request
import json
from flask import Flask, got_request_exception

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- PHASE 1: PRE-FLIGHT CHECKS ---


def print_status(step: str, success: bool, details: str = ""):
    color = "\033[92m[OK]\033[0m" if success else "\033[91m[FAIL]\033[0m"
    print(f"{color} {step} {details}")


def check_tcp_port(host: str, port: int, service_name: str) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            print_status(f"TCP-Verbindung zu {service_name} ({host}:{port})", True)
            return True
    except Exception as e:
        print_status(
            f"TCP-Verbindung zu {service_name} ({host}:{port})", False, f"-> {e}"
        )
        return False


def check_ollama_model(url: str, required_model: str):
    tags_url = url.replace("/api/generate", "/api/tags").replace(
        "/api/chat", "/api/tags"
    )
    try:
        response = urllib.request.urlopen(tags_url, timeout=3).read().decode("utf-8")
        models_data = json.loads(response).get("models", [])
        installed_models = [m["name"] for m in models_data]

        if required_model in installed_models:
            print_status(
                f"Ollama-Modell '{required_model}'", True, "Installiert und bereit."
            )
        else:
            print_status(
                f"Ollama-Modell '{required_model}'",
                False,
                f"-> Erkannte Modelle: {installed_models}",
            )
    except Exception as e:
        print_status("Ollama API-Abfrage (/api/tags)", False, f"-> {e}")


def run_pre_flight_checks():
    print("\n" + "=" * 50)
    print(" STARTE SYSTEMDIAGNOSE (PRE-FLIGHT)")
    print("=" * 50)

    # 1. Datenbank
    db_host = os.environ.get("DB_HOST", "db")
    check_tcp_port(db_host, 5432, "PostgreSQL")

    # 2. Kritische Variablen
    if not os.environ.get("DEV_USER_PASSWORD"):
        print_status(
            "Variable DEV_USER_PASSWORD", False, "Nicht in der Umgebung definiert."
        )
    else:
        print_status("Variable DEV_USER_PASSWORD", True)

    # 3. Ollama Netzwerk & Modelle
    ollama_url = os.environ.get(
        "OLLAMA_URL", "http://host.docker.internal:11434/api/generate"
    )
    host = urllib.parse.urlparse(ollama_url).hostname
    port = urllib.parse.urlparse(ollama_url).port or 11434

    if check_tcp_port(host, port, "Ollama Gateway"):
        # Modell aus Code oder Umgebung extrahieren
        model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
        check_ollama_model(ollama_url, model)
    print("=" * 50 + "\n")


# --- PHASE 2: FLASK DEBUG HOOKS ---


def attach_debug_listeners(app: Flask) -> None:
    if getattr(app, "_debug_hooks_attached", False):
        return
    app._debug_hooks_attached = True

    @got_request_exception.connect_via(app)
    def log_exception(sender, exception, **extra):
        print("\n" + "!" * 80)
        print(f" UNBEHANDELTE AUSNAHME (HTTP 500) IN ROUTE: {exception}")
        traceback.print_exception(type(exception), exception, exception.__traceback__)
        print("!" * 80 + "\n")

    @app.after_request
    def log_bad_response(response):
        if response.status_code >= 400:
            print("\n" + "-" * 80)
            print(f" HTTP FEHLER-ANTWORT [{response.status_code}]")
            try:
                json_data = response.get_json()
                print(f" Payload: {json_data}")
            except Exception:
                print(f" Body: {response.get_data(as_text=True)}")
            print("-" * 80 + "\n")
        return response


_original_init = Flask.__init__


def _patched_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    attach_debug_listeners(self)


Flask.__init__ = _patched_init


# --- PHASE 3: DYNAMISCHER TEST-RUNNER ---

if __name__ == "__main__":
    run_pre_flight_checks()

    print(" STARTE UNIT-TEST-BATTERIE")
    print("=" * 50)
    tests_dir = os.path.join(project_root, "tests")
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    for fname in sorted(os.listdir(tests_dir)):
        if fname.startswith("test_") and fname.endswith(".py"):
            mod_name = fname[:-3]
            file_path = os.path.join(tests_dir, fname)
            try:
                spec = importlib.util.spec_from_file_location(mod_name, file_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name] = mod
                    spec.loader.exec_module(mod)
                    mod_tests = loader.loadTestsFromModule(mod)
                    suite.addTests(mod_tests)
            except Exception:
                print("\n" + "!" * 80)
                print(f" FEHLER BEIM LADEN DER TESTDATEI '{fname}':")
                traceback.print_exc()
                print("!" * 80 + "\n")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(not result.wasSuccessful())
