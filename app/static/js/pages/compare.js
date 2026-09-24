/**
 * =====================================================================
 * Datei: app/static/js/pages/compare.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Logik der Vergleichsseite (compare.html): zwei Tagesansichten
 *   (FullCalendar) für zwei ausgewählte Mitarbeiter nebeneinander,
 *   inkl. Tagesnavigation (vorheriger/nächster Tag, heute).
 *
 * Mit welchen Backend-Endpunkten spricht diese Datei?
 *   GET /api/v1/auth                       → Mitarbeiterliste (nur aktive
 *                                            werden angeboten; TL sieht nur
 *                                            sein eigenes Team)
 *   GET /api/v1/events?start=...&end=...   → Termine im sichtbaren Zeitraum
 *   GET /api/v1/google/busy?start=...&end=...&user_ids=<id>
 *                                          → private Belegt-Zeiten aus Google
 *                                            (grau gestreifte Hintergrundblöcke)
 *
 * Abhängigkeiten:
 *   FullCalendar (global), app.js (apiFetch, readJson, toDateLocal,
 *   fetchGoogleBusyEvents),
 *   ui.js (initials, showFormError, hideFormError, toast, readableTextColor).
 * =====================================================================
 */

/** Terminfarben der beiden Spalten (passen zu den Punkten im Formular). */
const COLOR_A = "#2B6CB0";
const COLOR_B = "#0F766E";

/** Die beiden Kalender-Instanzen. */
let calendarA = null;
let calendarB = null;

/** Mitarbeiter-ID → Benutzerobjekt (für Namen/Initialen). */
const employeesById = new Map();

/**
 * Anzahl Termine und Google-Belegt-Blöcke je Spalte ("a"/"b").
 * Beide Event-Quellen laden unabhängig voneinander; renderCount() baut
 * daraus die Zeile unter dem Namen, sobald eine Quelle fertig ist.
 */
const counts = { a: { events: 0, busy: 0 }, b: { events: 0, busy: 0 } };

/** Formatierer für die Tagesüberschrift. */
const FMT_COMPARE_DAY = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

/**
 * Lädt die aktiven Mitarbeiter und füllt beide Auswahlfelder.
 * Spricht mit: GET /api/v1/auth
 * Option-Texte werden über `new Option(text, value)` gesetzt → kein HTML.
 */
async function loadEmployees() {
    const res = await apiFetch("/api/v1/auth");
    if (!res.ok) {
        showFormError("compare-error", "Die Mitarbeiterliste konnte nicht geladen werden.");
        return;
    }
    const users = await readJson(res);
    const active = (Array.isArray(users) ? users : []).filter(u => u.is_active);
    active.forEach(u => employeesById.set(String(u.id), u));
    ["trainer-a", "trainer-b"].forEach(selectId => {
        const select = document.getElementById(selectId);
        active.forEach(u => select.add(new Option(`${u.first_name} ${u.last_name}`, u.id)));
    });
}

/**
 * Erzeugt die `events`-Funktion für einen der beiden Kalender.
 * Lädt alle sichtbaren Termine des Zeitraums und filtert im Browser
 * auf den im jeweiligen Auswahlfeld gewählten Mitarbeiter.
 * Spricht mit: GET /api/v1/events?start=...&end=...
 *
 * @param {string} selectId - ID des Auswahlfelds ("trainer-a"/"trainer-b").
 * @param {string} color - Hintergrundfarbe der Termine.
 * @param {string} side - Spalte "a" oder "b" (für die Anzahl im Kopf).
 * @returns {Function} FullCalendar-kompatible Event-Quelle.
 */
function makeEventSource(selectId, color, side) {
    return async function (fetchInfo, successCallback, failureCallback) {
        const employeeId = document.getElementById(selectId).value;
        if (!employeeId) { successCallback([]); return; } // noch niemand gewählt → kein Request
        try {
            // encodeURIComponent: startStr enthält z. B. "+02:00"
            const url = `/api/v1/events?start=${encodeURIComponent(fetchInfo.startStr)}&end=${encodeURIComponent(fetchInfo.endStr)}`;
            const res = await apiFetch(url);
            if (!res.ok) throw new Error("Fehler beim Laden");
            const data = await readJson(res);
            const events = (Array.isArray(data) ? data : [])
                .filter(e => String(e.assigned_to_id) === String(employeeId))
                .map(e => ({
                    id: e.id, title: e.title, start: e.start_time, end: e.end_time, allDay: Boolean(e.is_all_day),
                    backgroundColor: color, borderColor: color, textColor: readableTextColor(color),
                }));
            counts[side].events = events.length;
            renderCount(side);
            successCallback(events);
        } catch (err) {
            toast("Termine konnten nicht geladen werden.", "error");
            failureCallback(err);
        }
    };
}

/**
 * Erzeugt die zweite Event-Quelle eines Kalenders: Belegt-Zeiten aus dem
 * Google-Kalender des gewählten Mitarbeiters (nur Zeiträume, keine Titel).
 * Fehler oder "nicht verbunden" ergeben einfach keine Blöcke.
 * Spricht mit: GET /api/v1/google/busy (über app.js::fetchGoogleBusyEvents)
 *
 * @param {string} selectId - ID des Auswahlfelds ("trainer-a"/"trainer-b").
 * @param {string} side - Spalte "a" oder "b" (für die Anzahl im Kopf).
 * @returns {Function} FullCalendar-kompatible Event-Quelle.
 */
