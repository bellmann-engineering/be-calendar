/**
 * =====================================================================
 * Datei: app/static/js/pages/dashboard.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Logik der Kalenderseite (dashboard.html):
 *     - Begrüßung + Kennzahlen (heute, nächste 14 Tage, nächster Termin)
 *     - FullCalendar: Standard "diese + nächste Woche untereinander"
 *       (Desktop: 2-Wochen-Raster, Smartphone: 2-Wochen-Liste)
 *     - Dialog "Termin anlegen/bearbeiten"
 *     - Dialog "Termindetails" mit Bearbeiten und Löschen
 *       (CEO/ADMIN/TEAM_LEADER). Mitarbeiter sagen nicht zu oder ab – ein
 *       Termin ist mit der Zuweisung verbindlich.
 *
 * Mit welchen Backend-Endpunkten spricht diese Datei?
 *   GET    /api/v1/events?start=...&end=...  → sichtbare Termine
 *   POST   /api/v1/events                     → Termin anlegen
 *   PUT    /api/v1/events/<id>                → bearbeiten (auch Mitarbeiter wechseln)
 *   DELETE /api/v1/events/<id>                → löschen (Soft-Delete)
 *   GET    /api/v1/auth/trainers              → Mitarbeiter für Zuweisungen
 *   GET    /api/v1/customers                  → Kunden (Farben, Formular)
 *   GET    /api/v1/google/events?start=...&end=... → Termine aus dem Google-Kalender
 *                                               (eigener bzw. im Mitarbeiter-Tab)
 *   GET    /api/v1/auth                       → Mitarbeiter für die Tabs (Planer)
 *
 * Abhängigkeiten:
 *   - FullCalendar 6 (global "FullCalendar", dist/vendor/fullcalendar.min.js)
 *   - app.js (apiFetch, readJson, getCurrentUser, toUtcIso, toDatetimeLocal,
 *     toDateLocal, isSafeHttpUrl, isValidHexColor, DEFAULT_EVENT_COLOR,
 *     PLANNER_ROLES, fetchGoogleEvents, openGoogleEvent, decorateGoogleEvent)
 *   - ui.js (h, icon, toast, confirmDialog, openDialog, closeDialog,
 *     setBusy, showFormError, hideFormError, readableTextColor)
 *
 * Sicherheit:
 *   Titel, Namen und Ablehnungsgründe stammen von Benutzern und werden
 *   ausschließlich per textContent angezeigt. Kundenfarben werden vor
 *   der Verwendung auf #RRGGBB geprüft und nur über das CSSOM
 *   (element.style / FullCalendar-Optionen) gesetzt – nie als HTML.
 * =====================================================================
 */

/* ------------------------------------------------------------------ */
/* Zustand                                                            */
/* ------------------------------------------------------------------ */

/** Die FullCalendar-Instanz (für refetchEvents, gotoDate ...). */
let calendar = null;

/** Eingeloggter Benutzer (aus /api/v1/auth/me). */
let viewer = null;

/** Mitarbeiter-ID → Name (für die Anzeige "Zugewiesen an"). */
const trainerNames = new Map();

/** Kunden-ID → {name, color_hex} (für die Anzeige im Detail-Dialog). */
const customersById = new Map();

/**
 * Planer-Tabs: ID des Mitarbeiters, dessen Kalender angezeigt wird
 * (null = "Alle Termine"). Steht auch in der URL (?mitarbeiter=ID).
 * @type {?number}
 */
let selectedUserId = null;

/** Mitarbeiter für die Tabs (aus GET /api/v1/auth), ID → Benutzer. */
const tabUsers = new Map();

/** Der aktuell im Detail-Dialog angezeigte Termin (FullCalendar-EventApi). */
let selectedEvent = null;



/** Unterhalb dieser Breite (px) zeigt der Kalender die kompakte Listenansicht. */
const MOBILE_BREAKPOINT = 768;

/** Deutsche Formatierer (einmal erzeugen, oft verwenden). */
const FMT_DAY_LONG = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const FMT_DAY_SHORT = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const FMT_TIME = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });

/** Kürzel für die Rollenprüfung. */
const isPlanner = () => viewer && PLANNER_ROLES.includes(viewer.role);

/* ------------------------------------------------------------------ */
/* Formatierung                                                       */
/* ------------------------------------------------------------------ */

/**
 * Lesbarer Zeitraum eines Termins, z. B. "Do., 24. Sept. 2026 · 10:00 – 11:00 Uhr".
 * @param {Date} start
 * @param {Date|null} end
 * @param {boolean} allDay
 * @returns {string}
 */
function formatEventRange(start, end, allDay) {
    if (allDay) return `${FMT_DAY_SHORT.format(start)} · ganztägig`;
    if (!end) return `${FMT_DAY_SHORT.format(start)} · ${FMT_TIME.format(start)} Uhr`;
    const sameDay = start.toDateString() === end.toDateString();
    return sameDay
        ? `${FMT_DAY_SHORT.format(start)} · ${FMT_TIME.format(start)} – ${FMT_TIME.format(end)} Uhr`
        : `${FMT_DAY_SHORT.format(start)}, ${FMT_TIME.format(start)} – ${FMT_DAY_SHORT.format(end)}, ${FMT_TIME.format(end)} Uhr`;
}

