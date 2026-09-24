/**
 * =====================================================================
 * Datei: app/static/js/app.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Kern-Skript des Bellmann Calendar, von base.html auf JEDER Seite
 *   geladen (nach ui.js, vor dem Seiten-Skript aus js/pages/).
 *
 * Was diese Datei bereitstellt:
 *   1. Globale Hilfsfunktionen für alle Seiten-Skripte:
 *        - escapeHtml()      → Text HTML-sicher machen (falls doch einmal
 *                              HTML-Strings nötig sind; bevorzugt: ui.js::h())
 *        - getCookie()       → liest die CSRF-Cookies des Servers
 *        - apiFetch()        → zentraler fetch-Wrapper: Cookies, CSRF-Header,
 *                              JSON, automatischer Token-Refresh bei 401
 *        - readJson()        → JSON-Antwort fehlertolerant lesen
 *        - getCurrentUser()  → eingeloggten Benutzer genau einmal laden
 *                              (window.currentUserPromise)
 *        - isSafeHttpUrl(), isValidHexColor(), toDatetimeLocal(),
 *          toDateLocal(), toUtcIso(), roleLabel(), roleBadgeClass()
 *   2. Die App-Kopfzeile: rollenabhängige Navigation, mobiles Menü,
 *      Benutzermenü mit Abmelden, Benachrichtigungs-Glocke.
 *   3. Sitzungsschutz: Auf geschützten Seiten ohne Login → /login.
 *
 * Mit welchen Backend-Endpunkten spricht diese Datei?
 *   POST /api/v1/auth/refresh       → neues Access-Token per Refresh-Cookie
 *   POST /api/v1/auth/logout        → Cookies löschen
 *   GET  /api/v1/auth/me            → Daten des eingeloggten Benutzers
 *   GET  /api/v1/notifications      → In-App-Benachrichtigungen
 *   PUT  /api/v1/notifications/<id>/read
 *
 * Wovon hängt diese Datei ab?
 *   - ui.js (h, icon, toast, setupPopover, initials, formatRelativeTime)
 *   - HTML-Elemente aus base.html (#user-info, #notif-list, #logout-btn ...)
 *   - Cookies, die das Flask-Backend (flask-jwt-extended) setzt:
 *       access_token_cookie  (HttpOnly → für JS unsichtbar, gut so!)
 *       refresh_token_cookie (HttpOnly)
 *       csrf_access_token    (für JS lesbar → X-CSRF-TOKEN Header)
 *       csrf_refresh_token   (für JS lesbar → beim Refresh)
 *
 * Sicherheitsprinzip:
 *   Das JWT liegt in einem HttpOnly-Cookie – selbst eingeschleustes
 *   JavaScript könnte es nicht auslesen. Alle Daten aus der API werden
 *   per textContent/h() eingefügt, niemals als HTML.
 * =====================================================================
 */

/* ------------------------------------------------------------------ */
/* Konstanten                                                         */
/* ------------------------------------------------------------------ */

/** Seiten, die OHNE Login erreichbar sein müssen (kein Redirect auf /login). */
const PUBLIC_PATHS = ["/login", "/reset-password"];

/** HTTP-Methoden, die Daten verändern und deshalb einen CSRF-Header brauchen. */
const UNSAFE_METHODS = ["POST", "PUT", "PATCH", "DELETE"];

/**
 * Auth-Endpunkte, bei denen ein 401 KEINEN Refresh-Versuch auslösen darf.
 * Beispiel: falsches Passwort beim Login liefert 401 – ein Refresh wäre
 * dort sinnlos und würde nur eine Endlosschleife riskieren.
 */
const NO_REFRESH_ENDPOINTS = [
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
];

/** Erlaubtes Farbformat für Kundenfarben (identisch zur Server-Validierung). */
const HEX_COLOR_RE = /^#[0-9A-Fa-f]{6}$/;

/** Standardfarbe für Termine ohne (gültige) Kundenfarbe (= Bellmann-Akzent). */
const DEFAULT_EVENT_COLOR = "#2B6CB0";

/** Rollen, die Termine planen dürfen (Anlegen, Bearbeiten, Neu-Zuweisen). */
const PLANNER_ROLES = ["CEO", "ADMIN", "TEAM_LEADER"];