function makeBusySource(selectId, side) {
    return async function (fetchInfo, successCallback) {
        const employeeId = document.getElementById(selectId).value;
        const blocks = employeeId ? await fetchGoogleBusyEvents(fetchInfo.startStr, fetchInfo.endStr, employeeId) : [];
        counts[side].busy = blocks.length;
        renderCount(side);
        // Legenden-Eintrag nur zeigen, wenn mindestens eine Spalte Blöcke hat.
        document.getElementById("busy-legend").hidden = counts.a.busy + counts.b.busy === 0;
        successCallback(blocks);
    };
}

/**
 * Schreibt die Zeile unter dem Namen einer Spalte, z. B.
 * "2 Termine · 1 Zeitraum privat belegt (Google)".
 * "ganztägig verfügbar" nur, wenn es weder Termine noch Belegt-Zeiten gibt.
 * @param {string} side - "a" oder "b".
 */
function renderCount(side) {
    const { events, busy } = counts[side];
    let text = events === 0 ? "Keine Termine" : (events === 1 ? "1 Termin" : `${events} Termine`);
    if (busy > 0) text += ` · ${busy === 1 ? "1 Zeitraum" : `${busy} Zeiträume`} privat belegt (Google)`;
    else if (events === 0) text += " – ganztägig verfügbar";
    document.getElementById(`count-${side}`).textContent = text;
}

/**
 * Zeigt den gewählten Tag in beiden Kalendern und lädt die Termine neu.
 * @param {string} isoDate - "YYYY-MM-DD".
 */
function showDay(isoDate) {
    document.getElementById("compare-date").value = isoDate;
    // "T00:00" ohne Offset = lokale Mitternacht → korrekter Wochentag in der Überschrift.
    document.getElementById("compare-day-label").textContent = FMT_COMPARE_DAY.format(new Date(`${isoDate}T00:00`));
    calendarA.gotoDate(isoDate);
    calendarB.gotoDate(isoDate);
    calendarA.refetchEvents();
    calendarB.refetchEvents();
}

/**
 * Verschiebt den Vergleich um n Tage.
 * @param {number} days
 */
function shiftDay(days) {
    const current = new Date(`${document.getElementById("compare-date").value}T00:00`);
    current.setDate(current.getDate() + days);
    showDay(toDateLocal(current));
}

/**
 * Überschrift (Name + Initialen) einer Spalte setzen – nur per textContent.
 * @param {string} side - "a" oder "b".
 * @param {HTMLSelectElement} select
 */
function setColumnHeader(side, select) {
    const user = employeesById.get(select.value);
    document.getElementById(`title-${side}`).textContent = select.options[select.selectedIndex].text;
    document.getElementById(`avatar-${side}`).textContent = user ? initials(user.first_name, user.last_name) : "?";
}

document.addEventListener("DOMContentLoaded", async () => {
    const me = await window.currentUserPromise;
    if (!me) return; // Umleitung erledigt app.js

    document.getElementById("compare-date").value = toDateLocal(new Date());
    loadEmployees();

    // Gemeinsame Einstellungen beider Tagesansichten.
    const commonConfig = {
        initialView: "timeGridDay",
        headerToolbar: false,
        locale: "de",
        slotMinTime: "06:00:00",
        slotMaxTime: "20:00:00",
        allDaySlot: true,
        allDayText: "Ganztägig",
        noEventsText: "Keine Termine",
        slotLabelFormat: { hour: "2-digit", minute: "2-digit" },
        eventTimeFormat: { hour: "2-digit", minute: "2-digit" },
        nowIndicator: true,
        height: "auto",
    };
    calendarA = new FullCalendar.Calendar(document.getElementById("calendar-a"), {
        ...commonConfig,
        eventSources: [makeEventSource("trainer-a", COLOR_A, "a"), makeBusySource("trainer-a", "a")],
    });
    calendarB = new FullCalendar.Calendar(document.getElementById("calendar-b"), {
        ...commonConfig,
        eventSources: [makeEventSource("trainer-b", COLOR_B, "b"), makeBusySource("trainer-b", "b")],
    });

    document.getElementById("compare-form").addEventListener("submit", (e) => {
        e.preventDefault();
        hideFormError("compare-error");
        const selectedDate = document.getElementById("compare-date").value;
        const trainerA = document.getElementById("trainer-a");
        const trainerB = document.getElementById("trainer-b");

        if (!selectedDate || !trainerA.value || !trainerB.value) {
            showFormError("compare-error", "Bitte wähle einen Tag und beide Mitarbeiter aus.");
            return;
        }
        if (trainerA.value === trainerB.value) {
            showFormError("compare-error", "Bitte wähle zwei verschiedene Mitarbeiter aus.");
            return;
        }

        setColumnHeader("a", trainerA);
        setColumnHeader("b", trainerB);
        document.getElementById("compare-empty").hidden = true;
        const results = document.getElementById("comparison-results");
        const firstShow = results.hidden;
        results.hidden = false;
        // Erst NACH dem Einblenden zeichnen: in einem versteckten Container
        // kann FullCalendar keine Größen berechnen.
        if (firstShow) { calendarA.render(); calendarB.render(); }
        showDay(selectedDate);
    });

    document.getElementById("day-prev").addEventListener("click", () => shiftDay(-1));
    document.getElementById("day-next").addEventListener("click", () => shiftDay(1));
    document.getElementById("day-today").addEventListener("click", () => showDay(toDateLocal(new Date())));
});