/**
 * Begrüßung je nach Tageszeit.
 * @returns {string}
 */
function greeting() {
    const hour = new Date().getHours();
    if (hour < 11) return "Guten Morgen";
    if (hour < 18) return "Guten Tag";
    return "Guten Abend";
}

/* ------------------------------------------------------------------ */
/* Stammdaten (Mitarbeiter, Kunden)                                   */
/* ------------------------------------------------------------------ */

/**
 * Füllt die Mitarbeiter-Auswahl im Termin-Formular.
 * Spricht mit: GET /api/v1/auth/trainers → [{id, name}]
 * new Option(text, value) setzt den Namen als Text → kein XSS möglich.
 */
async function loadTrainers() {
    try {
        const res = await apiFetch("/api/v1/auth/trainers");
        if (!res.ok) return;
        const data = await readJson(res);
        const selects = [document.getElementById("event-assignee")];
        (Array.isArray(data) ? data : []).forEach(t => {
            trainerNames.set(String(t.id), t.name);
            selects.forEach(select => select?.add(new Option(t.name, t.id)));
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
        (Array.isArray(data) ? data : []).forEach(c => {
            customersById.set(String(c.id), c);
            select?.add(new Option(c.name, c.id));
        });
    } catch (err) { console.error(err); }
}

/* ------------------------------------------------------------------ */
/* Kennzahlen                                                         */
/* ------------------------------------------------------------------ */

/** Wie viele Einträge "Als Nächstes" höchstens zeigt. */
const AGENDA_NEXT_LIMIT = 8;

const FMT_AGENDA_DAY = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "numeric", month: "numeric" });

/**
 * Datum aus der API/FullCalendar: "2026-10-05" (ganztägig) als LOKALE Mitternacht –
 * new Date("2026-10-05") wäre UTC und in Deutschland schon 02:00.
 * @param {string} value
 * @returns {Date}
 */
function parseCalendarDate(value) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(value);
}

/**
 * Lädt die Agenda: alles von heute bis in 14 Tagen – App-Termine und Google-Termine,
 * für den gewählten Tab (Mitarbeiter) bzw. den eigenen Kalender.
 * Spricht mit: GET /api/v1/events und GET /api/v1/google/events
 */
async function loadUpcoming() {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const endOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    const horizon = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 15);
    document.getElementById("agenda-today-date").textContent = FMT_DAY_SHORT.format(now);
    const userId = selectedUserId; // Tab kann während des Ladens wechseln
    try {
        const url = `/api/v1/events?start=${encodeURIComponent(startOfToday.toISOString())}&end=${encodeURIComponent(horizon.toISOString())}`;
        const [res, google] = await Promise.all([
            apiFetch(url),
            fetchGoogleEvents(startOfToday.toISOString(), horizon.toISOString(), userId),
        ]);
        if (!res.ok) throw new Error("Fehler beim Laden");
        if (userId !== selectedUserId) return; // veraltet – der neue Tab lädt selbst
        const appEvents = (await readJson(res)) || [];
        const items = [
            ...(Array.isArray(appEvents) ? appEvents : [])
                .filter(e => userId === null || e.assigned_to_id === userId)
                .map(e => ({
                    source: "app", id: e.id, title: e.title, tag: e.tag, allDay: Boolean(e.is_all_day),
                    start: new Date(e.start_time), end: new Date(e.end_time), assignee: e.assigned_to_id,
                })),
            ...google.events.map(e => ({
                source: "google", title: e.title, tag: e.extendedProps.tag, allDay: e.allDay,
                start: parseCalendarDate(e.start), end: parseCalendarDate(e.end), htmlLink: e.extendedProps.htmlLink,
            })),
        ];
        // Heute: alles, was heute stattfindet (auch mehrtägige, die früher begonnen haben).
        const today = items
            .filter(i => i.start < endOfToday && i.end > startOfToday)
            .sort((a, b) => (b.allDay - a.allDay) || (a.start - b.start));
        const next = items
            .filter(i => i.start >= endOfToday && i.start < horizon)
            .sort((a, b) => (a.start - b.start) || (b.allDay - a.allDay));
        renderAgenda(today, next, now);
    } catch (err) {
        ["agenda-today", "agenda-next"].forEach(id => {
            const list = document.getElementById(id);
            list.replaceChildren(h("li", { class: "px-2 py-1 text-sm text-fg-muted", text: "Konnte nicht geladen werden." }));
            list.removeAttribute("aria-busy");
        });
    }
}

/**
 * Zeitangabe eines Agenda-Eintrags: "14:00–14:30", "ganztägig" oder "bis 25.10.".
 * @param {object} item
 * @param {Date} day - Tag, für den der Eintrag angezeigt wird.
 * @returns {string}
 */
function agendaTime(item, day) {
    if (item.allDay) {
        const lastDay = new Date(item.end.getTime() - 1); // Ende ist exklusiv
        const multi = lastDay.toDateString() !== item.start.toDateString();
        return multi && lastDay.toDateString() !== day.toDateString()
            ? `bis ${lastDay.getDate()}.${lastDay.getMonth() + 1}.`
            : "ganztägig";
    }
    return `${FMT_TIME.format(item.start)}–${FMT_TIME.format(item.end)}`;
}