/** Lesbare Rollenbezeichnungen für die Oberfläche. */
const ROLE_LABELS = { CEO: "CEO", ADMIN: "Administrator", TEAM_LEADER: "Teamleitung", TRAINER: "Trainer" };

/** Badge-Farbe je Rolle (Klassen aus frontend/app.css). */
const ROLE_BADGES = { CEO: "badge-violet", ADMIN: "badge-blue", TEAM_LEADER: "badge-amber", TRAINER: "badge-gray" };

/** Wie oft die Glocke im Hintergrund neue Benachrichtigungen holt (ms). */
const NOTIFICATION_POLL_MS = 60000;

/* ------------------------------------------------------------------ */
/* Allgemeine Hilfsfunktionen                                         */
/* ------------------------------------------------------------------ */

/**
 * Wandelt einen beliebigen Wert in HTML-sicheren Text um.
 *
 * WARUM: Werte aus der API (z. B. eine Ablehnungsbegründung eines
 * Trainers) könnten HTML/JavaScript enthalten. Ohne Escaping würde
 * `innerHTML` diesen Code ausführen (Stored XSS). Die Seiten bauen ihr
 * DOM inzwischen mit ui.js::h() – escapeHtml bleibt für Sonderfälle.
 *
 * @param {*} value - Beliebiger Wert (String, Zahl, null, undefined ...)
 * @returns {string} Escapeter Text, null/undefined werden zu "".
 */
function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
        .replace(/&/g, "&amp;")   // & zuerst, sonst würden wir unsere eigenen Entities doppelt escapen
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/**
 * Liest ein Cookie anhand seines Namens.
 * Wird für die CSRF-Cookies (csrf_access_token / csrf_refresh_token)
 * benötigt – die JWT-Cookies selbst sind HttpOnly und hier unsichtbar.
 *
 * @param {string} name - Name des Cookies.
 * @returns {string|null} Wert des Cookies oder null, wenn nicht vorhanden.
 */
function getCookie(name) {
    const prefix = `${name}=`;
    for (const part of document.cookie.split(";")) {
        const cookie = part.trim();
        if (cookie.startsWith(prefix)) {
            return decodeURIComponent(cookie.substring(prefix.length));
        }
    }
    return null;
}

/**
 * Prüft, ob die aktuelle Seite öffentlich ist (Login / Passwort-Reset).
 * @returns {boolean}
 */
function isPublicPage() {
    return PUBLIC_PATHS.includes(window.location.pathname);
}

/**
 * Leitet auf die Login-Seite um – außer man befindet sich bereits auf
 * einer öffentlichen Seite (sonst entstünde eine Redirect-Schleife).
 */
function redirectToLogin() {
    if (!isPublicPage()) window.location.href = "/login";
}

/**
 * Prüft, ob eine URL eine echte http(s)-Adresse ist.
 * WARUM: Ein Meeting-Link wie "javascript:alert(1)" würde beim Klick
 * Code ausführen. Deshalb werden nur http: und https: zugelassen.
 *
 * @param {string} url - Zu prüfende URL.
 * @returns {boolean}
 */
