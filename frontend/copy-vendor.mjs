/**
 * =====================================================================
 * Datei: frontend/copy-vendor.mjs
 * ---------------------------------------------------------------------
 * Zweck:
 *   Kopiert die Fremdbibliotheken, die der Browser direkt lädt, aus
 *   node_modules/ nach app/static/dist/ – damit sie von UNSERER Domain
 *   ausgeliefert werden (kein Drittanbieter-CDN, strenge CSP möglich).
 *
 *   Kopiert werden:
 *     - FullCalendar 6 (fertiges "global"-Bundle, stellt window.FullCalendar bereit)
 *       → app/static/dist/vendor/fullcalendar.min.js (+ Lizenz)
 *     - Schrift "Inter" (variabel, nur lateinischer Zeichensatz inkl. ä/ö/ü/ß)
 *       → app/static/dist/fonts/inter-latin-wght-normal.woff2 (+ Lizenz)
 *
 * Wer ruft das auf?
 *   "npm run build:vendor" bzw. "npm run build" (package.json) – lokal
 *   und in der Node-Stufe des Dockerfiles.
 *
 * Abhängigkeiten:
 *   Nur Node.js-Bordmittel (fs, path, url). Die Versionen der kopierten
 *   Pakete sind in package.json exakt gepinnt, package-lock.json sichert
 *   zusätzlich die Prüfsummen.
 *
 * Hinweis:
 *   app/static/dist/ ist ein Build-Ergebnis und steht in .gitignore.
 * =====================================================================
 */
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Projektwurzel = eine Ebene über diesem Skript (frontend/..).
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const NODE_MODULES = join(ROOT, "node_modules");
const DIST = join(ROOT, "app", "static", "dist");

/** Liste aller Kopieraufträge: [Quelle relativ zu node_modules, Ziel relativ zu dist]. */
const FILES = [
    ["fullcalendar/index.global.min.js", "vendor/fullcalendar.min.js"],
    ["fullcalendar/LICENSE.md", "vendor/fullcalendar.LICENSE.md"],
    ["@fontsource-variable/inter/files/inter-latin-wght-normal.woff2", "fonts/inter-latin-wght-normal.woff2"],
    ["@fontsource-variable/inter/LICENSE", "fonts/inter.LICENSE.txt"],
];

for (const [source, target] of FILES) {
    const from = join(NODE_MODULES, source);
    const to = join(DIST, target);
    if (!existsSync(from)) {
        // Klare Fehlermeldung statt Stacktrace: meist fehlt "npm ci".
        console.error(`Datei fehlt: ${from}\nBitte zuerst "npm ci" ausführen.`);
        process.exit(1);
    }
    mkdirSync(dirname(to), { recursive: true });
    copyFileSync(from, to);
    console.log(`kopiert: ${source} -> app/static/dist/${target}`);
}