/**
 * Ein Agenda-Eintrag als Button: Klick springt im Kalender zu diesem Tag
 * (Google-Termine: öffnet sie in Google).
 * @param {object} item
 * @param {Date} day
 * @param {Date} now
 * @returns {HTMLLIElement}
 */
function agendaItem(item, day, now) {
    const past = !item.allDay && item.end < now;
    const running = !item.allDay && item.start <= now && item.end > now;
    const assignee = selectedUserId === null && isPlanner() && item.assignee
        ? (tabUsers.get(item.assignee) ? `${tabUsers.get(item.assignee).first_name} ${tabUsers.get(item.assignee).last_name}` : trainerNames.get(String(item.assignee)))
        : null;
    const meta = [assignee, item.source === "google" ? "Google Kalender" : null, running ? "läuft gerade" : null].filter(Boolean).join(" · ");
    const button = h("button", {
        type: "button", class: `agenda-item ${past ? "opacity-55" : ""}`,
        on: {
            click: () => {
                if (item.source === "google" && item.htmlLink && isSafeHttpUrl(item.htmlLink)) {
                    window.open(item.htmlLink, "_blank", "noopener");
                    return;
                }
                calendar?.gotoDate(item.start);
                document.getElementById("calendar-container").scrollIntoView({ behavior: "smooth", block: "start" });
            },
        },
    },
        h("span", { class: "agenda-time", text: agendaTime(item, day) }),
        h("span", { class: "min-w-0 flex-1" },
            h("span", { class: `block truncate text-sm ${running ? "font-semibold text-accent" : "font-medium text-fg"}` },
                customerBadge(item.tag), item.title),
            meta ? h("span", { class: "block truncate text-xs text-fg-muted", text: meta }) : null,
        ),
    );
    return h("li", {}, button);
}

/**
 * Zeichnet "Heute" und "Als Nächstes" (nach Tagen gruppiert).
 * @param {object[]} today
 * @param {object[]} next
 * @param {Date} now
 */
function renderAgenda(today, next, now) {
    const empty = text => h("li", { class: "px-2 py-1 text-sm text-fg-muted", text });
    const todayList = document.getElementById("agenda-today");
    todayList.replaceChildren(...(today.length
        ? today.map(i => agendaItem(i, now, now))
        : [empty("Heute stehen keine Termine an.")]));

    const nextList = document.getElementById("agenda-next");
    const shown = next.slice(0, AGENDA_NEXT_LIMIT);
    const rows = [];
    let lastDay = "";
    shown.forEach(i => {
        const day = i.start.toDateString();
        if (day !== lastDay) {
            const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).toDateString();
            rows.push(h("li", { class: "agenda-day", text: day === tomorrow ? `Morgen · ${FMT_AGENDA_DAY.format(i.start)}` : FMT_AGENDA_DAY.format(i.start) }));
            lastDay = day;
        }
        rows.push(agendaItem(i, i.start, now));
    });
    if (next.length > shown.length) {
        rows.push(empty(`… und ${next.length - shown.length} weitere – siehe Kalender.`));
    }
    nextList.replaceChildren(...(rows.length ? rows : [empty("In den nächsten 14 Tagen keine weiteren Termine.")]));
    [todayList, nextList].forEach(list => list.removeAttribute("aria-busy"));
}

/** Kalender UND Agenda neu laden (nach jeder Änderung). */
function refreshAll() {
    if (calendar) calendar.refetchEvents();
    loadUpcoming();
}

/* ------------------------------------------------------------------ */
/* Kalender (FullCalendar)                                            */
/* ------------------------------------------------------------------ */

/**
 * Eigene Ansichten: diese + nächste Woche, jeweils ab Montag.
 *   twoWeeks     → zwei Wochenzeilen untereinander (Standard am Desktop). Jede
 *                  Tageszelle zeigt ALLE Termine: ganztägige als Balken, dazu die
 *                  stundenweisen mit Uhrzeit.
 *   listTwoWeeks → dieselben zwei Wochen als Liste (Standard auf dem Smartphone).
 * dateAlignment "week": "Heute" und die Pfeile springen immer auf einen Montag.
 */
const CUSTOM_VIEWS = {
    twoWeeks: {
        type: "dayGrid",
        duration: { weeks: 2 },
        dateAlignment: "week",
        buttonText: "2 Wochen",
        weekNumbers: true, // "KW 39" am Zeilenanfang
        // Uhrzeit auch in der Monats-/Wochenzeile, z. B. "14:00–14:30 Weekly"
        displayEventEnd: true,
    },
    listTwoWeeks: {
        type: "list",
        duration: { weeks: 2 },
        dateAlignment: "week",
        buttonText: "Liste",
    },
};

/** localStorage-Schlüssel für "Wochenende anzeigen" (nur Komfort, pro Browser). */
const WEEKENDS_STORAGE_KEY = "bc-show-weekends";

/**
 * Wochenende anzeigen? Standard: nein. Die Wahl merkt sich der Browser.
 * try/catch: localStorage kann gesperrt sein (privates Fenster) – dann gilt der Standard.
 * @returns {boolean}
 */
