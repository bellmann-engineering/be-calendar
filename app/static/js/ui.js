/**
 * =====================================================================
 * Datei: app/static/js/ui.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Kleine, abhängigkeitsfreie UI-Bibliothek für alle Seiten:
 *     - h()             → sicherer DOM-Baukasten (statt innerHTML)
 *     - icon()          → Icon aus dem SVG-Sprite (_icons.html)
 *     - toast()         → kurze Rückmeldung unten rechts (ersetzt alert())
 *     - confirmDialog() → Bestätigungsdialog als Promise (ersetzt confirm())
 *     - openDialog()/closeDialog() → native <dialog>-Elemente steuern
 *     - setupPopover()  → Dropdowns (Tastatur, Klick außerhalb, Esc)
 *     - setBusy()       → Lade-Zustand für Buttons
 *     - showFormError() / hideFormError() → Fehlermeldung in Formularen
 *     - emptyRow(), initials(), readableTextColor(), formatRelativeTime()
 *
 * Wer lädt diese Datei?
 *   base.html auf JEDER Seite, als erstes Skript (defer). Alle Funktionen
 *   sind globale Funktionen (klassische Skripte, kein Bundler) und stehen
 *   damit app.js und den Seiten-Skripten unter js/pages/ zur Verfügung.
 *
 * Mit welchen Endpunkten spricht diese Datei?
 *   Mit keinem – reine Oberfläche.
 *
 * Abhängigkeiten:
 *   HTML-Bausteine aus base.html: #toast-region, #confirm-dialog und das
 *   Icon-Sprite (<symbol id="i-...">).
 *
 * Sicherheitsprinzip (XSS):
 *   h() setzt Texte IMMER als Textknoten und Attribute über setAttribute.
 *   Event-Handler-Attribute (onclick="...") und style-Attribute werden
 *   bewusst abgelehnt – so kann weder eingeschleustes HTML noch Code aus
 *   API-Daten ausgeführt werden, und die strenge CSP bleibt eingehalten.
 * =====================================================================
 */

/* ------------------------------------------------------------------ */
/* DOM-Baukasten                                                      */
/* ------------------------------------------------------------------ */

/** SVG-Namensraum – SVG-Elemente müssen mit createElementNS erzeugt werden. */
const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * Erzeugt ein HTML-Element – die sichere Alternative zu innerHTML.
 *
 * Beispiel:
 *   h("p", { class: "text-sm", "data-id": 5 }, "Hallo ", h("b", {}, name))
 *
 * @param {string} tag - Tag-Name, z. B. "div".
 * @param {object} [attrs={}] - Attribute. Sonderfälle:
 *        class   → className
 *        text    → textContent
 *        on      → { click: fn, ... } echte Event-Listener
 *        dataset → { id: 1 } → data-id="1"
 *        Werte null/undefined/false werden ausgelassen, true = leeres Attribut.
 * @param {...(Node|string|number|null|undefined|Array)} children - Kinder;
 *        Strings/Zahlen werden zu Textknoten (NIE als HTML interpretiert).
 * @returns {HTMLElement}
 */
function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
        if (value === null || value === undefined || value === false) continue;
        if (key === "class") el.className = value;
        else if (key === "text") el.textContent = String(value);
        else if (key === "on") {
            for (const [evt, fn] of Object.entries(value)) el.addEventListener(evt, fn);
        } else if (key === "dataset") {
            for (const [k, v] of Object.entries(value)) el.dataset[k] = String(v);
        } else if (/^on/i.test(key) || key === "style") {
            // Inline-Handler und style-Attribute würden gegen die CSP verstoßen
            // und sind ein klassisches XSS-Einfallstor → hart verweigern.
            throw new Error(`h(): Attribut "${key}" ist nicht erlaubt.`);
        } else {
            el.setAttribute(key, value === true ? "" : String(value));
        }
    }
    appendChildren(el, children);
    return el;
}

/**
 * Hängt Kinder an ein Element an (verschachtelte Arrays erlaubt).
 * @param {Node} el
 * @param {Array} children
 */