function isSafeHttpUrl(url) {
    if (!url) return false;
    try {
        const parsed = new URL(url, window.location.origin);
        return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch (e) {
        return false;
    }
}

/**
 * Prüft eine Farbe auf das Format #RRGGBB.
 * WARUM: Farben landen im CSSOM (element.style); ein manipulierter Wert
 * soll gar nicht erst verwendet werden.
 *
 * @param {string} color
 * @returns {boolean}
 */
function isValidHexColor(color) {
    return typeof color === "string" && HEX_COLOR_RE.test(color);
}

/**
 * Lesbare Rollenbezeichnung ("TEAM_LEADER" → "Teamleitung").
 * @param {string} role
 * @returns {string}
 */
function roleLabel(role) {
    return ROLE_LABELS[role] || String(role || "");
}

/**
 * CSS-Klasse für das Rollen-Badge.
 * @param {string} role
 * @returns {string}
 */
function roleBadgeClass(role) {
    return ROLE_BADGES[role] || "badge-gray";
}

/* ------------------------------------------------------------------ */
/* Zentraler API-Zugriff                                              */
/* ------------------------------------------------------------------ */

/**
 * Laufender Refresh-Vorgang. Wenn mehrere Requests gleichzeitig ein 401
 * bekommen, soll nur EIN Refresh an den Server gehen – alle anderen
 * warten auf dasselbe Promise.
 * @type {Promise<boolean>|null}
 */
let refreshPromise = null;

/**
 * Holt über das Refresh-Cookie ein neues Access-Token.
 * Spricht mit: POST /api/v1/auth/refresh
 * Der Server erwartet dabei den Wert von csrf_refresh_token im Header.
 *
 * @returns {Promise<boolean>} true, wenn der Refresh erfolgreich war.
 */
function refreshAccessToken() {
    if (!refreshPromise) {
        const headers = {};
        const csrf = getCookie("csrf_refresh_token");
        if (csrf) headers["X-CSRF-TOKEN"] = csrf;

        refreshPromise = fetch("/api/v1/auth/refresh", {
            method: "POST",
            credentials: "same-origin",
            headers,
        })
            .then(res => res.ok)
            .catch(() => false)
            .finally(() => {
                // Nach Abschluss wieder freigeben, damit ein späterer 401 erneut refreshen darf.
                refreshPromise = null;
            });
    }
    return refreshPromise;
}

/**
 * Zentraler Wrapper um fetch() für ALLE Aufrufe an unser Backend.
 *
 * Was er automatisch erledigt:
 *   - `credentials: "same-origin"` → Browser schickt die JWT-Cookies mit.
 *   - Bei POST/PUT/PATCH/DELETE: Header "X-CSRF-TOKEN" aus dem Cookie
 *     csrf_access_token (Double-Submit-Schutz gegen CSRF-Angriffe).
 *   - Ist `options.body` ein normales Objekt, wird es als JSON gesendet
 *     (inkl. Content-Type). FormData (CSV-Upload) bleibt unverändert.
 *   - Bei 401: einmalig Refresh versuchen und den Request wiederholen;
 *     schlägt das fehl → Umleitung auf /login.
 *
 * @param {string} url - Relativer API-Pfad, z. B. "/api/v1/events".
 * @param {object} [options={}] - Normale fetch-Optionen.
 * @param {boolean} [isRetry=false] - Intern: verhindert Endlos-Wiederholungen.
 * @returns {Promise<Response>} Die fetch-Response (Aufrufer prüft res.ok).
 */
async function apiFetch(url, options = {}, isRetry = false) {
    const method = (options.method || "GET").toUpperCase();
    const headers = { ...(options.headers || {}) };
    let body = options.body;

    // Normale Objekte → JSON. FormData/Blob/String werden unverändert durchgereicht.
    const isPlainObject = body !== null && typeof body === "object"
        && !(body instanceof FormData) && !(body instanceof Blob);
    if (isPlainObject) {
        body = JSON.stringify(body);
        headers["Content-Type"] = "application/json";
    }

    // CSRF-Schutz nur für verändernde Methoden (GET ist per Definition "sicher").
    if (UNSAFE_METHODS.includes(method)) {
        const csrf = getCookie("csrf_access_token");
        if (csrf) headers["X-CSRF-TOKEN"] = csrf;
    }

    const response = await fetch(url, { ...options, method, headers, body, credentials: "same-origin" });

    // 401 = Access-Token abgelaufen oder fehlt → einmal still erneuern.
    const path = url.split("?")[0];
    if (response.status === 401 && !isRetry && !NO_REFRESH_ENDPOINTS.includes(path)) {
        const refreshed = await refreshAccessToken();
        if (refreshed) return apiFetch(url, options, true);
        redirectToLogin();
    } else if (response.status === 401 && isRetry) {
        // Auch nach dem Refresh nicht berechtigt → Sitzung ist wirklich vorbei.
        redirectToLogin();
    }
    return response;
}

/**
 * Liest die JSON-Antwort sicher aus. Liefert {} bei leerem oder
 * fehlerhaftem Body (z. B. HTML-Fehlerseite eines Proxys).
 *
 * @param {Response} response
 * @returns {Promise<object>}
 */
async function readJson(response) {
    try {
        return await response.json();
    } catch (e) {
        return {};
    }
}

/* ------------------------------------------------------------------ */
/* Eingeloggter Benutzer                                              */
/* ------------------------------------------------------------------ */

/** Zwischengespeichertes Promise für /api/v1/auth/me (nur ein Request pro Seite). */
let currentUserCache = null;

/**
 * Lädt die Daten des eingeloggten Benutzers genau einmal pro Seitenaufruf.
 * Spricht mit: GET /api/v1/auth/me
 *
 * @returns {Promise<object|null>} Benutzerobjekt {id, email, first_name,
 *          last_name, role, team_id} oder null, wenn nicht eingeloggt.
 */
function getCurrentUser() {
    if (!currentUserCache) {
        currentUserCache = apiFetch("/api/v1/auth/me")
            .then(async res => (res.ok ? readJson(res) : null))
            .catch(() => null);
    }
    return currentUserCache;
}

// Auf geschützten Seiten sofort starten, damit das Promise schon existiert,
// wenn die Seiten-Skripte (die NACH dieser Datei laufen) es brauchen.
window.currentUserPromise = isPublicPage() ? Promise.resolve(null) : getCurrentUser();

/* ------------------------------------------------------------------ */
/* Datum/Zeit-Helfer                                                  */
/* ------------------------------------------------------------------ */

/**
 * Formatiert ein Date-Objekt für ein <input type="datetime-local">
 * (lokale Uhrzeit des Browsers, Format YYYY-MM-DDTHH:MM).
 *
 * @param {Date|null} dateObj
 * @returns {string}
 */
function toDatetimeLocal(dateObj) {
    if (!dateObj) return "";
    const pad = n => (n < 10 ? "0" + n : String(n));
    return dateObj.getFullYear() + "-" + pad(dateObj.getMonth() + 1) + "-" + pad(dateObj.getDate())
        + "T" + pad(dateObj.getHours()) + ":" + pad(dateObj.getMinutes());
}

/**
 * Formatiert ein Date-Objekt für ein <input type="date"> (YYYY-MM-DD, lokal).
 * @param {Date|null} dateObj
 * @returns {string}
 */
function toDateLocal(dateObj) {
    return toDatetimeLocal(dateObj).substring(0, 10);
}

/**
 * Wandelt einen Eingabewert aus dem Termin-Formular in einen UTC-ISO-String.
 *
 * WARUM: Das Formular liefert lokale Uhrzeit ("Wanduhrzeit" in Deutschland).
 * Das Backend speichert alles in UTC. `new Date("YYYY-MM-DDTHH:MM")`
 * interpretiert den Wert als lokale Zeit, `toISOString()` rechnet nach UTC um.
 *
 * Unterstützt:
 *   - "YYYY-MM-DDTHH:MM"   (datetime-local)
 *   - "YYYY-MM-DD"         (date, bei ganztägigen Terminen)
 *   - "TT.MM.JJJJ HH:MM"   (Fallback für Browser ohne Datums-Picker)
 *
 * @param {string} value - Rohwert aus dem Input.
 * @param {boolean} isEnd - true für das Endfeld (ganztägig → 23:59:59).
 * @returns {string|null} ISO-String in UTC oder null bei ungültiger Eingabe.
 */
function toUtcIso(value, isEnd) {
    if (!value) return null;
    let normalized = value.trim();

    // Deutsches Format "TT.MM.JJJJ HH:MM" → ISO-ähnlich umbauen.
    if (normalized.includes(".")) {
        const [datePart, timePart] = normalized.split(" ");
        const [d, m, y] = datePart.split(".");
        normalized = `${y}-${m}-${d}` + (timePart ? `T${timePart}` : "");
    }

    // Nur Datum (ganztägig) → Beginn bzw. Ende des lokalen Tages.
    if (normalized.length === 10) {
        normalized += isEnd ? "T23:59:59" : "T00:00:00";
    }

    const date = new Date(normalized); // ohne Offset → wird als LOKALE Zeit gelesen
    return isNaN(date.getTime()) ? null : date.toISOString();
}

/* ------------------------------------------------------------------ */
/* Kopfzeile: Navigation, Benutzermenü, mobiles Menü                  */
/* ------------------------------------------------------------------ */

/**
 * Blendet die Navigationspunkte (Desktop + mobil) je nach Rolle ein.
 * Jeder rollenabhängige Link trägt data-roles="CEO ADMIN ..." (base.html).
 * HINWEIS: Das ist nur Komfort für die Oberfläche – die echte
 * Zugriffskontrolle macht das Backend bei jedem API-Aufruf.
 *
 * @param {object} user - Benutzer aus /api/v1/auth/me.
 */
function applyRoleNavigation(user) {
    document.querySelectorAll("[data-roles]").forEach(el => {
        el.hidden = !el.dataset.roles.split(" ").includes(user.role);
    });
}

/**
 * Füllt Benutzermenü und Avatar mit den Daten des eingeloggten Benutzers.
 * Alle Werte per textContent → auch ein präparierter Name bleibt reiner Text.
 *
 * @param {object} user
 */
function renderUserMenu(user) {
    const fullName = `${user.first_name || ""} ${user.last_name || ""}`.trim();
    const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    set("user-name", fullName);
    set("user-role", roleLabel(user.role));
    set("user-avatar", initials(user.first_name, user.last_name));
    set("user-menu-name", fullName);
    set("user-menu-email", user.email || "");
    const badge = document.getElementById("user-menu-role");
    if (badge) {
        badge.textContent = roleLabel(user.role);
        badge.className = `badge ${roleBadgeClass(user.role)} mt-2`;
    }
}

/**
 * Mobiles Menü (Hamburger-Button) auf- und zuklappen.
 */
function setupMobileMenu() {
    const btn = document.getElementById("mobile-menu-btn");
    const nav = document.getElementById("mobile-nav");
    if (!btn || !nav) return;
    btn.addEventListener("click", () => {
        const open = nav.hidden;
        nav.hidden = !open;
        btn.setAttribute("aria-expanded", String(open));
        btn.setAttribute("aria-label", open ? "Menü schließen" : "Menü öffnen");
    });
}

/**
 * Abmelden. Spricht mit: POST /api/v1/auth/logout → Server löscht die Cookies.
 */
function setupLogout() {
    document.getElementById("logout-btn")?.addEventListener("click", async () => {
        try {
            await apiFetch("/api/v1/auth/logout", { method: "POST" });
        } finally {
            // Auch wenn der Server nicht antwortet: zurück zum Login.
            window.location.href = "/login";
        }
    });
}

/* ------------------------------------------------------------------ */
/* Benachrichtigungen                                                 */
/* ------------------------------------------------------------------ */

/** Zuletzt geladene Benachrichtigungen (für "Alle gelesen"). */
let currentNotifications = [];

/**
 * Lädt die Benachrichtigungen und rendert sie ins Glocken-Dropdown.
 * Spricht mit: GET /api/v1/notifications
 *
 * SICHERHEIT: Titel und Nachricht enthalten Benutzertext (z. B. die
 * Ablehnungsbegründung eines Trainers). h() setzt sie als Textknoten –
 * niemals als HTML.
 */
async function loadNotifications() {
    try {
        const res = await apiFetch("/api/v1/notifications");
        if (!res.ok) return;
        const data = await readJson(res);
        currentNotifications = Array.isArray(data.notifications) ? data.notifications : [];
        renderNotifications();
    } catch (err) { console.error(err); }
}

/**
 * Zeichnet Zähler und Liste der Benachrichtigungen neu.
 */
function renderNotifications() {
    const badge = document.getElementById("notif-badge");
    const list = document.getElementById("notif-list");
    const markAll = document.getElementById("notif-mark-all");
    const bell = document.getElementById("notification-bell");
    if (!badge || !list) return;

    const unread = currentNotifications.filter(n => !n.is_read).length;
    badge.textContent = unread > 99 ? "99+" : String(unread);
    badge.hidden = unread === 0;
    if (markAll) markAll.hidden = unread === 0;
    // Screenreader erfahren die Anzahl über das Label des Buttons.
    bell?.setAttribute("aria-label", unread ? `Benachrichtigungen, ${unread} ungelesen` : "Benachrichtigungen");

    if (currentNotifications.length === 0) {
        list.replaceChildren(h("div", { class: "empty-state py-10" },
            h("div", { class: "empty-state-icon" }, icon("inbox")),
            h("p", { class: "text-sm font-medium", text: "Alles erledigt" }),
            h("p", { class: "text-xs text-fg-muted", text: "Keine Benachrichtigungen vorhanden." }),
        ));
        return;
    }

    list.replaceChildren(...currentNotifications.map(n => h("button", {
        type: "button",
        class: `flex w-full cursor-pointer gap-3 border-b border-line px-4 py-3 text-left last:border-b-0 transition-colors hover:bg-surface-2 ${n.is_read ? "" : "bg-accent-soft/40"}`,
        // Handler direkt am Element – kein Inline-onclick, keine Daten im DOM-Attribut.
        on: { click: () => markRead(n.id) },
    },
        h("span", {
            class: `mt-1.5 size-2 shrink-0 rounded-full ${n.is_read ? "bg-transparent" : "bg-accent"}`,
            "aria-hidden": "true",
        }),
        h("span", { class: "min-w-0 flex-1" },
            h("span", { class: `block text-sm ${n.is_read ? "font-medium text-fg-muted" : "font-semibold text-fg"}`, text: n.title }),
            h("span", { class: "mt-0.5 block text-xs leading-relaxed break-words text-fg-muted", text: n.message }),
            h("span", { class: "mt-1 block text-[0.6875rem] text-fg-subtle", text: formatRelativeTime(n.created_at) }),
        ),
        n.is_read ? null : h("span", { class: "sr-only", text: "(ungelesen)" }),
    )));
}

/**
 * Markiert eine Benachrichtigung als gelesen und lädt die Liste neu.
 * Spricht mit: PUT /api/v1/notifications/<id>/read
 *
 * @param {number} id - ID der Benachrichtigung.
 */
async function markRead(id) {
    await apiFetch(`/api/v1/notifications/${encodeURIComponent(id)}/read`, { method: "PUT" });
    loadNotifications();
}

/**
 * Markiert alle ungelesenen Benachrichtigungen als gelesen.
 * Die API kennt nur Einzel-Aufrufe → parallel für jede ungelesene ID.
 */
async function markAllRead() {
    const unread = currentNotifications.filter(n => !n.is_read);
    await Promise.all(unread.map(n =>
        apiFetch(`/api/v1/notifications/${encodeURIComponent(n.id)}/read`, { method: "PUT" })));
    loadNotifications();
}

/**
 * Glocke verdrahten: Dropdown, "Alle gelesen" und Aktualisierung im
 * Hintergrund (nur solange der Tab sichtbar ist – spart Anfragen).
 */
function setupNotifications() {
    setupPopover(document.getElementById("notification-bell"), document.getElementById("notif-dropdown"));
    document.getElementById("notif-mark-all")?.addEventListener("click", markAllRead);
    loadNotifications();
    setInterval(() => {
        if (document.visibilityState === "visible") loadNotifications();
    }, NOTIFICATION_POLL_MS);
}

/* ------------------------------------------------------------------ */
/* Seitenstart                                                        */
/* ------------------------------------------------------------------ */

/**
 * Einstiegspunkt nach dem Laden des DOM.
 * - Login-Seite: Ist man schon angemeldet → direkt zum Kalender.
 * - Geschützte Seiten: Benutzer laden, Kopfzeile befüllen, Navigation
 *   nach Rolle filtern. Die eigentliche Seitenlogik steckt in js/pages/.
 */
document.addEventListener("DOMContentLoaded", async () => {
    if (window.location.pathname === "/login") {
        // Ohne lesbares CSRF-Cookie gibt es sicher keine Sitzung → gar nicht erst
        // fragen (spart eine Anfrage und einen roten 401-Eintrag in der Konsole).
        if (!getCookie("csrf_access_token") && !getCookie("csrf_refresh_token")) return;
        // Normales fetch (nicht apiFetch), damit ein 401 hier keinen Refresh/Redirect auslöst.
        try {
            const res = await fetch("/api/v1/auth/me", { credentials: "same-origin" });
            if (res.ok) window.location.href = "/dashboard";
        } catch (e) { /* offline → einfach auf der Login-Seite bleiben */ }
        return;
    }
    if (isPublicPage()) return;

    setupMobileMenu();
    setupLogout();
    setupPopover(document.getElementById("user-menu-btn"), document.getElementById("user-menu"));

    const user = await window.currentUserPromise;
    if (!user) { redirectToLogin(); return; }

    renderUserMenu(user);
    applyRoleNavigation(user);
    document.getElementById("user-info").hidden = false;
    setupNotifications();
});