function loadShowWeekends() {
    try {
        return localStorage.getItem(WEEKENDS_STORAGE_KEY) === "1";
    } catch (err) {
        return false;
    }
}

/**
 * Button "Wochenende ein-/ausblenden" für die Kalenderleiste. Die Beschriftung
 * nennt immer die Aktion, die ein Klick auslöst.
 * @param {boolean} showWeekends - aktueller Zustand.
 * @returns {object} FullCalendar-customButtons.
 */
function weekendButtons(showWeekends) {
    return {
        weekendToggle: {
            text: showWeekends ? "Wochenende ausblenden" : "Wochenende einblenden",
            hint: "Samstag und Sonntag im Kalender ein- oder ausblenden",
            click: () => {
                const next = !calendar.getOption("weekends");
                try { localStorage.setItem(WEEKENDS_STORAGE_KEY, next ? "1" : "0"); } catch (err) { /* nur Komfort */ }
                calendar.setOption("weekends", next);
                calendar.setOption("customButtons", weekendButtons(next));
            },
        },
    };
}

/**
 * Ansicht und Werkzeugleisten passend zur Bildschirmbreite.
 * Standard: diese und nächste Woche untereinander (Smartphone als Liste).
 * @returns {object} FullCalendar-Optionen.
 */
function responsiveOptions() {
    const mobile = window.innerWidth < MOBILE_BREAKPOINT;
    return mobile
        ? {
            view: "listTwoWeeks",
            headerToolbar: { left: "prev,next", center: "title", right: "today" },
            footerToolbar: { center: "listTwoWeeks,timeGridDay,dayGridMonth weekendToggle" },
        }
        : {
            view: "twoWeeks",
            headerToolbar: { left: "prev,next today weekendToggle", center: "title", right: "twoWeeks,timeGridWeek,timeGridDay,dayGridMonth,listTwoWeeks" },
            footerToolbar: false,
        };
}

/**
 * Erstellt den Kalender.
 * Spricht mit: GET /api/v1/events?start=...&end=...
 *
 * FullCalendar ruft `events` bei jedem Ansichtswechsel mit dem sichtbaren
 * Zeitraum auf; nur dieser Zeitraum wird geladen. Die Zeiten kommen als
 * ISO-String MIT Offset (+00:00) – FullCalendar rechnet in Lokalzeit um.
 *
 * @param {HTMLElement} container
 */
function renderCalendar(container) {
    container.replaceChildren();
    let layout = responsiveOptions();
    calendar = new FullCalendar.Calendar(container, {
        views: CUSTOM_VIEWS,
        initialView: layout.view,
        // Wochenende standardmäßig ausgeblendet, per Button umschaltbar (weekendButtons).
        weekends: loadShowWeekends(),
        customButtons: weekendButtons(loadShowWeekends()),
        headerToolbar: layout.headerToolbar,
        footerToolbar: layout.footerToolbar,
        locale: "de",
        firstDay: 1, // Woche beginnt in Deutschland am Montag
        // Deutsche Beschriftungen (das globale Bundle enthält keine Sprachpakete).
        buttonText: { today: "Heute", month: "Monat", week: "Woche", day: "Tag", list: "Liste" },
        buttonHints: { prev: "Vorheriger Zeitraum", next: "Nächster Zeitraum", today: "Zu heute springen" },
        viewHint: "Ansicht $0",
        noEventsText: "Keine Termine in diesem Zeitraum",
        allDayText: "Ganztägig",
        moreLinkText: n => `+ ${n} weitere`,
        weekText: "KW",
        navLinkHint: "Gehe zu $0",
        allDaySlot: true,
        slotMinTime: "06:00:00",
        slotMaxTime: "22:00:00",
        scrollTime: "07:30:00",
        slotLabelFormat: { hour: "2-digit", minute: "2-digit" },
        eventTimeFormat: { hour: "2-digit", minute: "2-digit" },
        dayHeaderFormat: { weekday: "short", day: "numeric", month: "numeric" },
        nowIndicator: true,
        // Termine per Tastatur erreichbar (Tab) und mit Enter zu öffnen.
        eventInteractive: true,
        height: "auto",
        expandRows: true,
        // Alle Termine zeigen, nie "+2 weitere": An einem Tag kann es mehrere ganztägige
        // und stundenweise Termine geben – alle müssen sichtbar sein.
        dayMaxEvents: false,
        // Gleichzeitige Termine NEBENeinander statt überlappend (sonst verdeckt).
        slotEventOverlap: false,
        // Zwei Quellen: 1. Termine aus der App, 2. Termine aus dem eigenen Google-Kalender.
        eventSources: [loadCalendarEvents, loadGoogleEvents],
        eventClick: info => {
            // Google-Termine gehören nicht der App → im Google Kalender öffnen.
            if (info.event.extendedProps.source === "google") {
                info.jsEvent.preventDefault();
                openGoogleEvent(info.event);
                return;
            }
            openEventDetails(info.event);
        },
        // Klick auf eine freie Stelle: Planer legen direkt dort einen Termin an.
        dateClick: info => {
            if (!isPlanner()) return;
            const start = new Date(info.date);
            if (info.allDay) start.setHours(9, 0, 0, 0); // Monatsansicht: sinnvoller Standard 09:00
            openCreateForm(start);
        },
        eventDidMount: info => {
            if (info.event.extendedProps.source === "google") decorateGoogleEvent(info);
            decorateCustomerTag(info);
        },
        // Beim Drehen/Vergrößern des Fensters zwischen Liste und Wochenraster wechseln.
        windowResize: () => {
            const next = responsiveOptions();
            if (next.view === layout.view) return;
            layout = next;
            calendar.setOption("headerToolbar", next.headerToolbar);
            calendar.setOption("footerToolbar", next.footerToolbar);
            calendar.changeView(next.view);
        },
    });
    calendar.render();
}