function appendChildren(el, children) {
    for (const child of children.flat(Infinity)) {
        if (child === null || child === undefined || child === false) continue;
        el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
}

/**
 * Erzeugt ein Icon aus dem Sprite in base.html (<symbol id="i-NAME">).
 * @param {string} name - Icon-Name, z. B. "bell".
 * @param {string} [cls="size-4"] - CSS-Klassen.
 * @returns {SVGSVGElement}
 */
function icon(name, cls = "size-4") {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", cls);
    svg.setAttribute("aria-hidden", "true"); // Dekoration – Bedeutung trägt der Text
    svg.setAttribute("focusable", "false");
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", `#i-${name}`);
    svg.appendChild(use);
    return svg;
}

/**
 * Tabellenzeile für leere Zustände / Fehler, die über alle Spalten geht.
 * @param {number} colspan - Anzahl der Tabellenspalten.
 * @param {string} iconName - Icon im Kreis.
 * @param {string} title - Überschrift.
 * @param {string} [text] - Erklärung darunter.
 * @param {Node} [action] - optionaler Button.
 * @returns {HTMLTableRowElement}
 */
function emptyRow(colspan, iconName, title, text, action) {
    return h("tr", {},
        h("td", { colspan },
            h("div", { class: "empty-state" },
                h("div", { class: "empty-state-icon" }, icon(iconName)),
                h("p", { class: "text-sm font-semibold text-fg", text: title }),
                text ? h("p", { class: "max-w-sm text-sm text-fg-muted", text }) : null,
                action ? h("div", { class: "mt-3" }, action) : null,
            ),
        ),
    );
}

/**
 * Initialen für Avatare ("Tom Trainer" → "TT").
 * @param {string} first
 * @param {string} [last]
 * @returns {string}
 */
function initials(first, last) {
    const a = (first || "").trim().charAt(0);
    const b = (last || "").trim().charAt(0);
    return (a + b).toUpperCase() || "?";
}

/**
 * Wählt Weiß oder Dunkelblau als Schriftfarbe für eine Hintergrundfarbe
 * (WCAG-Luminanzformel, Mindestkontrast 4,5:1).
 * WARUM: Kundenfarben sind frei wählbar – ein helles Gelb mit weißer
 * Schrift wäre unlesbar.
 *
 * @param {string} hex - Farbe im Format #RRGGBB (vorher validieren!).
 * @returns {string} "#0f1b2d" oder "#ffffff".
 */
function readableTextColor(hex) {
    const rgb = [1, 3, 5].map(i => parseInt(hex.substr(i, 2), 16) / 255)
        .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    const luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
    // Weiß wirkt auf farbigen Flächen ruhiger – solange es WCAG AA (4,5:1)
    // erreicht, wird es bevorzugt. Nur auf hellen Farben: dunkle Schrift.
    const contrastWhite = 1.05 / (luminance + 0.05);
    return contrastWhite >= 4.5 ? "#ffffff" : "#0f1b2d";
}

/** Formatierer für relative Zeitangaben ("vor 5 Minuten"). */
const RELATIVE_TIME = new Intl.RelativeTimeFormat("de", { numeric: "auto" });

/**
 * Formatiert einen Zeitpunkt relativ zu jetzt, z. B. "vor 3 Stunden".
 * @param {string} iso - ISO-Zeitstempel.
 * @returns {string}
 */
function formatRelativeTime(iso) {
    const date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    const units = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]];
    for (const [unit, size] of units) {
        if (Math.abs(seconds) >= size) return RELATIVE_TIME.format(Math.round(seconds / size), unit);
    }
    return "gerade eben";
}

/* ------------------------------------------------------------------ */
/* Buttons & Formulare                                                */
/* ------------------------------------------------------------------ */

/**
 * Setzt einen Button in den Lade-Zustand (Spinner, deaktiviert) und zurück.
 * Der ursprüngliche Inhalt wird gemerkt und danach wiederhergestellt.
 *
 * @param {HTMLButtonElement} btn
 * @param {boolean} busy
 * @param {string} [busyText] - Text während des Ladens (z. B. "Speichert …").
 */
