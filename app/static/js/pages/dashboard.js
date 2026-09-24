/**
 * =====================================================================
 * Datei: app/static/js/pages/dashboard.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Logik der Kalenderseite (dashboard.html):
 *     - Begrüßung + Kennzahlen (heute, nächste 14 Tage, nächster Termin)
 *     - Hinweis auf abgelehnte Termine, die neu zugewiesen werden müssen
 *     - FullCalendar (Woche auf dem Desktop, Liste auf dem Smartphone)
 *     - Dialog "Termin anlegen/bearbeiten"
 *     - Dialog "Termindetails" mit RSVP (Trainer), Neu-Zuweisung,
 *       Bearbeiten und Löschen (CEO/ADMIN/TEAM_LEADER)
 *
 * Mit welchen Backend-Endpunkten spricht diese Datei?
 *   GET    /api/v1/events?start=...&end=...  → sichtbare Termine
 *   POST   /api/v1/events                     → Termin anlegen
 *   PUT    /api/v1/events/<id>                → bearbeiten / neu zuweisen
 *   DELETE /api/v1/events/<id>                → löschen (Soft-Delete)
 *   PUT    /api/v1/events/<id>/rsvp           → Zusage/Absage (Trainer)
 *   GET    /api/v1/auth/trainers              → Mitarbeiter für Zuweisungen
 *   GET    /api/v1/customers                  → Kunden (Farben, Formular)
 *   GET    /api/v1/google/busy?start=...&end=... → eigene private Belegt-Zeiten
 *                                               aus Google (Hintergrundblöcke)
 *
 * Abhängigkeiten:
 *   - FullCalendar 6 (global "FullCalendar", dist/vendor/fullcalendar.min.js)
 *   - app.js (apiFetch, readJson, getCurrentUser, toUtcIso, toDatetimeLocal,
 *     toDateLocal, isSafeHttpUrl, isValidHexColor, DEFAULT_EVENT_COLOR,
 *     PLANNER_ROLES, fetchGoogleBusyEvents)
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

/** Der aktuell im Detail-Dialog angezeigte Termin (FullCalendar-EventApi). */
let selectedEvent = null;

/** Abgelehnte Termine aus der 14-Tage-Vorschau (für den Hinweis-Banner). */
let pendingReassignments = [];

/** Unterhalb dieser Breite (px) zeigt der Kalender die kompakte Listenansicht. */
const MOBILE_BREAKPOINT = 768;

/** Farbe für Termine, die neu zugewiesen werden müssen. */
const REASSIGN_COLOR = "#DC2626";

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
 * Kurzform für den "Nächster Termin"-Block: "Heute, 14:00", "Morgen, 09:30" oder Datum.
 * @param {Date} date
 * @returns {string}
 */
