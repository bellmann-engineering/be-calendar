/**
 * =====================================================================
 * Datei: app/static/js/app.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Zentrales Frontend-Skript des Bellmann Calendar. Es wird von
 *   base.html auf JEDER Seite geladen (vor den seitenspezifischen
 *   Skripten im Block {% block scripts %}).
 *
 * Was diese Datei bereitstellt:
 *   1. Globale Hilfsfunktionen, die auch die Seiten-Skripte nutzen:
 *        - escapeHtml()      → Schutz vor XSS beim Einfügen in innerHTML
 *        - getCookie()       → liest die CSRF-Cookies des Servers
 *        - apiFetch()        → zentraler Wrapper um fetch() inkl. Cookies,
 *                              CSRF-Header, JSON und automatischem
 *                              Token-Refresh bei 401
 *        - getCurrentUser()  → lädt den eingeloggten Benutzer genau einmal
 *                              (window.currentUserPromise)
 *        - isSafeHttpUrl(), isValidHexColor(), toDatetimeLocal(), toUtcIso()
 *   2. Die Logik des Dashboards (FullCalendar, Termin-Modal, RSVP,
 *      Neu-Zuweisung, Benachrichtigungen).
 *   3. Login- und Logout-Verhalten.
 *
 * Mit welchen Backend-Endpunkten spricht diese Datei?
 *   POST /api/v1/auth/login         → Anmeldung (Server setzt Cookies)
 *   POST /api/v1/auth/refresh       → neues Access-Token per Refresh-Cookie
 *   POST /api/v1/auth/logout        → Cookies löschen
 *   GET  /api/v1/auth/me            → Daten des eingeloggten Benutzers
 *   GET  /api/v1/auth/trainers      → Mitarbeiterliste für Zuweisungen
 *   GET  /api/v1/customers          → Kundenliste (Farben im Kalender)
 *   GET  /api/v1/notifications      → In-App-Benachrichtigungen
 *   PUT  /api/v1/notifications/<id>/read
 *   GET/POST/PUT/DELETE /api/v1/events[/<id>]
 *   PUT  /api/v1/events/<id>/rsvp   → Zusage/Absage eines Trainers
 *
 * Wovon hängt diese Datei ab?
 *   - FullCalendar (global "FullCalendar", per CDN in base.html geladen)
 *   - Die HTML-Elemente aus base.html und dashboard.html (IDs wie
 *     "calendar-container", "event-modal", "notif-list" ...)
 *   - Cookies, die das Flask-Backend (flask-jwt-extended) setzt:
 *       access_token_cookie  (HttpOnly → für JS unsichtbar, gut so!)
 *       refresh_token_cookie (HttpOnly)
 *       csrf_access_token    (für JS lesbar → X-CSRF-TOKEN Header)
 *       csrf_refresh_token   (für JS lesbar → beim Refresh)
 *
 * Sicherheitsprinzip:
 *   Das JWT liegt NICHT mehr im localStorage, sondern in einem
 *   HttpOnly-Cookie. Selbst wenn ein Angreifer JavaScript einschleusen
 *   könnte, kann er das Token nicht auslesen. Zusätzlich wird jeder
 *   Datenwert aus der API vor dem Einfügen in HTML escaped.
 * =====================================================================
 */

/* ------------------------------------------------------------------ */
/* Globale Zustände                                                   */
/* ------------------------------------------------------------------ */

/** Referenz auf die FullCalendar-Instanz des Dashboards (für refetchEvents). */
let globalCalendar = null;

/**
 * Rolle des eingeloggten Benutzers (CEO, ADMIN, TEAM_LEADER, TRAINER).
 * Bleibt aus Kompatibilitätsgründen global erhalten; zuverlässiger ist
 * aber `await getCurrentUser()`, weil die Rolle asynchron geladen wird.
 */
let currentUserRole = null;

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

/** Standardfarbe für Termine ohne (gültige) Kundenfarbe. */
const DEFAULT_EVENT_COLOR = "#2B6CB0";

/* ------------------------------------------------------------------ */
/* Allgemeine Hilfsfunktionen (werden auch von den Seiten genutzt)    */
/* ------------------------------------------------------------------ */