function setBusy(btn, busy, busyText) {
    if (!btn) return;
    if (busy) {
        if (!btn._original) btn._original = Array.from(btn.childNodes).map(n => n.cloneNode(true));
        btn.disabled = true;
        btn.setAttribute("aria-busy", "true");
        btn.replaceChildren(h("span", { class: "spinner", "aria-hidden": "true" }), busyText || "Bitte warten …");
    } else {
        btn.disabled = false;
        btn.removeAttribute("aria-busy");
        if (btn._original) btn.replaceChildren(...btn._original);
        btn._original = null;
    }
}

/**
 * Zeigt eine Fehlermeldung in einem Formular-Bereich an (als reiner Text).
 * Der Bereich hat role="alert" im Template → Screenreader lesen sie sofort vor.
 *
 * @param {HTMLElement|string} target - Element oder dessen ID.
 * @param {string} message
 */
function showFormError(target, message) {
    const el = typeof target === "string" ? document.getElementById(target) : target;
    if (!el) return;
    el.replaceChildren(icon("alert"), h("span", { text: message }));
    el.hidden = false;
}

/**
 * Blendet eine Formular-Fehlermeldung wieder aus.
 * @param {HTMLElement|string} target
 */
function hideFormError(target) {
    const el = typeof target === "string" ? document.getElementById(target) : target;
    if (el) el.hidden = true;
}

/* ------------------------------------------------------------------ */
/* Toasts                                                             */
/* ------------------------------------------------------------------ */

/** Aussehen je Toast-Typ: [Icon, Farbklasse des Icons]. */
const TOAST_STYLES = {
    success: ["check-circle", "text-success"],
    error: ["x-circle", "text-danger"],
    info: ["info", "text-accent"],
    warning: ["alert", "text-warning"],
};

/**
 * Zeigt eine kurze Rückmeldung an (ersetzt alert()).
 * Fehler bekommen role="alert" (sofortige Ansage), andere werden über die
 * aria-live-Region "polite" angesagt.
 *
 * @param {string} message - Text (wird als Text, nie als HTML eingefügt).
 * @param {"success"|"error"|"info"|"warning"} [type="success"]
 * @param {number} [duration=4500] - Anzeigedauer in ms (Fehler länger).
 */
function toast(message, type = "success", duration) {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const [iconName, iconClass] = TOAST_STYLES[type] || TOAST_STYLES.info;
    const close = h("button", {
        type: "button", class: "btn-icon btn-icon-sm -my-1 -mr-2", "aria-label": "Meldung schließen",
    }, icon("x"));
    const el = h("div", { class: "toast", role: type === "error" ? "alert" : null },
        icon(iconName, `size-5 ${iconClass}`),
        h("p", { class: "flex-1 leading-snug", text: message }),
        close,
    );
    const remove = () => el.remove();
    close.addEventListener("click", remove);
    region.appendChild(el);
    setTimeout(remove, duration || (type === "error" ? 8000 : 4500));
}

/* ------------------------------------------------------------------ */
/* Dialoge                                                            */
/* ------------------------------------------------------------------ */

/**
 * Öffnet ein <dialog> modal. showModal() sperrt den Hintergrund (inert),
 * hält den Fokus im Dialog und schließt mit der Esc-Taste.
 * @param {HTMLDialogElement|string} dialog - Element oder ID.
 */
function openDialog(dialog) {
    const el = typeof dialog === "string" ? document.getElementById(dialog) : dialog;
    if (el && !el.open) el.showModal();
}

/**
 * Schließt ein <dialog>.
 * @param {HTMLDialogElement|string} dialog - Element oder ID.
 */
function closeDialog(dialog) {
    const el = typeof dialog === "string" ? document.getElementById(dialog) : dialog;
    if (el && el.open) el.close();
}