function formatUpcoming(date) {
    const today = new Date();
    const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
    let day = FMT_DAY_SHORT.format(date);
    if (date.toDateString() === today.toDateString()) day = "Heute";
    else if (date.toDateString() === tomorrow.toDateString()) day = "Morgen";
    return `${day}, ${FMT_TIME.format(date)} Uhr`;
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
 * Füllt die Mitarbeiter-Auswahlfelder (Termin anlegen + Neu-Zuweisung).
 * Spricht mit: GET /api/v1/auth/trainers → [{id, name}]
 * new Option(text, value) setzt den Namen als Text → kein XSS möglich.
 */
async function loadTrainers() {
    try {
        const res = await apiFetch("/api/v1/auth/trainers");
        if (!res.ok) return;
        const data = await readJson(res);
        const selects = [document.getElementById("event-assignee"), document.getElementById("reassign-select")];
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
/* Kennzahlen & Hinweis-Banner                                        */
/* ------------------------------------------------------------------ */

/**
 * Lädt die Termine von heute 00:00 bis in 14 Tagen und aktualisiert die
 * Kennzahlen sowie den Banner "Termine neu zuweisen".
 * Spricht mit: GET /api/v1/events?start=...&end=...
 */
async function loadUpcoming() {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const endOfToday = new Date(startOfToday.getTime() + 86400000);
    const horizon = new Date(startOfToday.getTime() + 14 * 86400000);
    try {
        const url = `/api/v1/events?start=${encodeURIComponent(startOfToday.toISOString())}&end=${encodeURIComponent(horizon.toISOString())}`;
        const res = await apiFetch(url);
        if (!res.ok) throw new Error("Fehler beim Laden");
        const events = (await readJson(res)) || [];
        const list = (Array.isArray(events) ? events : [])
            .map(e => ({ ...e, start: new Date(e.start_time), end: new Date(e.end_time) }))
            .sort((a, b) => a.start - b.start);

        const todayCount = list.filter(e => e.start < endOfToday && e.end > startOfToday).length;
        document.getElementById("stat-today").textContent = String(todayCount);
        document.getElementById("stat-upcoming").textContent = String(list.length);

        const next = list.find(e => e.start > now);
        document.getElementById("stat-next-title").textContent = next ? next.title : "Keine anstehenden Termine";
        document.getElementById("stat-next-time").textContent = next ? formatUpcoming(next.start) : "in den nächsten 14 Tagen";

        pendingReassignments = isPlanner() ? list.filter(e => e.reallocation_required) : [];
        const banner = document.getElementById("reassign-banner");
        banner.hidden = pendingReassignments.length === 0;
        if (pendingReassignments.length) {
            const n = pendingReassignments.length;
            document.getElementById("reassign-banner-text").textContent = n === 1
                ? "1 Termin wurde abgelehnt und muss neu zugewiesen werden."
                : `${n} Termine wurden abgelehnt und müssen neu zugewiesen werden.`;
        }
    } catch (err) {
        ["stat-today", "stat-upcoming"].forEach(id => { document.getElementById(id).textContent = "–"; });
        document.getElementById("stat-next-title").textContent = "Konnte nicht geladen werden";
    }
}

/**
 * Banner-Button: springt zum ersten abgelehnten Termin und öffnet ihn.
 */
function showFirstReassignment() {
    const first = pendingReassignments[0];
    if (!first || !calendar) return;
    calendar.gotoDate(first.start);
    // Nach dem Laden der neuen Ansicht den Termin im Kalender suchen und öffnen.
    setTimeout(() => {
        const ev = calendar.getEventById(String(first.id));
        if (ev) openEventDetails(ev);
    }, 400);
}

/** Kalender UND Kennzahlen neu laden (nach jeder Änderung). */
function refreshAll() {
    if (calendar) calendar.refetchEvents();
    loadUpcoming();
}

/* ------------------------------------------------------------------ */
/* Kalender (FullCalendar)                                            */
/* ------------------------------------------------------------------ */

/**
 * Ansicht und Werkzeugleisten passend zur Bildschirmbreite.
 * Smartphone: Liste (gut lesbar), Desktop: Wochenraster.
 * @returns {object} FullCalendar-Optionen.
 */
function responsiveOptions() {
    const mobile = window.innerWidth < MOBILE_BREAKPOINT;
    return mobile
        ? {
            view: "listWeek",
            headerToolbar: { left: "prev,next", center: "title", right: "today" },
            footerToolbar: { center: "listWeek,timeGridDay,dayGridMonth" },
        }
        : {
            view: "timeGridWeek",
            headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,timeGridDay,listWeek" },
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
        initialView: layout.view,
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
        dayMaxEvents: true,
        // Zwei Quellen: 1. Termine aus der App, 2. eigene Belegt-Zeiten aus Google.
        eventSources: [loadCalendarEvents, loadGoogleBusy],
        eventClick: info => {
            // Hintergrundblöcke (Google belegt) haben keine Details.
            if (info.event.extendedProps.googleBusy) return;
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
            // Abgelehnte Termine zusätzlich gestreift (erkennbar auch ohne Farbsehen).
            if (info.event.extendedProps.reallocation_required) info.el.classList.add("bc-needs-reassign");
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
        successCallback((Array.isArray(data) ? data : []).map(toCalendarEvent));
    } catch (error) {
        toast("Termine konnten nicht geladen werden.", "error");
        failureCallback(error);
    }
}

/**
 * Event-Quelle 2: eigene private Belegt-Zeiten aus Google (nur Zeiträume,
 * keine Titel) als grau gestreifte Hintergrundblöcke. Ohne Verbindung,
 * ohne zugeordneten Kalender oder bei Fehlern: keine Blöcke, kein Toast.
 * Der Legenden-Eintrag erscheint nur, wenn es Blöcke gibt.
 * Spricht mit: GET /api/v1/google/busy (über app.js::fetchGoogleBusyEvents)
 * @param {object} fetchInfo - Zeitraum von FullCalendar.
 * @param {Function} successCallback
 */
async function loadGoogleBusy(fetchInfo, successCallback) {
    const blocks = await fetchGoogleBusyEvents(fetchInfo.startStr, fetchInfo.endStr, null, "Privat belegt (Google)");
    // Einmal sichtbar, bleibt der Eintrag stehen (sonst "springt" die Legende beim Blättern).
    if (blocks.length) document.getElementById("busy-legend").hidden = false;
    successCallback(blocks);
}

/**
 * Wandelt einen Termin aus der API in ein FullCalendar-Event um.
 * @param {object} e - Termin aus GET /api/v1/events.
 * @returns {object}
 */
function toCalendarEvent(e) {
    const color = e.reallocation_required
        ? REASSIGN_COLOR
        : (isValidHexColor(e.color) ? e.color : DEFAULT_EVENT_COLOR);
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
            reallocation_required: e.reallocation_required,
            assigned_to_id: e.assigned_to_id,
            meeting_link: e.meeting_link,
            customer_id: e.customer_id,
            is_all_day: e.is_all_day,
            is_mandatory: e.is_mandatory,
            rejection_reason: e.rejection_reason,
        },
    };
}

/* ------------------------------------------------------------------ */
/* Detail-Dialog                                                      */
/* ------------------------------------------------------------------ */

/**
 * Öffnet den Detail-Dialog eines Termins und zeigt – je nach Rolle –
 * RSVP-Buttons (Trainer), Neu-Zuweisung und Verwaltung (CEO/ADMIN/TL).
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
    document.getElementById("detail-status").hidden = !props.reallocation_required;

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

    // Alle rollenabhängigen Bereiche zurücksetzen.
    const rsvpSection = document.getElementById("rsvp-section");
    const reassignSection = document.getElementById("reassign-section");
    const adminActions = document.getElementById("admin-actions");
    rsvpSection.hidden = true;
    reassignSection.hidden = true;
    adminActions.hidden = true;
    hideFormError("rsvp-error");
    document.getElementById("decline-container").hidden = true;
    document.getElementById("btn-decline").setAttribute("aria-expanded", "false");
    document.getElementById("decline-reason").value = "";

    if (viewer.role === "TRAINER") {
        // Pflichttermine können nicht abgelehnt werden → keine RSVP-Buttons.
        if (!props.is_mandatory) rsvpSection.hidden = false;
    } else if (isPlanner()) {
        if (props.reallocation_required) {
            reassignSection.hidden = false;
            const reasonEl = document.getElementById("detail-rejection-reason");
            reasonEl.textContent = props.rejection_reason ? `„${props.rejection_reason}“` : "";
            reasonEl.hidden = !props.rejection_reason;
            document.getElementById("reassign-select").value = "";
        }
        adminActions.hidden = false;
    }
    openDialog("event-details-modal");
}

/**
 * Zeigt eine Fehlermeldung im RSVP-Bereich an.
 * @param {string} message
 */
function showRsvpError(message) {
    showFormError("rsvp-error", message);
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
 * Sendet die Zusage/Absage eines Trainers.
 * Spricht mit: PUT /api/v1/events/<id>/rsvp {status, rejection_reason}
 * Bei DECLINED markiert das Backend den Termin zur Neu-Zuweisung.
 *
 * @param {"ACCEPTED"|"DECLINED"} status
 * @param {string|null} reason - Pflicht bei DECLINED.
 * @param {HTMLButtonElement} button - für den Lade-Zustand.
 */
async function submitRsvp(status, reason, button) {
    if (!selectedEvent) return;
    setBusy(button, true, "Sendet …");
    try {
        const response = await apiFetch(`/api/v1/events/${encodeURIComponent(selectedEvent.id)}/rsvp`, {
            method: "PUT",
            body: { status, rejection_reason: reason },
        });
        if (response.ok) {
            closeDialog("event-details-modal");
            toast(status === "ACCEPTED" ? "Zusage gesendet – danke!" : "Absage gesendet. Die Planung wurde informiert.");
            refreshAll();
        } else {
            const data = await readJson(response);
            showRsvpError(data.error || "Rückmeldung konnte nicht gespeichert werden.");
        }
    } catch (err) {
        showRsvpError("Netzwerkfehler oder Server nicht erreichbar.");
    }
    setBusy(button, false);
}

/**
 * Weist den ausgewählten (abgelehnten) Termin einem neuen Mitarbeiter zu.
 * Spricht mit: PUT /api/v1/events/<id> {assigned_to_id}
 */
async function reassignSelectedEvent() {
    const select = document.getElementById("reassign-select");
    if (!selectedEvent) return;
    if (!select.value) {
        select.setAttribute("aria-invalid", "true");
        select.focus();
        return;
    }
    select.removeAttribute("aria-invalid");
    const button = document.getElementById("btn-reassign");
    setBusy(button, true, "Speichert …");
    try {
        const response = await apiFetch(`/api/v1/events/${encodeURIComponent(selectedEvent.id)}`, {
            method: "PUT",
            body: { assigned_to_id: parseInt(select.value, 10) },
        });
        if (response.ok) {
            closeDialog("event-details-modal");
            toast("Termin neu zugewiesen.");
            refreshAll();
            loadNotifications();
        } else {
            const data = await readJson(response);
            toast(data.message || data.error || "Fehler bei der Zuweisung.", "error");
        }
    } catch (err) {
        toast("Netzwerkfehler oder Server nicht erreichbar.", "error");
    }
    setBusy(button, false);
}

/**
 * Verdrahtet die festen Buttons des Detail-Dialogs (einmalig).
 * Die Aktionen beziehen sich immer auf `selectedEvent` – so stapeln sich
 * keine Handler, wenn nacheinander mehrere Termine geöffnet werden.
 */
function setupDetailsDialog() {
    document.getElementById("btn-accept").addEventListener("click", (e) => submitRsvp("ACCEPTED", null, e.currentTarget));
    document.getElementById("btn-decline").addEventListener("click", (e) => {
        document.getElementById("decline-container").hidden = false;
        e.currentTarget.setAttribute("aria-expanded", "true");
        document.getElementById("decline-reason").focus();
    });
    document.getElementById("btn-submit-decline").addEventListener("click", (e) => {
        const reason = document.getElementById("decline-reason").value.trim();
        if (!reason) { showRsvpError("Bitte gib eine Begründung an."); return; }
        submitRsvp("DECLINED", reason, e.currentTarget);
    });
    document.getElementById("btn-reassign").addEventListener("click", reassignSelectedEvent);
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
                // z. B. 409 "Kollision ..." – der Server liefert eine verständliche Meldung.
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
    }

    renderCalendar(document.getElementById("calendar-container"));
    loadUpcoming();
    setupEventForm();
    setupDetailsDialog();
    document.getElementById("reassign-banner-btn").addEventListener("click", showFirstReassignment);
});