/**
 * Wandelt einen beliebigen Wert in HTML-sicheren Text um.
 *
 * WARUM: Werte aus der API (z. B. eine Ablehnungsbegründung eines
 * Trainers) könnten HTML/JavaScript enthalten. Ohne Escaping würde
 * `innerHTML` diesen Code ausführen (Stored XSS).
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
 * WARUM: Farben landen in style-Attributen; ein manipulierter Wert
 * könnte sonst CSS/HTML einschleusen.
 *
 * @param {string} color
 * @returns {boolean}
 */
function isValidHexColor(color) {
    return typeof color === "string" && HEX_COLOR_RE.test(color);
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
 * Seiten-Skripte (z. B. members.html) nutzen `await getCurrentUser()`,
 * statt sich auf die globale Variable currentUserRole zu verlassen,
 * die zum Zeitpunkt ihres Aufrufs eventuell noch leer ist.
 *
 * @returns {Promise<object|null>} Benutzerobjekt {id, email, first_name,
 *          last_name, role, team_id} oder null, wenn nicht eingeloggt.
 */
function getCurrentUser() {
    if (!currentUserCache) {
        currentUserCache = apiFetch("/api/v1/auth/me")
            .then(async res => (res.ok ? readJson(res) : null))
            .then(user => {
                if (user) currentUserRole = user.role; // Kompatibilität für ältere Stellen
                return user;
            })
            .catch(() => null);
    }
    return currentUserCache;
}

// Auf geschützten Seiten sofort starten, damit das Promise schon existiert,
// wenn die Seiten-Skripte (die NACH dieser Datei geladen werden) es brauchen.
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
/* Seitenstart                                                        */
/* ------------------------------------------------------------------ */

/**
 * Einstiegspunkt nach dem Laden des DOM.
 * - Öffentliche Seiten: nur Login-/Logout-Handler.
 * - Geschützte Seiten: Benutzer laden, Navigation nach Rolle filtern,
 *   Dashboard-Komponenten initialisieren.
 */
document.addEventListener("DOMContentLoaded", async () => {
    setupAuth();

    if (window.location.pathname === "/login") {
        // Bereits eingeloggt? Dann direkt ins Dashboard (normales fetch,
        // damit ein 401 hier keinen Redirect/Refresh auslöst).
        try {
            const res = await fetch("/api/v1/auth/me", { credentials: "same-origin" });
            if (res.ok) window.location.href = "/dashboard";
        } catch (e) { /* offline → einfach auf der Login-Seite bleiben */ }
        return;
    }
    if (isPublicPage()) return;

    const user = await window.currentUserPromise;
    if (!user) { redirectToLogin(); return; }

    document.getElementById("user-info")?.classList.remove("hidden");
    document.getElementById("dashboard-content")?.classList.remove("hidden");

    applyRoleNavigation(user);

    const userNameEl = document.getElementById("user-name");
    if (userNameEl) userNameEl.textContent = `${user.first_name} ${user.last_name} (${user.role})`;

    if (["CEO", "ADMIN", "TEAM_LEADER"].includes(user.role)) {
        document.getElementById("open-modal-btn")?.classList.remove("hidden");
        loadTrainers();
        loadCustomers();
        loadNotifications();
        document.getElementById("notification-bell")?.addEventListener("click", (e) => {
            // Klicks auf einen Eintrag in der Liste sollen das Dropdown nicht schließen.
            if (e.target.closest("#notif-list")) return;
            document.getElementById("notif-dropdown")?.classList.toggle("hidden");
        });
    } else {
        document.getElementById("notification-bell")?.classList.add("hidden");
    }

    const calendarContainer = document.getElementById("calendar-container");
    if (calendarContainer) renderCalendar(calendarContainer);

    setupEventCreation();
    setupRSVPModals();
    setupAllDayToggle();
});

/**
 * Blendet die Navigations-Tabs abhängig von der Rolle ein/aus.
 * HINWEIS: Das ist nur Komfort für die Oberfläche – die echte
 * Zugriffskontrolle macht das Backend bei jedem API-Aufruf.
 *
 * @param {object} user - Benutzer aus /api/v1/auth/me.
 */
function applyRoleNavigation(user) {
    const allowedTabs = {
        "nav-compare": ["CEO", "ADMIN", "TEAM_LEADER"],
        "nav-logs": ["CEO", "ADMIN"],
        "nav-members": ["CEO", "ADMIN"],
        "nav-customers": ["CEO", "ADMIN"],
    };
    for (const [tabId, roles] of Object.entries(allowedTabs)) {
        const el = document.getElementById(tabId);
        if (el) el.classList.toggle("hidden", !roles.includes(user.role));
    }
}

/**
 * Schaltet die Datumsfelder des Termin-Formulars zwischen
 * "datetime-local" und "date" um, wenn "Ganztägig" angehakt wird.
 */
function setupAllDayToggle() {
    const cb = document.getElementById("event-is-all-day");
    if (!cb) return;
    cb.addEventListener("change", (e) => setAllDayInputs(e.target.checked));
}

/**
 * Setzt den Typ der Start/Ende-Felder.
 * @param {boolean} isAllDay
 */
function setAllDayInputs(isAllDay) {
    const type = isAllDay ? "date" : "datetime-local";
    const start = document.getElementById("event-start");
    const end = document.getElementById("event-end");
    if (start) start.type = type;
    if (end) end.type = type;
}

/* ------------------------------------------------------------------ */
/* Dropdown-Daten (Mitarbeiter, Kunden)                               */
/* ------------------------------------------------------------------ */

/**
 * Füllt die Mitarbeiter-Auswahlfelder (Termin anlegen + Neu-Zuweisung).
 * Spricht mit: GET /api/v1/auth/trainers → [{id, name}]
 * createElement + textContent statt innerHTML → kein XSS möglich.
 */
async function loadTrainers() {
    try {
        const res = await apiFetch("/api/v1/auth/trainers");
        if (!res.ok) return;
        const data = await readJson(res);
        const selects = [document.getElementById("event-assignee"), document.getElementById("reassign-select")];
        (Array.isArray(data) ? data : []).forEach(t => {
            selects.forEach(select => {
                if (!select) return;
                const opt = document.createElement("option");
                opt.value = t.id;
                opt.textContent = t.name;
                select.appendChild(opt);
            });
        });
    } catch (err) { console.error(err); }
}

/**
 * Füllt die Kunden-Auswahl im Termin-Formular.
 * Spricht mit: GET /api/v1/customers → [{id, name, email, color_hex}]
 */
async function loadCustomers() {
    try {
        const res = await apiFetch("/api/v1/customers");
        if (!res.ok) return;
        const data = await readJson(res);
        const select = document.getElementById("event-customer");
        if (!select) return;
        (Array.isArray(data) ? data : []).forEach(c => {
            const opt = document.createElement("option");
            opt.value = c.id;
            opt.textContent = c.name;
            select.appendChild(opt);
        });
    } catch (err) { console.error(err); }
}

/* ------------------------------------------------------------------ */
/* Benachrichtigungen                                                 */
/* ------------------------------------------------------------------ */

/**
 * Lädt die Benachrichtigungen und rendert sie ins Glocken-Dropdown.
 * Spricht mit: GET /api/v1/notifications
 *
 * SICHERHEIT: Titel und Nachricht enthalten Benutzertext (z. B. die
 * Ablehnungsbegründung eines Trainers). Deshalb werden sie per
 * textContent gesetzt – niemals per innerHTML.
 */
async function loadNotifications() {
    try {
        const res = await apiFetch("/api/v1/notifications");
        if (!res.ok) return;
        const data = await readJson(res);
        const notifications = Array.isArray(data.notifications) ? data.notifications : [];
        const unread = notifications.filter(n => !n.is_read);
        const badge = document.getElementById("notif-badge");
        const list = document.getElementById("notif-list");
        if (!badge || !list) return;

        badge.textContent = String(unread.length);
        badge.classList.toggle("hidden", unread.length === 0);

        list.replaceChildren(); // alte Einträge entfernen
        if (notifications.length === 0) {
            const empty = document.createElement("div");
            empty.className = "px-4 py-3 text-sm text-gray-500";
            empty.textContent = "Keine Benachrichtigungen.";
            list.appendChild(empty);
            return;
        }

        notifications.forEach(n => {
            const item = document.createElement("div");
            item.className = `px-4 py-3 border-b hover:bg-gray-50 ${n.is_read ? "opacity-50" : "bg-blue-50"} cursor-pointer`;

            const title = document.createElement("p");
            title.className = "text-sm font-bold text-[#1A365D]";
            title.textContent = n.title;

            const message = document.createElement("p");
            message.className = "text-xs text-gray-700 mt-1";
            message.textContent = n.message;

            item.append(title, message);
            // Handler direkt am Element – kein Inline-onclick, kein Token im DOM.
            item.addEventListener("click", () => markRead(n.id));
            list.appendChild(item);
        });
    } catch (err) { console.error(err); }
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
window.markRead = markRead;

/* ------------------------------------------------------------------ */
/* Kalender (FullCalendar)                                            */
/* ------------------------------------------------------------------ */

/**
 * Erstellt den Wochenkalender im Dashboard.
 * Abhängigkeit: FullCalendar (global, CDN aus base.html).
 * Spricht mit: GET /api/v1/events?start=...&end=...
 *
 * FullCalendar ruft `events` bei jedem Ansichtswechsel mit dem sichtbaren
 * Zeitraum auf. Wir geben ihn an den Server weiter, damit nur die
 * benötigten Termine geladen werden. Die Zeiten kommen als ISO-String
 * MIT Offset (+00:00) – FullCalendar rechnet sie in Lokalzeit um.
 *
 * @param {HTMLElement} container - Element, in das der Kalender gezeichnet wird.
 */
function renderCalendar(container) {
    container.replaceChildren();
    globalCalendar = new FullCalendar.Calendar(container, {
        initialView: "timeGridWeek",
        headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,timeGridDay" },
        locale: "de",
        allDaySlot: false,
        slotMinTime: "06:00:00",
        slotMaxTime: "22:00:00",
        events: async function (fetchInfo, successCallback, failureCallback) {
            try {
                // encodeURIComponent ist nötig, weil startStr ein "+" enthält
                // (z. B. +02:00), das in einer URL sonst als Leerzeichen gilt.
                const url = `/api/v1/events?start=${encodeURIComponent(fetchInfo.startStr)}&end=${encodeURIComponent(fetchInfo.endStr)}`;
                const response = await apiFetch(url);
                if (!response.ok) throw new Error("Fehler beim Laden");
                const data = await readJson(response);
                successCallback((Array.isArray(data) ? data : []).map(e => ({
                    id: e.id,
                    title: e.title, // FullCalendar setzt Titel als Text → sicher
                    start: e.start_time,
                    end: e.end_time,
                    backgroundColor: e.reallocation_required
                        ? "#E53E3E"
                        : (isValidHexColor(e.color) ? e.color : DEFAULT_EVENT_COLOR),
                    extendedProps: {
                        reallocation_required: e.reallocation_required,
                        assigned_to_id: e.assigned_to_id,
                        meeting_link: e.meeting_link,
                        customer_id: e.customer_id,
                        is_all_day: e.is_all_day,
                        is_mandatory: e.is_mandatory,
                        rejection_reason: e.rejection_reason,
                    },
                })));
            } catch (error) { failureCallback(error); }
        },
        eventClick: info => openEventDetails(info.event),
    });
    globalCalendar.render();
}

/**
 * Öffnet das Detail-Modal eines Termins und zeigt – je nach Rolle –
 * RSVP-Buttons (Trainer), Neu-Zuweisung und Verwaltung (CEO/ADMIN/TL).
 *
 * @param {object} event - FullCalendar-EventApi-Objekt.
 */
function openEventDetails(event) {
    const eventId = event.id;
    const props = event.extendedProps;

    // Alle Texte per textContent → auch bösartige Titel werden nur angezeigt.
    document.getElementById("detail-title").textContent = event.title;
    document.getElementById("detail-time").textContent =
        `${event.start.toLocaleString("de-DE")} - ${event.end ? event.end.toLocaleString("de-DE") : ""}`;

    // Meeting-Link nur anzeigen, wenn es wirklich eine http(s)-URL ist.
    const link = document.getElementById("detail-link");
    if (link) {
        if (isSafeHttpUrl(props.meeting_link)) {
            link.href = props.meeting_link;
            link.rel = "noopener noreferrer"; // verhindert Zugriff der Zielseite auf window.opener
            link.classList.remove("hidden");
        } else {
            link.removeAttribute("href");
            link.classList.add("hidden");
        }
    }

    const rsvpSection = document.getElementById("rsvp-section");
    const reassignSection = document.getElementById("reassign-section");
    const adminActions = document.getElementById("admin-actions");
    rsvpSection?.classList.add("hidden");
    reassignSection?.classList.add("hidden");
    adminActions?.classList.add("hidden");
    document.getElementById("rsvp-error")?.classList.add("hidden");
    document.getElementById("decline-container")?.classList.add("hidden");
    const declineReason = document.getElementById("decline-reason");
    if (declineReason) declineReason.value = "";

    if (currentUserRole === "TRAINER") {
        // Pflichttermine können nicht abgelehnt werden → keine RSVP-Buttons.
        if (!props.is_mandatory && rsvpSection) {
            rsvpSection.classList.remove("hidden");
            // .onclick statt addEventListener: überschreibt den Handler des
            // zuvor geöffneten Termins, statt Handler zu stapeln.
            document.getElementById("btn-accept").onclick = () => submitRsvp(eventId, "ACCEPTED", null);
            document.getElementById("btn-submit-decline").onclick = () => {
                const reason = document.getElementById("decline-reason").value.trim();
                if (!reason) { showRsvpError("Bitte gib eine Begründung an."); return; }
                submitRsvp(eventId, "DECLINED", reason);
            };
        }
    } else if (["CEO", "ADMIN", "TEAM_LEADER"].includes(currentUserRole)) {
        if (props.reallocation_required && reassignSection) {
            reassignSection.classList.remove("hidden");
            const reasonEl = document.getElementById("detail-rejection-reason");
            if (reasonEl) {
                if (props.rejection_reason) {
                    reasonEl.textContent = "Ablehnungsgrund: " + props.rejection_reason;
                    reasonEl.classList.remove("hidden");
                } else {
                    reasonEl.classList.add("hidden");
                }
            }
            document.getElementById("btn-reassign").onclick = () => {
                const newAssignee = document.getElementById("reassign-select").value;
                if (newAssignee) reassignEvent(eventId, newAssignee);
            };
        }
        if (adminActions) {
            adminActions.classList.remove("hidden");
            document.getElementById("btn-delete").onclick = () => deleteEvent(eventId);
            document.getElementById("btn-edit").onclick = () => openEditForm(event);
        }
    }
    document.getElementById("event-details-modal").classList.remove("hidden");
}

/**
 * Zeigt eine Fehlermeldung im RSVP-Bereich an.
 * @param {string} message
 */
function showRsvpError(message) {
    const el = document.getElementById("rsvp-error");
    if (!el) return;
    el.textContent = message;
    el.classList.remove("hidden");
}

/**
 * Schließt das Detail-Modal und lädt die Kalendertermine neu.
 */
function closeDetailsAndRefresh() {
    document.getElementById("event-details-modal").classList.add("hidden");
    if (globalCalendar) globalCalendar.refetchEvents();
}

/**
 * Löscht einen Termin nach Rückfrage (Soft-Delete im Backend).
 * Spricht mit: DELETE /api/v1/events/<id>
 *
 * @param {string|number} eventId
 */
async function deleteEvent(eventId) {
    if (!confirm("Bist du sicher, dass du diesen Termin löschen möchtest?")) return;
    const res = await apiFetch(`/api/v1/events/${encodeURIComponent(eventId)}`, { method: "DELETE" });
    if (res.ok) {
        closeDetailsAndRefresh();
    } else {
        const data = await readJson(res);
        alert(data.error || "Termin konnte nicht gelöscht werden.");
    }
}

/**
 * Öffnet das Termin-Formular im Bearbeitungsmodus und befüllt es mit
 * den aktuellen Werten des Termins.
 *
 * WARUM auch Kunde, Link und Ganztägig befüllt werden: Das Formular
 * sendet diese Felder beim Speichern immer mit. Wären sie leer,
 * würde ein Bearbeiten sie versehentlich löschen.
 *
 * @param {object} event - FullCalendar-EventApi-Objekt.
 */
function openEditForm(event) {
    const props = event.extendedProps;
    document.getElementById("event-details-modal").classList.add("hidden");
    document.getElementById("event-modal-title").textContent = "Termin bearbeiten";
    document.getElementById("editing-event-id").value = event.id;
    document.getElementById("event-title").value = event.title;

    const allDay = Boolean(props.is_all_day);
    const allDayCb = document.getElementById("event-is-all-day");
    if (allDayCb) allDayCb.checked = allDay;
    setAllDayInputs(allDay);
    const format = allDay ? toDateLocal : toDatetimeLocal;
    document.getElementById("event-start").value = format(event.start);
    document.getElementById("event-end").value = format(event.end);

    document.getElementById("event-assignee").value = props.assigned_to_id || "";
    const customer = document.getElementById("event-customer");
    if (customer) customer.value = props.customer_id || "";
    const meetingLink = document.getElementById("event-meeting-link");
    if (meetingLink) meetingLink.value = props.meeting_link || "";

    document.getElementById("event-error")?.classList.add("hidden");
    document.getElementById("event-modal").classList.remove("hidden");
}

/**
 * Sendet die Zusage/Absage eines Trainers.
 * Spricht mit: PUT /api/v1/events/<id>/rsvp {status, rejection_reason}
 * Bei DECLINED markiert das Backend den Termin zur Neu-Zuweisung.
 *
 * @param {string|number} eventId
 * @param {"ACCEPTED"|"DECLINED"|"TENTATIVE"} status
 * @param {string|null} reason - Pflicht bei DECLINED.
 */
async function submitRsvp(eventId, status, reason) {
    try {
        const response = await apiFetch(`/api/v1/events/${encodeURIComponent(eventId)}/rsvp`, {
            method: "PUT",
            body: { status, rejection_reason: reason },
        });
        if (response.ok) {
            closeDetailsAndRefresh();
        } else {
            const data = await readJson(response);
            showRsvpError(data.error || "Fehler.");
        }
    } catch (err) { console.error(err); }
}

/**
 * Weist einen (abgelehnten) Termin einem neuen Mitarbeiter zu.
 * Spricht mit: PUT /api/v1/events/<id> {assigned_to_id}
 *
 * @param {string|number} eventId
 * @param {string} assigneeId - ID aus dem Auswahlfeld.
 */
async function reassignEvent(eventId, assigneeId) {
    try {
        const response = await apiFetch(`/api/v1/events/${encodeURIComponent(eventId)}`, {
            method: "PUT",
            body: { assigned_to_id: parseInt(assigneeId, 10) },
        });
        if (response.ok) {
            closeDetailsAndRefresh();
            loadNotifications();
        } else {
            const data = await readJson(response);
            alert(data.message || data.error || "Fehler bei der Zuweisung.");
        }
    } catch (err) { console.error(err); }
}

/* ------------------------------------------------------------------ */
/* Termin anlegen / bearbeiten                                        */
/* ------------------------------------------------------------------ */

/**
 * Verdrahtet das Termin-Modal (Öffnen, Schließen, Absenden).
 * Spricht mit: POST /api/v1/events (neu) bzw. PUT /api/v1/events/<id>
 *
 * Die Zeiten werden vor dem Senden von Lokalzeit in UTC umgerechnet
 * (siehe toUtcIso), weil das Backend ausschließlich UTC speichert.
 */
function setupEventCreation() {
    const modal = document.getElementById("event-modal");
    const form = document.getElementById("event-form");
    if (!modal || !form) return;

    /** Setzt Formular und Feldtypen auf den Ausgangszustand zurück. */
    const resetForm = () => {
        form.reset();
        setAllDayInputs(false);
        document.getElementById("event-error")?.classList.add("hidden");
    };

    document.getElementById("open-modal-btn")?.addEventListener("click", () => {
        document.getElementById("event-modal-title").textContent = "Neuen Termin anlegen";
        resetForm();
        document.getElementById("editing-event-id").value = ""; // nach reset(), da hidden-Felder sonst bleiben könnten
        modal.classList.remove("hidden");
    });
    document.getElementById("close-modal-btn")?.addEventListener("click", () => {
        modal.classList.add("hidden");
        resetForm();
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const errorDiv = document.getElementById("event-error");
        const showError = (msg) => { errorDiv.textContent = msg; errorDiv.classList.remove("hidden"); };

        const editingId = document.getElementById("editing-event-id").value;
        const title = document.getElementById("event-title").value;
        const startTime = toUtcIso(document.getElementById("event-start").value, false);
        const endTime = toUtcIso(document.getElementById("event-end").value, true);
        if (!startTime || !endTime) { showError("Bitte gültige Start- und Endzeiten angeben."); return; }

        const assigneeId = document.getElementById("event-assignee").value;
        const meetingLink = document.getElementById("event-meeting-link")?.value.trim();
        const customerId = document.getElementById("event-customer")?.value;

        const payload = {
            title,
            start_time: startTime,
            end_time: endTime,
            is_all_day: document.getElementById("event-is-all-day")?.checked || false,
            // null = "kein Kunde" (explizit, damit ein Entfernen beim Bearbeiten ankommt)
            customer_id: customerId ? parseInt(customerId, 10) : null,
            meeting_link: meetingLink || null,
        };
        // Beim Bearbeiten "Unzugewiesen" explizit als null senden; beim Anlegen weglassen.
        if (assigneeId) payload.assigned_to_id = parseInt(assigneeId, 10);
        else if (editingId) payload.assigned_to_id = null;

        try {
            const response = await apiFetch(
                editingId ? `/api/v1/events/${encodeURIComponent(editingId)}` : "/api/v1/events",
                { method: editingId ? "PUT" : "POST", body: payload },
            );
            const data = await readJson(response);
            if (response.ok) {
                modal.classList.add("hidden");
                resetForm();
                if (globalCalendar) globalCalendar.refetchEvents();
            } else {
                showError(data.message || data.error || "Fehler beim Speichern.");
            }
        } catch (err) {
            showError("Netzwerkfehler oder Server nicht erreichbar.");
        }
    });
}

/**
 * Verdrahtet die statischen Buttons des Detail-Modals
 * (Ablehnen-Bereich aufklappen, Modal schließen).
 */
function setupRSVPModals() {
    document.getElementById("btn-decline")?.addEventListener("click", () => {
        document.getElementById("decline-container").classList.remove("hidden");
    });
    document.getElementById("close-details-btn")?.addEventListener("click", () => {
        document.getElementById("event-details-modal").classList.add("hidden");
    });
}

/* ------------------------------------------------------------------ */
/* Login / Logout                                                     */
/* ------------------------------------------------------------------ */

/**
 * Verdrahtet Login-Formular (login.html) und Logout-Button (base.html).
 *
 * Login:  POST /api/v1/auth/login → Server setzt die HttpOnly-Cookies,
 *         das Frontend muss sich nichts merken.
 * Logout: POST /api/v1/auth/logout → Server löscht die Cookies.
 */
function setupAuth() {
    document.getElementById("login-form")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = document.getElementById("email").value;
        const password = document.getElementById("password").value;
        const errDiv = document.getElementById("login-error");
        try {
            const res = await apiFetch("/api/v1/auth/login", { method: "POST", body: { email, password } });
            const data = await readJson(res);
            if (res.ok) {
                window.location.href = "/dashboard";
            } else {
                // 401 = falsche Daten, 429 = Rate-Limit (zu viele Versuche)
                errDiv.textContent = data.error || "Anmeldung fehlgeschlagen.";
                errDiv.classList.remove("hidden");
            }
        } catch (err) {
            errDiv.textContent = "Fehler.";
            errDiv.classList.remove("hidden");
        }
    });

    document.getElementById("logout-btn")?.addEventListener("click", async () => {
        try {
            await apiFetch("/api/v1/auth/logout", { method: "POST" });
        } finally {
            // Auch wenn der Server nicht antwortet: zurück zum Login.
            window.location.href = "/login";
        }
    });
}