/**
 * Verdrahtet allgemeine Dialog-Bedienung für alle <dialog class="dialog">:
 *   - Buttons mit data-close-dialog schließen den umgebenden Dialog
 *   - Klick auf den abgedunkelten Hintergrund schließt ebenfalls
 */
function setupDialogs() {
    document.addEventListener("click", (e) => {
        const closer = e.target.closest("[data-close-dialog]");
        if (closer) closer.closest("dialog")?.close();
    });
    document.querySelectorAll("dialog.dialog").forEach(dialog => {
        // Ein Klick direkt auf das <dialog>-Element (nicht auf dessen Inhalt) ist ein
        // Klick auf den Hintergrund außerhalb der Box.
        dialog.addEventListener("mousedown", (e) => {
            if (e.target !== dialog) return;
            const r = dialog.getBoundingClientRect();
            const outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
            if (outside) dialog.close();
        });
    });
}

/**
 * Zeigt einen Bestätigungsdialog und wartet auf die Entscheidung.
 * Ersetzt window.confirm() – barrierefrei, im Design der App.
 *
 * @param {object} options
 * @param {string} options.title - Überschrift (Frage).
 * @param {string} [options.message] - Erklärung.
 * @param {string} [options.confirmText="Bestätigen"]
 * @param {boolean} [options.danger=true] - roter Bestätigen-Button.
 * @returns {Promise<boolean>} true = bestätigt.
 */
function confirmDialog({ title, message = "", confirmText = "Bestätigen", danger = true }) {
    const dialog = document.getElementById("confirm-dialog");
    if (!dialog) return Promise.resolve(false);
    document.getElementById("confirm-title").textContent = title;
    document.getElementById("confirm-message").textContent = message;
    const ok = document.getElementById("confirm-ok");
    ok.textContent = confirmText;
    ok.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
    document.getElementById("confirm-icon").hidden = !danger;
    dialog.returnValue = "";
    return new Promise(resolve => {
        // "close" feuert bei Button-Klick (form method=dialog), Esc und Hintergrund-Klick.
        dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
        dialog.showModal();
        document.getElementById("confirm-cancel").focus(); // sichere Wahl vorausgewählt
    });
}

/* ------------------------------------------------------------------ */
/* Popover / Dropdown                                                 */
/* ------------------------------------------------------------------ */

/** Aktuell offenes Popover (es ist immer höchstens eines offen). */
let openPopover = null;

/**
 * Macht aus einem Button + Panel ein barrierefreies Dropdown:
 *   - Klick/Enter/Leertaste öffnet und schließt (aria-expanded wird gepflegt)
 *   - Esc schließt und gibt den Fokus an den Button zurück
 *   - Klick außerhalb schließt
 *
 * @param {HTMLElement} button - Auslöser (mit aria-controls).
 * @param {HTMLElement} panel - Das Dropdown (anfangs hidden).
 * @param {Function} [onOpen] - wird beim Öffnen aufgerufen.
 */
function setupPopover(button, panel, onOpen) {
    if (!button || !panel) return;
    const close = (focusButton) => {
        panel.hidden = true;
        button.setAttribute("aria-expanded", "false");
        if (openPopover && openPopover.panel === panel) openPopover = null;
        if (focusButton) button.focus();
    };
    const open = () => {
        if (openPopover) openPopover.close(false); // anderes Dropdown zuerst schließen
        panel.hidden = false;
        button.setAttribute("aria-expanded", "true");
        openPopover = { panel, close };
        if (onOpen) onOpen();
    };
    button.addEventListener("click", (e) => {
        e.stopPropagation();
        if (panel.hidden) open(); else close(false);
    });
    panel.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.stopPropagation(); close(true); }
    });
    button.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !panel.hidden) close(true);
    });
    document.addEventListener("click", (e) => {
        if (!panel.hidden && !panel.contains(e.target) && !button.contains(e.target)) close(false);
    });
}

// Dialoge verdrahten, sobald das DOM steht (Skript ist "defer" → DOM ist fertig).
document.addEventListener("DOMContentLoaded", setupDialogs);
