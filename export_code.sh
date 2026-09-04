#!/bin/bash
OUTPUT="proyecto_status.txt"
echo "Generando snapshot en $OUTPUT..."

# Datei leeren, falls sie bereits existiert.
> $OUTPUT

# Alle relevanten Dateiendungen suchen.
find . -type f \( \
  -name "*.py" -o \
  -name "*.yml" -o \
  -name "*.yaml" -o \
  -name "Dockerfile*" -o \
  -name "*.txt" -o \
  -name "*.conf" -o \
  -name "*.html" -o \
  -name "*.css" -o \
  -name "*.js" -o \
  -name "*.sh" -o \
  -name "*.md" -o \
  -name ".env" -o \
  -name ".dockerignore" -o \
  -name ".gitignore" \
\) \
  -not -path "*/venv/*" \
  -not -path "*/.git/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/postgres_data/*" | sort | while read -r file; do
    
    echo "================================================================" >> $OUTPUT
    echo "Archivo: $file" >> $OUTPUT
    echo "================================================================" >> $OUTPUT
    cat "$file" >> $OUTPUT
    echo -e "\n\n" >> $OUTPUT
    
done

echo "✅ Fertig! Die Datei $OUTPUT wurde erfolgreich erstellt."
