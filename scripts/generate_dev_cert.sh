#!/usr/bin/env bash
# =============================================================================
# generate_dev_cert.sh – Erzeugt ein selbstsigniertes TLS-Zertifikat für Nginx
# -----------------------------------------------------------------------------
# Wofür?  HTTPS lokal bzw. im Intranet, solange es keine öffentliche Domain mit
#         echtem Zertifikat (z. B. Let's Encrypt) gibt.
# Ergebnis: nginx/certs/fullchain.pem (Zertifikat) + nginx/certs/privkey.pem (Schlüssel)
#           – beides wird von docker-compose.yml read-only in Nginx eingehängt und ist
#           per .gitignore von Git ausgeschlossen.
# Aufruf:   ./scripts/generate_dev_cert.sh [zusätzlicher-hostname-oder-ip ...]
#           Beispiel für Zugriff aus dem Büronetz: ./scripts/generate_dev_cert.sh 192.168.1.50
#
# Hinweis: Der Browser warnt bei selbstsignierten Zertifikaten ("nicht sicher"), weil
# keine bekannte Zertifizierungsstelle unterschrieben hat. Die Verbindung ist trotzdem
# verschlüsselt. Für eine Anzeige ohne Warnung: Zertifikat im System als vertrauens-
# würdig importieren oder das Werkzeug "mkcert" verwenden.
# Vorhandene Zertifikate werden NICHT überschrieben (außer mit --force).
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
CERT_DIR="nginx/certs"
FORCE=0
EXTRA_NAMES=()
for arg in "$@"; do
    if [ "$arg" = "--force" ]; then FORCE=1; else EXTRA_NAMES+=("$arg"); fi
done

if [ -f "$CERT_DIR/fullchain.pem" ] && [ "$FORCE" = "0" ]; then
    echo "Zertifikat existiert bereits ($CERT_DIR/fullchain.pem) – nichts zu tun (--force erneuert)."
    exit 0
fi

mkdir -p "$CERT_DIR"

# Subject Alternative Names: Moderne Browser prüfen NUR diese Liste, nicht den CN.
SAN="DNS:localhost,IP:127.0.0.1"
for name in "${EXTRA_NAMES[@]}"; do
    if [[ "$name" =~ ^[0-9.]+$ ]]; then SAN="$SAN,IP:$name"; else SAN="$SAN,DNS:$name"; fi
done

# RSA 2048 + SHA-256, 825 Tage (Maximum, das Apple/Chrome für Zertifikate akzeptieren).
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 825 \
    -keyout "$CERT_DIR/privkey.pem" -out "$CERT_DIR/fullchain.pem" \
    -subj "/CN=localhost/O=Bellmann Engineering (Entwicklung)" \
    -addext "subjectAltName=$SAN" \
    -addext "keyUsage=digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" 2>/dev/null

# Der Schlüssel muss für den Nginx-Container lesbar sein (bind mount).
chmod 644 "$CERT_DIR/fullchain.pem" "$CERT_DIR/privkey.pem"
echo "Zertifikat erstellt: $CERT_DIR/fullchain.pem (SAN: $SAN)"