/**
 * Event-Quelle 1: Termine aus der App im sichtbaren Zeitraum.
 * Spricht mit: GET /api/v1/events?start=...&end=...
 * @param {object} fetchInfo - Zeitraum von FullCalendar.
 * @param {Function} successCallback
 * @param {Function} failureCallback
 */
async function loadCalendarEvents(fetchInfo, successCallback, failureCallback) {
    try {
        // encodeURIComponent ist nötig, weil startStr ein "+" enthält
        // (z. B. +02:00), das in einer URL sonst als Leerzeichen gilt.
        const url = `/api/v1/events?start=${encodeURIComponent(fetchInfo.startStr)}&end=${encodeURIComponent(fetchInfo.endStr)}`;
        const response = await apiFetch(url);
        if (!response.ok) throw new Error("Fehler beim Laden");
        const data = await readJson(response);
        // Mitarbeiter-Tab: nur dessen Termine.
        const list = (Array.isArray(data) ? data : [])
            .filter(e => selectedUserId === null || e.assigned_to_id === selectedUserId);
        successCallback(list.map(toCalendarEvent));
    } catch (error) {
        toast("Termine konnten nicht geladen werden.", "error");
        failureCallback(error);
    }
}

/**
 * Event-Quelle 2: Termine aus dem zugeordneten Google-Kalender (mit Titel, nur
 * lesend) – der eigene bzw. im Mitarbeiter-Tab der des Mitarbeiters. Ohne
 * Verbindung oder ohne zugeordneten Kalender: keine Termine, kein Toast.
 * Fehlt der Lesezugriff oder der Kalender, steht ein Hinweis unter der Legende.
 * Spricht mit: GET /api/v1/google/events (über app.js::fetchGoogleEvents)
 * @param {object} fetchInfo - Zeitraum von FullCalendar.
 * @param {Function} successCallback
 */
async function loadGoogleEvents(fetchInfo, successCallback) {
    const { events, error } = await fetchGoogleEvents(fetchInfo.startStr, fetchInfo.endStr, selectedUserId);
    // Einmal sichtbar, bleibt der Eintrag stehen (sonst "springt" die Legende beim Blättern).
    if (events.length) document.getElementById("google-legend").hidden = false;
    const selected = selectedUserId !== null ? tabUsers.get(selectedUserId) : null;
    let message = error ? `Google-Kalender: ${error}` : "";
    if (!message && selected && !selected.google_calendar_id) {
        message = `${selected.first_name} ${selected.last_name} ist kein Google-Kalender zugeordnet.`;
    }
    const hint = document.getElementById("google-error");
    hint.textContent = message;
    hint.hidden = !message;
    successCallback(events);
}

/* ------------------------------------------------------------------ */
/* Planer-Tabs: Kalender einzelner Mitarbeiter                        */
/* ------------------------------------------------------------------ */

/**
 * Baut die Tabs "Alle Termine" + je Mitarbeiter (nur Planer). So sehen CEO,
 * Administration und Teamleitung den Kalender eines Mitarbeiters – App-Termine
 * UND seinen Google-Kalender –, ohne sich als er anzumelden.
 * Spricht mit: GET /api/v1/auth (Teamleitung bekommt nur ihr Team; die
 * Google-Termine prüft der Server ebenfalls nach diesen Regeln).
 */
async function setupCalendarTabs() {
    const tablist = document.getElementById("calendar-tabs");
    try {
        const res = await apiFetch("/api/v1/auth");
        if (!res.ok) return;
        const users = (await readJson(res)) || [];
        (Array.isArray(users) ? users : [])
            .filter(u => u.is_active)
            .sort((a, b) => `${a.first_name} ${a.last_name}`.localeCompare(`${b.first_name} ${b.last_name}`, "de"))
            .forEach(u => tabUsers.set(Number(u.id), u));
    } catch (err) {
        return; // ohne Tabs: der Kalender zeigt weiter alle Termine
    }

    const tab = (userId, label, hint) => h("button", {
        type: "button", role: "tab", class: "tab",
        id: userId === null ? "tab-all" : `tab-user-${userId}`,
        "aria-controls": "calendar-container",
        title: hint || null,
        dataset: { userId: userId === null ? "" : userId },
    }, label);

    tablist.replaceChildren(
        tab(null, "Alle Termine"),
        ...Array.from(tabUsers.values()).map(u => {
            const name = `${u.first_name} ${u.last_name}${u.id === viewer.id ? " (ich)" : ""}`;
            return tab(Number(u.id), [
                name,
                // Kleines Kalender-Symbol: Google-Kalender zugeordnet.
                u.google_calendar_id ? icon("calendar-check", "size-3.5 text-accent") : null,
            ], u.google_calendar_id ? "Mit Google-Kalender" : "Kein Google-Kalender zugeordnet");
        }),
    );

    tablist.addEventListener("click", e => {
        const button = e.target.closest(".tab");
        if (button) selectCalendarTab(tabIdOf(button));
    });
    // Tastatur (WAI-ARIA Tabs): Pfeile, Pos1, Ende wechseln den Tab.
    tablist.addEventListener("keydown", e => {
        const tabs = Array.from(tablist.querySelectorAll(".tab"));
        const index = tabs.indexOf(document.activeElement);
        if (index < 0) return;
        const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (next === undefined) return;
        e.preventDefault();
        const target = tabs[(next + tabs.length) % tabs.length];
        selectCalendarTab(tabIdOf(target));
        target.focus();
    });

    // Tab aus der URL übernehmen (Link auf den Kalender eines Mitarbeiters).
    const fromUrl = Number(new URLSearchParams(window.location.search).get("mitarbeiter"));
    selectCalendarTab(tabUsers.has(fromUrl) ? fromUrl : null, { initial: true });
    tablist.hidden = false;
}

/**
 * Mitarbeiter-ID eines Tab-Buttons (null = "Alle Termine").
 * @param {HTMLElement} button
 * @returns {?number}
 */
function tabIdOf(button) {
    return button.dataset.userId ? Number(button.dataset.userId) : null;
}

/**
 * Wechselt den angezeigten Kalender: Tabs markieren, Überschrift und URL
 * anpassen, Termine neu laden.
 * @param {?number} userId - Mitarbeiter oder null für "Alle Termine".
 * @param {{initial?: boolean}} [options] - initial: Kalender lädt ohnehin gleich.
 */
function selectCalendarTab(userId, { initial = false } = {}) {
    selectedUserId = userId;
    const activeId = userId === null ? "tab-all" : `tab-user-${userId}`;
    document.querySelectorAll("#calendar-tabs .tab").forEach(t => {
        const active = t.id === activeId;
        t.setAttribute("aria-selected", String(active));
        t.tabIndex = active ? 0 : -1; // nur der aktive Tab ist per Tab-Taste erreichbar
    });
    document.getElementById("calendar-container").setAttribute("aria-labelledby", activeId);

    const user = userId !== null ? tabUsers.get(userId) : null;
    document.getElementById("dash-subtitle").textContent = user
        ? `Kalender von ${user.first_name} ${user.last_name} – Termine aus der App und aus Google.`
        : "Alle Termine und Einsätze auf einen Blick.";

    const url = new URL(window.location.href);
    if (userId === null) url.searchParams.delete("mitarbeiter");
    else url.searchParams.set("mitarbeiter", String(userId));
    history.replaceState(history.state, "", url.pathname + url.search + url.hash);

    if (!initial && calendar) {
        calendar.refetchEvents();
        loadUpcoming(); // Agenda folgt dem Tab
    }
}

/**
 * Wandelt einen Termin aus der API in ein FullCalendar-Event um.
 * @param {object} e - Termin aus GET /api/v1/events.
 * @returns {object}
 */
function toCalendarEvent(e) {
    const color = isValidHexColor(e.color) ? e.color : DEFAULT_EVENT_COLOR;
    return {
        id: e.id,
        title: e.title, // FullCalendar setzt Titel als Text → sicher
        start: e.start_time,
        end: e.end_time,
        allDay: Boolean(e.is_all_day),
        backgroundColor: color,
        borderColor: color,
        textColor: readableTextColor(color), // lesbar auch auf hellen Kundenfarben
        extendedProps: {
            color,
            assigned_to_id: e.assigned_to_id,
            meeting_link: e.meeting_link,
            customer_id: e.customer_id,
            is_all_day: e.is_all_day,
            tag: e.tag, // Kunde für das kleine Logo (decorateCustomerTag)
        },
    };
}

/* ------------------------------------------------------------------ */
/* Detail-Dialog                                                      */
/* ------------------------------------------------------------------ */

/**
 * Öffnet den Detail-Dialog eines Termins und zeigt – je nach Rolle –
 * Neu-Zuweisung und Verwaltung (CEO/ADMIN/TL). Trainer sehen nur die Details.
 *
 * @param {object} event - FullCalendar-EventApi-Objekt.
 */
function openEventDetails(event) {
    selectedEvent = event;
    const props = event.extendedProps;

    // Alle Texte per textContent → auch bösartige Titel werden nur angezeigt.
    document.getElementById("detail-title").textContent = event.title;
    document.getElementById("detail-time").textContent = formatEventRange(event.start, event.end, event.allDay);
    // CSSOM statt style-Attribut: CSP-konform, Farbe ist bereits validiert.
    document.getElementById("detail-color").style.backgroundColor = props.color || DEFAULT_EVENT_COLOR;

    const assigneeName = props.assigned_to_id ? trainerNames.get(String(props.assigned_to_id)) : null;
    document.getElementById("detail-assignee-row").hidden = !isPlanner();
    document.getElementById("detail-assignee").textContent = assigneeName || (props.assigned_to_id ? `Mitarbeiter #${props.assigned_to_id}` : "Nicht zugewiesen");

    const customer = props.customer_id ? customersById.get(String(props.customer_id)) : null;
    document.getElementById("detail-customer-row").hidden = !customer;
    document.getElementById("detail-customer").textContent = customer ? customer.name : "";

    // Meeting-Link nur anzeigen, wenn es wirklich eine http(s)-URL ist.
    const link = document.getElementById("detail-link");
    if (isSafeHttpUrl(props.meeting_link)) {
        link.href = props.meeting_link;
        link.rel = "noopener noreferrer"; // Zielseite bekommt keinen Zugriff auf window.opener
        link.hidden = false;
    } else {
        link.removeAttribute("href");
        link.hidden = true;
    }

    // Bearbeiten/Löschen nur für Planer (Mitarbeiter wechseln geht über "Bearbeiten").
    document.getElementById("admin-actions").hidden = !isPlanner();
    openDialog("event-details-modal");
}

/**
 * Löscht den ausgewählten Termin nach Rückfrage (Soft-Delete im Backend).
 * Spricht mit: DELETE /api/v1/events/<id>
 */
async function deleteSelectedEvent() {
    if (!selectedEvent) return;
    const ok = await confirmDialog({
        title: "Termin löschen?",
        message: `„${selectedEvent.title}“ wird entfernt. Zugewiesene Mitarbeiter sehen ihn danach nicht mehr.`,
        confirmText: "Löschen",
    });
    if (!ok) return;
    const res = await apiFetch(`/api/v1/events/${encodeURIComponent(selectedEvent.id)}`, { method: "DELETE" });
    if (res.ok) {
        closeDialog("event-details-modal");
        toast("Termin gelöscht.");
        refreshAll();
    } else {
        const data = await readJson(res);
        toast(data.error || "Termin konnte nicht gelöscht werden.", "error");
    }
}

/**
 * Verdrahtet die festen Buttons des Detail-Dialogs (einmalig).
 * Die Aktionen beziehen sich immer auf `selectedEvent` – so stapeln sich
 * keine Handler, wenn nacheinander mehrere Termine geöffnet werden.
 */
function setupDetailsDialog() {
    document.getElementById("btn-delete").addEventListener("click", deleteSelectedEvent);
    document.getElementById("btn-edit").addEventListener("click", () => {
        if (selectedEvent) openEditForm(selectedEvent);
    });
}

/* ------------------------------------------------------------------ */
/* Termin anlegen / bearbeiten                                        */
/* ------------------------------------------------------------------ */

/**
 * Setzt den Typ der Start/Ende-Felder (mit oder ohne Uhrzeit).
 * @param {boolean} isAllDay
 */
function setAllDayInputs(isAllDay) {
    const type = isAllDay ? "date" : "datetime-local";
    document.getElementById("event-start").type = type;
    document.getElementById("event-end").type = type;
}

/** Setzt Formular, Feldtypen und Fehlermeldung auf den Ausgangszustand. */
function resetEventForm() {
    document.getElementById("event-form").reset();
    setAllDayInputs(false);
    hideFormError("event-error");
    document.getElementById("editing-event-id").value = ""; // nach reset(), hidden-Felder bleiben sonst ggf. stehen
}

/**
 * Öffnet das Formular für einen NEUEN Termin – vorbelegt mit der nächsten
 * vollen Stunde (bzw. dem angeklickten Zeitpunkt), Dauer 1 Stunde.
 * @param {Date} [start]
 */
function openCreateForm(start) {
    resetEventForm();
    document.getElementById("event-modal-title").textContent = "Neuen Termin anlegen";
    const begin = start ? new Date(start) : new Date();
    if (!start) begin.setHours(begin.getHours() + 1, 0, 0, 0);
    const end = new Date(begin.getTime() + 3600000);
    document.getElementById("event-start").value = toDatetimeLocal(begin);
    document.getElementById("event-end").value = toDatetimeLocal(end);
    // Im Mitarbeiter-Tab: neuer Termin gleich für diesen Mitarbeiter (falls planbar).
    const assignee = document.getElementById("event-assignee");
    if (selectedUserId !== null && Array.from(assignee.options).some(o => o.value === String(selectedUserId))) {
        assignee.value = String(selectedUserId);
    }
    openDialog("event-modal");
    document.getElementById("event-title").focus();
}

/**
 * Öffnet das Termin-Formular im Bearbeitungsmodus und befüllt es.
 *
 * WARUM auch Kunde, Link und Ganztägig befüllt werden: Das Formular
 * sendet diese Felder beim Speichern immer mit. Wären sie leer,
 * würde ein Bearbeiten sie versehentlich löschen.
 *
 * @param {object} event - FullCalendar-EventApi-Objekt.
 */
function openEditForm(event) {
    const props = event.extendedProps;
    closeDialog("event-details-modal");
    resetEventForm();
    document.getElementById("event-modal-title").textContent = "Termin bearbeiten";
    document.getElementById("editing-event-id").value = event.id;
    document.getElementById("event-title").value = event.title;

    const allDay = Boolean(props.is_all_day);
    document.getElementById("event-is-all-day").checked = allDay;
    setAllDayInputs(allDay);
    const format = allDay ? toDateLocal : toDatetimeLocal;
    document.getElementById("event-start").value = format(event.start);
    // Ganztägige Termine: FullCalendar liefert das Ende exklusiv (Folgetag 00:00)
    // oder – bei eintägigen Terminen – gar kein Ende (null).
    let end = event.end || event.start;
    if (allDay && event.end) end = new Date(event.end.getTime() - 1000);
    document.getElementById("event-end").value = format(end);

    document.getElementById("event-assignee").value = props.assigned_to_id || "";
    document.getElementById("event-customer").value = props.customer_id || "";
    document.getElementById("event-meeting-link").value = props.meeting_link || "";
    openDialog("event-modal");
}

/**
 * Verdrahtet Termin-Dialog (Öffnen, Ganztägig, Absenden).
 * Spricht mit: POST /api/v1/events (neu) bzw. PUT /api/v1/events/<id>
 *
 * Die Zeiten werden vor dem Senden von Lokalzeit in UTC umgerechnet
 * (siehe toUtcIso in app.js), weil das Backend ausschließlich UTC speichert.
 */
function setupEventForm() {
    const form = document.getElementById("event-form");
    document.getElementById("open-modal-btn").addEventListener("click", () => openCreateForm());
    document.getElementById("event-is-all-day").addEventListener("change", (e) => {
        // Vorhandene Werte beim Umschalten erhalten (nur Datumsteil bzw. 09:00/17:00).
        const start = document.getElementById("event-start");
        const end = document.getElementById("event-end");
        const [s, en] = [start.value.substring(0, 10), end.value.substring(0, 10)];
        setAllDayInputs(e.target.checked);
        start.value = e.target.checked ? s : (s ? `${s}T09:00` : "");
        end.value = e.target.checked ? en : (en ? `${en}T17:00` : "");
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideFormError("event-error");
        const titleInput = document.getElementById("event-title");
        const editingId = document.getElementById("editing-event-id").value;
        const title = titleInput.value.trim();
        if (!title) {
            titleInput.setAttribute("aria-invalid", "true");
            showFormError("event-error", "Bitte gib einen Titel ein.");
            titleInput.focus();
            return;
        }
        titleInput.removeAttribute("aria-invalid");

        const startTime = toUtcIso(document.getElementById("event-start").value, false);
        const endTime = toUtcIso(document.getElementById("event-end").value, true);
        if (!startTime || !endTime) { showFormError("event-error", "Bitte gültige Start- und Endzeiten angeben."); return; }
        if (new Date(endTime) <= new Date(startTime)) { showFormError("event-error", "Das Ende muss nach dem Beginn liegen."); return; }

        const assigneeId = document.getElementById("event-assignee").value;
        const meetingLink = document.getElementById("event-meeting-link").value.trim();
        const customerId = document.getElementById("event-customer").value;

        const payload = {
            title,
            start_time: startTime,
            end_time: endTime,
            is_all_day: document.getElementById("event-is-all-day").checked,
            // null = "kein Kunde" (explizit, damit ein Entfernen beim Bearbeiten ankommt)
            customer_id: customerId ? parseInt(customerId, 10) : null,
            meeting_link: meetingLink || null,
        };
        // Beim Bearbeiten "Nicht zugewiesen" explizit als null senden; beim Anlegen weglassen.
        if (assigneeId) payload.assigned_to_id = parseInt(assigneeId, 10);
        else if (editingId) payload.assigned_to_id = null;

        const submit = document.getElementById("event-submit");
        setBusy(submit, true, "Speichert …");
        try {
            const response = await apiFetch(
                editingId ? `/api/v1/events/${encodeURIComponent(editingId)}` : "/api/v1/events",
                { method: editingId ? "PUT" : "POST", body: payload },
            );
            const data = await readJson(response);
            if (response.ok) {
                closeDialog("event-modal");
                toast(editingId ? "Termin aktualisiert." : "Termin angelegt.");
                refreshAll();
            } else {
                // Der Server liefert eine verständliche Meldung (z. B. 403 fehlende Rechte).
                showFormError("event-error", data.message || data.error || "Fehler beim Speichern.");
            }
        } catch (err) {
            showFormError("event-error", "Netzwerkfehler oder Server nicht erreichbar.");
        }
        setBusy(submit, false);
    });
}

/* ------------------------------------------------------------------ */
/* Seitenstart                                                        */
/* ------------------------------------------------------------------ */

document.addEventListener("DOMContentLoaded", async () => {
    viewer = await window.currentUserPromise;
    if (!viewer) return; // app.js leitet bereits auf /login um

    document.getElementById("dash-date").textContent = FMT_DAY_LONG.format(new Date());
    document.getElementById("dash-greeting").textContent = `${greeting()}, ${viewer.first_name || ""}`.trim();
    document.getElementById("dashboard-content").hidden = false;

    if (isPlanner()) {
        document.getElementById("open-modal-btn").hidden = false;
        // Stammdaten parallel laden; der Kalender wartet nicht darauf.
        loadTrainers();
        loadCustomers();
        // Tabs zuerst: Ein ?mitarbeiter= aus der URL soll schon beim ersten Laden gelten.
        await setupCalendarTabs();
    }

    renderCalendar(document.getElementById("calendar-container"));
    loadUpcoming();
    setupEventForm();
    setupDetailsDialog();
});
