/**
 * =====================================================================
 * Datei: app/static/js/pages/members.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Logik der Mitarbeiterverwaltung (members.html, nur CEO/ADMIN):
 *   Liste mit Suche/Filter, Anlegen/Bearbeiten, CSV-Import,
 *   Aktivieren/Deaktivieren, Rechte entziehen, Löschen.
 *   Dazu die Karte "Google-Kalender": Google-Konto verbinden/trennen,
 *   Kalenderliste laden und je Mitarbeiter einen Kalender zuordnen.
 *
 * Mit welchen Backend-Endpunkten spricht diese Datei?
 *   GET    /api/v1/auth                        → Benutzerliste
 *   POST   /api/v1/auth/users                  → Benutzer anlegen
 *   PUT    /api/v1/auth/users/<id>             → Benutzer bearbeiten
 *   DELETE /api/v1/auth/users/<id>             → Benutzer löschen
 *   PUT    /api/v1/auth/<id>/status            → aktiv/gesperrt umschalten
 *   PUT    /api/v1/auth/users/<id>/revoke-role → Rolle auf TRAINER zurücksetzen
 *   POST   /api/v1/auth/csv                    → CSV-Import (multipart "file")
 *   GET    /api/v1/google/status               → Google konfiguriert/verbunden?
 *   POST   /api/v1/google/oauth/start          → Anmelde-URL bei Google holen
 *   POST   /api/v1/google/disconnect           → Verbindung trennen
 *   GET    /api/v1/google/calendars            → Kalender des verbundenen Kontos
 *   POST   /api/v1/google/calendars/check      → Zugriff auf einen Kalender prüfen
 *
 * Rückkehr von Google:
 *   Nach der Anmeldung bei Google leitet das Backend auf
 *   /members?google=verbunden bzw. /members?google=fehler&grund=... um.
 *   handleGoogleReturn() zeigt dazu einen Toast und entfernt die
 *   Parameter wieder aus der Adresszeile.
 *
 * Abhängigkeiten:
 *   app.js (apiFetch, readJson, roleLabel, roleBadgeClass),
 *   ui.js (h, icon, emptyRow, initials, toast, confirmDialog, openDialog,
 *   closeDialog, setBusy, showFormError, hideFormError).
 *
 * Sicherheit:
 *   - Alle Werte aus der API landen als Textknoten im DOM (h()).
 *   - Buttons tragen nur data-action + numerische data-id; die Daten zum
 *     Bearbeiten kommen aus usersById – nie aus HTML-Strings.
 *   - Die gezeigten Einschränkungen (wer wen zurückstufen darf ...) sind
 *     nur Komfort. Verbindlich prüft das Backend
 *     (AuthorizationService.can_manage_user).
 * =====================================================================
 */

/**
 * Zwischenspeicher der zuletzt geladenen Benutzer (ID → Benutzerobjekt).
 * @type {Map<number, object>}
 */
const usersById = new Map();

/** Rolle des eingeloggten Benutzers (wird beim Seitenstart gesetzt). */
let viewerRole = null;

/** Anzahl Tabellenspalten (für leere Zustände über die ganze Breite). */
const MEMBER_COLUMNS = 6;

/**
 * Zuletzt geladener Google-Status (GET /api/v1/google/status) oder null,
 * solange er nicht geladen ist bzw. der Abruf fehlgeschlagen ist.
 * @type {{configured: boolean, connected: boolean, account_email: ?string, connected_at: ?string, connected_by: ?string}|null}
 */
let googleStatus = null;

/**
 * Kalender des verbundenen Google-Kontos (Cache für den Dialog).
 * null = noch nicht geladen; googleCalendarsError enthält ggf. den Fehlertext.
 * @type {Array<object>|null}
 */
let googleCalendars = null;
let googleCalendarsError = null;

/** true, sobald GET /api/v1/auth geantwortet hat (siehe refreshUsersTable). */
let usersLoaded = false;

/** Laufender Abruf der Kalenderliste (verhindert doppelte Requests). */
let googleCalendarsPromise = null;

/** Kalender-ID des Mitarbeiters beim Öffnen des Dialogs ("" = keiner). */
let gcalOriginal = "";

/** Deutsche Bezeichnungen der Google-Zugriffsrechte (access_role). */
const GOOGLE_ACCESS_ROLES = {
    owner: "Besitzer",
    writer: "Bearbeiten",
    reader: "Nur lesen",
    freeBusyReader: "Nur Frei/Belegt",
};

/** Formatierer für "verbunden seit" (z. B. "25.09.2026, 14:05"). */
const FMT_GOOGLE_DATE = new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" });

/* ------------------------------------------------------------------ */
/* Liste                                                              */
/* ------------------------------------------------------------------ */

/**
 * Lädt alle Benutzer und zeichnet die Tabelle.
 * Spricht mit: GET /api/v1/auth
 */
async function loadUsers() {
    const tbody = document.getElementById("users-table-body");
    try {
        const res = await apiFetch("/api/v1/auth");
        if (!res.ok) {
            tbody.replaceChildren(emptyRow(MEMBER_COLUMNS, "lock", "Keine Berechtigung",
                "Diese Seite ist nur für CEO und Administration verfügbar."));
            return;
        }
        const users = await readJson(res);
        usersById.clear();
        (Array.isArray(users) ? users : []).forEach(u => usersById.set(Number(u.id), u));
        usersLoaded = true;
        renderUsers();
    } catch (err) {
        tbody.replaceChildren(emptyRow(MEMBER_COLUMNS, "alert", "Netzwerkfehler", "Die Liste konnte nicht geladen werden."));
    } finally {
        tbody.removeAttribute("aria-busy");
    }
}

/**
 * Zeichnet die Tabelle neu, sobald sich die Kalenderliste geändert hat
 * (Kalendernamen statt IDs) – aber erst, wenn die Benutzer geladen sind,
 * sonst würde das Skelett durch "Noch keine Mitarbeiter" ersetzt.
 */
function refreshUsersTable() {
    if (usersLoaded) renderUsers();
}

/**
 * Zeichnet die Tabelle anhand von Suche, Rollen- und Kalenderfilter neu.
 */
function renderUsers() {
    const tbody = document.getElementById("users-table-body");
    const query = document.getElementById("member-search").value.trim().toLowerCase();
    const role = document.getElementById("member-role-filter").value;
    const gcal = document.getElementById("member-gcal-filter").value;
    const all = Array.from(usersById.values());
    const visible = all.filter(u => {
        if (role && u.role !== role) return false;
        if (gcal === "assigned" && !u.google_calendar_id) return false;
        if (gcal === "missing" && u.google_calendar_id) return false;
        if (!query) return true;
        const calendarName = findGoogleCalendar(u.google_calendar_id)?.summary || "";
        return `${u.first_name} ${u.last_name} ${u.email} ${u.google_calendar_id || ""} ${calendarName}`
            .toLowerCase().includes(query);
    });

    document.getElementById("member-count").textContent =
        visible.length === all.length ? `${all.length} Mitarbeiter` : `${visible.length} von ${all.length} Mitarbeitern`;

    if (visible.length === 0) {
        tbody.replaceChildren(all.length === 0
            ? emptyRow(MEMBER_COLUMNS, "users", "Noch keine Mitarbeiter", "Lege den ersten Mitarbeiter an oder importiere eine CSV-Datei.")
            : emptyRow(MEMBER_COLUMNS, "search", "Keine Treffer", "Keine Mitarbeiter entsprechen der Suche."));
        return;
    }
    tbody.replaceChildren(...visible.map(userRow));
}

/**
 * Kalender aus der Liste des verbundenen Google-Kontos (oder null).
 * @param {?string} calendarId
 * @returns {?object}
 */
function findGoogleCalendar(calendarId) {
    if (!calendarId || !googleCalendars) return null;
    return googleCalendars.find(c => c.id === calendarId) || null;
}

/**
 * Zelle "Google-Kalender": Name (aus der Kalenderliste) + ID darunter.
 *   - nicht zugeordnet        → grauer Hinweis
 *   - Liste geladen, Kalender
 *     fehlt darin             → Warnung: verbundenes Konto sieht ihn nicht
 *   - Liste nicht verfügbar   → nur die ID (z. B. Google nicht verbunden)
 * Alle Texte aus Google landen per h()/text im DOM – nie als HTML.
 *
 * @param {object} u - Benutzer aus der API.
 * @returns {HTMLTableCellElement}
 */
function googleCalendarCell(u) {
    const label = h("span", { class: "text-fg-muted md:hidden", text: "Google-Kalender: " });
    // Auf dem Smartphone eine eigene Zeile in der Karte (block), am PC normale Zelle.
    const cellClass = "mt-2 block max-w-full align-middle md:mt-0 md:table-cell md:max-w-72";

    if (!u.google_calendar_id) {
        return h("td", { class: cellClass },
            label, h("span", { class: "badge badge-gray", text: "Nicht zugeordnet" }));
    }

    const calendar = findGoogleCalendar(u.google_calendar_id);
    const missing = Boolean(googleCalendars) && !calendar;
    const name = calendar ? `${calendar.summary || calendar.id}${calendar.primary ? " (Hauptkalender)" : ""}` : null;
    const role = calendar ? (GOOGLE_ACCESS_ROLES[calendar.access_role] || calendar.access_role) : null;

    return h("td", { class: cellClass },
        label,
        h("span", { class: "inline-flex max-w-full min-w-0 flex-col align-top" },
            h("span", { class: "flex min-w-0 items-center gap-1.5" },
                icon(missing ? "alert" : "calendar-check", `size-4 shrink-0 ${missing ? "text-warning" : "text-accent"}`),
                h("span", { class: "truncate font-medium text-fg", text: name || u.google_calendar_id, title: u.google_calendar_id }),
            ),
            // Die ID nur zusätzlich zeigen, wenn oben der Name steht.
            name ? h("span", {
                class: "truncate text-xs text-fg-muted",
                text: role ? `${u.google_calendar_id} · ${role}` : u.google_calendar_id,
                title: u.google_calendar_id,
            }) : null,
            missing ? h("span", { class: "text-xs text-warning", text: "Kein Zugriff über das verbundene Google-Konto" }) : null,
        ),
    );
}

/**
 * Baut eine Tabellenzeile für einen Benutzer.
 * Unter 768 px wird die Zeile per CSS zur Karte (siehe .table in app.css).
 *
 * @param {object} u - Benutzer aus der API.
 * @returns {HTMLTableRowElement}
 */
function userRow(u) {
    const fullName = `${u.first_name} ${u.last_name}`;
    // Sichtbarkeitslogik: CEO darf ADMIN/TL zurückstufen, ADMIN nur TL.
    const canRevoke = (viewerRole === "CEO" && (u.role === "ADMIN" || u.role === "TEAM_LEADER"))
        || (viewerRole === "ADMIN" && u.role === "TEAM_LEADER");

    /** Icon-Button mit verständlichem Namen für Screenreader und Tooltip. */
    const action = (name, iconName, label, extraClass = "") => h("button", {
        type: "button", class: `btn-icon btn-icon-sm ${extraClass}`,
        "aria-label": `${label}: ${fullName}`, title: label,
        dataset: { action: name, id: u.id },
    }, icon(iconName));

    // relative: auf dem Smartphone stehen die Aktionen oben rechts in der Karte.
    return h("tr", { class: "relative" },
        h("td", { class: "pr-32 md:pr-5" },
            h("div", { class: "flex items-center gap-3" },
                h("span", { class: "avatar", "aria-hidden": "true", text: initials(u.first_name, u.last_name) }),
                h("div", { class: "min-w-0" },
                    h("p", { class: "truncate font-medium text-fg", text: fullName }),
                    h("p", { class: "truncate text-xs text-fg-muted", text: u.email }),
                ),
            ),
        ),
        googleCalendarCell(u),
        // Auf dem Smartphone stehen Rolle, Team und Status nebeneinander (inline-block).
        h("td", { class: "mt-2 mr-2 inline-block align-middle md:mt-0 md:mr-0 md:table-cell" },
            h("span", { class: `badge ${roleBadgeClass(u.role)}`, text: roleLabel(u.role) })),
        h("td", { class: "mr-2 inline-block align-middle text-fg-muted md:mr-0 md:table-cell" },
            h("span", { class: "md:hidden", text: "Team: " }), u.team_name && u.team_name !== "-" ? u.team_name : "–"),
        h("td", { class: "inline-block align-middle md:table-cell" },
            h("span", {
                class: `badge badge-dot ${u.is_active ? "badge-green" : "badge-red"}`,
                text: u.is_active ? "Aktiv" : "Gesperrt",
            })),
        h("td", { class: "absolute top-3 right-3 md:static md:text-right" },
            h("div", { class: "flex gap-0.5 md:justify-end" },
                action("edit", "pencil", "Bearbeiten"),
                action("toggle", u.is_active ? "lock" : "unlock", u.is_active ? "Deaktivieren" : "Aktivieren"),
                canRevoke ? action("revoke", "shield", "Rechte entziehen") : null,
                action("delete", "trash", "Löschen", "btn-icon-danger"),
            ),
        ),
    );
}

/**
 * Zentraler Klick-Handler der Tabelle (Event-Delegation).
 * @param {MouseEvent} e
 */
function onUserTableClick(e) {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const user = usersById.get(id);
    if (!user) return;

    switch (btn.dataset.action) {
        case "edit": openManualModal(user); break;
        case "delete": deleteUser(user); break;
        case "toggle": toggleStatus(user); break;
        case "revoke": revokeRole(user); break;
    }
}

/* ------------------------------------------------------------------ */
/* Aktionen                                                           */
/* ------------------------------------------------------------------ */

/**
 * Setzt einen Benutzer auf die Rolle TRAINER zurück.
 * Spricht mit: PUT /api/v1/auth/users/<id>/revoke-role
 * @param {object} user
 */
async function revokeRole(user) {
    const ok = await confirmDialog({
        title: "Rechte entziehen?",
        message: `${user.first_name} ${user.last_name} verliert die Rolle „${roleLabel(user.role)}“ und wird zum Trainer zurückgestuft.`,
        confirmText: "Rechte entziehen",
    });
    if (!ok) return;
    const res = await apiFetch(`/api/v1/auth/users/${encodeURIComponent(user.id)}/revoke-role`, { method: "PUT" });
    const data = await readJson(res);
    if (res.ok) {
        toast(data.message || "Rechte entzogen.");
        loadUsers(); // sofort neu laden, damit die Tabelle den neuen Stand zeigt
    } else {
        toast(data.error || "Fehler beim Entziehen der Rechte.", "error");
    }
}

/**
 * Aktiviert bzw. sperrt einen Benutzer.
 * Spricht mit: PUT /api/v1/auth/<id>/status
 * @param {object} user
 */
async function toggleStatus(user) {
    if (user.is_active) {
        const ok = await confirmDialog({
            title: "Konto deaktivieren?",
            message: `${user.first_name} ${user.last_name} kann sich danach nicht mehr anmelden. Das lässt sich jederzeit rückgängig machen.`,
            confirmText: "Deaktivieren",
        });
        if (!ok) return;
    }
    const res = await apiFetch(`/api/v1/auth/${encodeURIComponent(user.id)}/status`, { method: "PUT" });
    if (res.ok) {
        toast(user.is_active ? "Konto deaktiviert." : "Konto aktiviert.");
        loadUsers();
    } else {
        const data = await readJson(res);
        toast(data.error || "Status konnte nicht geändert werden.", "error");
    }
}

/**
 * Löscht einen Benutzer endgültig (nach Rückfrage).
 * Spricht mit: DELETE /api/v1/auth/users/<id>
 * Hat der Benutzer bereits Termine erstellt, verweigert das Backend das
 * Löschen (409) – dann soll "Deaktivieren" genutzt werden.
 * @param {object} user
 */
async function deleteUser(user) {
    const ok = await confirmDialog({
        title: "Mitarbeiter endgültig löschen?",
        message: `${user.first_name} ${user.last_name} (${user.email}) wird dauerhaft entfernt. Das kann nicht rückgängig gemacht werden.`,
        confirmText: "Endgültig löschen",
    });
    if (!ok) return;
    const res = await apiFetch(`/api/v1/auth/users/${encodeURIComponent(user.id)}`, { method: "DELETE" });
    const data = await readJson(res);
    if (res.ok) {
        toast(data.message || "Benutzer gelöscht.");
        loadUsers();
    } else {
        toast(data.error || "Benutzer konnte nicht gelöscht werden.", "error");
    }
}

/* ------------------------------------------------------------------ */
/* Dialoge                                                            */
/* ------------------------------------------------------------------ */

/**
 * Öffnet den Dialog zum Anlegen (ohne Parameter) oder Bearbeiten.
 * Beim Bearbeiten ist das Passwort optional: leer = unverändert.
 *
 * @param {object|null} user - Benutzer aus der Liste oder null für "neu".
 */
function openManualModal(user = null) {
    const isEdit = Boolean(user);
    document.getElementById("manual-form").reset();
    document.getElementById("m-id").value = isEdit ? user.id : "";
    document.getElementById("m-first").value = isEdit ? user.first_name : "";
    document.getElementById("m-last").value = isEdit ? user.last_name : "";
    document.getElementById("m-email").value = isEdit ? user.email : "";
    // Option "CEO": Nur ein CEO darf die Rolle vergeben (Server prüft das ebenfalls).
    // Wird ein CEO bearbeitet, muss sie sichtbar sein – sonst wäre das Feld leer und das
    // Speichern schlüge mit "Rolle existiert nicht" fehl (z. B. Kalender für Kai zuordnen).
    const ceoOption = document.getElementById("m-role-ceo");
    const ceoErlaubt = viewerRole === "CEO" || (isEdit && user.role === "CEO");
    ceoOption.hidden = !ceoErlaubt;
    ceoOption.disabled = !ceoErlaubt;
    document.getElementById("m-role").value = isEdit ? user.role : "TRAINER";
    document.getElementById("m-pass").required = !isEdit;
    document.getElementById("m-pass-hint").textContent = isEdit ? "(leer lassen = unverändert)" : "";
    document.getElementById("manual-modal-title").textContent = isEdit ? "Mitarbeiter bearbeiten" : "Mitarbeiter anlegen";
    prepareGoogleField(isEdit ? user.google_calendar_id : "");
    hideFormError("manual-error");
    openDialog("manual-modal");
    document.getElementById("m-first").focus();
}

/**
 * Zeigt das Ergebnis des CSV-Imports an. Alle Texte (auch die vom Server
 * gemeldeten Zeilenfehler, die E-Mails aus der CSV enthalten) werden als
 * Textknoten eingefügt – eine präparierte CSV kann kein HTML einschleusen.
 *
 * @param {HTMLElement} msgDiv - Ausgabebereich.
 * @param {string} message - Erfolgsmeldung des Servers.
 * @param {string[]} errors - Warnungen pro Zeile.
 */
function renderCsvResult(msgDiv, message, errors) {
    msgDiv.className = `alert ${errors.length ? "alert-warning" : "alert-success"}`;
    msgDiv.replaceChildren(
        icon(errors.length ? "alert" : "check-circle"),
        h("div", { class: "min-w-0" },
            h("p", { class: "font-medium", text: message || "Import abgeschlossen." }),
            errors.length ? h("ul", { class: "mt-2 list-disc space-y-0.5 pl-4 text-xs break-words" },
                errors.map(err => h("li", { text: err }))) : null,
        ),
    );
    msgDiv.hidden = false;
}

/**
 * Verdrahtet CSV-Dialog: Upload per FormData.
 * Spricht mit: POST /api/v1/auth/csv (multipart/form-data).
 * apiFetch sendet FormData unverändert; der Browser setzt den Content-Type
 * inkl. Boundary selbst.
 */
function setupCsvImport() {
    document.getElementById("open-csv-btn").addEventListener("click", () => {
        document.getElementById("csv-form").reset();
        document.getElementById("csv-msg").hidden = true;
        openDialog("csv-modal");
    });

    document.getElementById("csv-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const file = document.getElementById("csv-file").files[0];
        const btn = document.getElementById("csv-btn");
        const msgDiv = document.getElementById("csv-msg");
        if (!file) {
            msgDiv.className = "alert alert-error";
            showFormError(msgDiv, "Bitte zuerst eine CSV-Datei auswählen.");
            return;
        }
        const formData = new FormData();
        formData.append("file", file);

        setBusy(btn, true, "Importiert …");
        try {
            const res = await apiFetch("/api/v1/auth/csv", { method: "POST", body: formData });
            const data = await readJson(res);
            if (res.ok) {
                renderCsvResult(msgDiv, data.message, Array.isArray(data.errors) ? data.errors : []);
                loadUsers();
            } else {
                msgDiv.className = "alert alert-error";
                showFormError(msgDiv, data.error || "Import fehlgeschlagen.");
            }
        } catch (err) {
            msgDiv.className = "alert alert-error";
            showFormError(msgDiv, "Netzwerkfehler.");
        }
        setBusy(btn, false);
    });
}

/**
 * Verdrahtet den Anlegen/Bearbeiten-Dialog.
 * Spricht mit: POST /api/v1/auth/users bzw. PUT /api/v1/auth/users/<id>
 */
function setupManualForm() {
    document.getElementById("open-manual-btn").addEventListener("click", () => openManualModal());
    document.getElementById("manual-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const form = e.currentTarget;
        hideFormError("manual-error");
        // Browser-Validierung (required, type=email, minlength) nutzen, Meldung aber selbst zeigen.
        const invalid = Array.from(form.querySelectorAll("input:not([type=hidden])")).find(el => !el.checkValidity());
        form.querySelectorAll("[aria-invalid]").forEach(el => el.removeAttribute("aria-invalid"));
        if (invalid) {
            invalid.setAttribute("aria-invalid", "true");
            const label = form.querySelector(`label[for="${invalid.id}"]`)?.firstChild?.textContent.trim() || "Feld";
            showFormError("manual-error", `Bitte „${label}“ korrekt ausfüllen. ${invalid.validationMessage}`);
            invalid.focus();
            return;
        }

        const id = document.getElementById("m-id").value;
        const payload = {
            first_name: document.getElementById("m-first").value.trim(),
            last_name: document.getElementById("m-last").value.trim(),
            email: document.getElementById("m-email").value.trim(),
            role: document.getElementById("m-role").value,
        };
        const pass = document.getElementById("m-pass").value;
        if (pass) payload.password = pass; // nur senden, wenn wirklich geändert
        // Leerer Wert → null = Zuordnung entfernen (so erwartet es das Backend).
        payload.google_calendar_id = getGoogleFieldValue() || null;

        const submit = document.getElementById("manual-submit");
        setBusy(submit, true, "Speichert …");
        try {
            const res = await apiFetch(id ? `/api/v1/auth/users/${encodeURIComponent(id)}` : "/api/v1/auth/users", {
                method: id ? "PUT" : "POST",
                body: payload,
            });
            const data = await readJson(res);
            if (res.ok) {
                closeDialog("manual-modal");
                toast(id ? "Änderungen gespeichert." : "Mitarbeiter angelegt.");
                loadUsers();
            } else {
                showFormError("manual-error", data.error || "Fehler beim Speichern.");
            }
        } catch (err) {
            showFormError("manual-error", "Netzwerkfehler.");
        }
        setBusy(submit, false);
    });
}

/* ------------------------------------------------------------------ */
/* Google-Kalender: Verbindung (Karte oberhalb der Tabelle)           */
/* ------------------------------------------------------------------ */

/**
 * Wertet die Rückkehr von der Google-Anmeldung aus (?google=...) und
 * entfernt die Parameter danach aus der Adresszeile – sonst käme der
 * Toast bei jedem Neuladen der Seite erneut.
 */
function handleGoogleReturn() {
    const url = new URL(window.location.href);
    const result = url.searchParams.get("google");
    if (!result) return;
    if (result === "verbunden") {
        toast("Google-Konto verbunden. Die Kalender stehen jetzt zur Zuordnung bereit.");
    } else if (result === "fehler") {
        // "grund" kommt aus der URL → nur als Text anzeigen (toast nutzt textContent).
        const reason = (url.searchParams.get("grund") || "").trim().slice(0, 200);
        toast(reason ? `Google-Verbindung fehlgeschlagen: ${reason}` : "Google-Verbindung fehlgeschlagen.", "error");
    }
    url.searchParams.delete("google");
    url.searchParams.delete("grund");
    history.replaceState(history.state, "", url.pathname + url.search + url.hash);
}

/**
 * Lädt den Verbindungsstatus und zeichnet die Karte neu.
 * Ist das Konto verbunden, wird die Kalenderliste gleich mitgeladen,
 * damit der Mitarbeiter-Dialog sofort die Auswahl anbieten kann.
 * Spricht mit: GET /api/v1/google/status
 */
async function loadGoogleStatus() {
    try {
        const res = await apiFetch("/api/v1/google/status");
        googleStatus = res.ok ? await readJson(res) : null;
    } catch (err) {
        googleStatus = null;
    }
    googleCalendars = null;
    googleCalendarsError = null;
    renderGoogleCard();
    refreshUsersTable();
    if (googleStatus && googleStatus.connected) {
        await loadGoogleCalendars();
        renderGoogleCard(); // jetzt mit der Anzahl der Kalender
    }
}

/**
 * Lädt die Kalender des verbundenen Google-Kontos (mit Cache).
 * Spricht mit: GET /api/v1/google/calendars
 *   409 = nicht (mehr) verbunden, 502 = Google nicht erreichbar.
 *
 * @param {boolean} [force=false] - Cache ignorieren und neu laden.
 * @returns {Promise<boolean>} true = Liste erfolgreich geladen.
 */
function loadGoogleCalendars(force = false) {
    if (googleCalendarsPromise) return googleCalendarsPromise;
    if (googleCalendars && !force) return Promise.resolve(true);
    googleCalendarsPromise = (async () => {
        try {
            const res = await apiFetch("/api/v1/google/calendars");
            const data = await readJson(res);
            if (!res.ok) throw new Error(data.error || "Die Kalenderliste konnte nicht geladen werden.");
            googleCalendars = Array.isArray(data.calendars) ? data.calendars : [];
            googleCalendarsError = null;
            return true;
        } catch (err) {
            googleCalendars = null;
            googleCalendarsError = err.message || "Die Kalenderliste konnte nicht geladen werden.";
            return false;
        } finally {
            googleCalendarsPromise = null;
            refreshUsersTable(); // Kalendernamen in der Tabelle aktualisieren
        }
    })();
    return googleCalendarsPromise;
}

/**
 * Zeichnet die Karte "Google-Kalender" passend zum Zustand:
 *   - Status unbekannt (Fehler), nicht eingerichtet, nicht verbunden, verbunden.
 * Alle Werte aus der API (E-Mail, Name) landen als Textknoten im DOM.
 */
function renderGoogleCard() {
    const badge = document.getElementById("google-badge");
    const details = document.getElementById("google-details");
    const actions = document.getElementById("google-actions");
    /** Badge umfärben (Klassen aus frontend/app.css). */
    const setBadge = (cls, text) => { badge.className = `badge badge-dot ${cls}`; badge.textContent = text; };

    if (!googleStatus) {
        setBadge("badge-red", "Unbekannt");
        details.replaceChildren(h("p", { text: "Der Status der Google-Anbindung konnte nicht geladen werden." }));
        actions.replaceChildren(h("button", {
            type: "button", class: "btn btn-secondary", on: { click: loadGoogleStatus },
        }, icon("rotate"), "Erneut versuchen"));
        return;
    }

    if (!googleStatus.configured) {
        setBadge("badge-amber", "Nicht eingerichtet");
        details.replaceChildren(h("p", {
            text: "Google-Anbindung ist noch nicht eingerichtet – OAuth-Zugangsdaten in der .env fehlen (siehe README).",
        }));
        actions.replaceChildren();
        return;
    }

    if (!googleStatus.connected) {
        setBadge("badge-gray", "Nicht verbunden");
        details.replaceChildren(h("p", {
            text: "Verbinde dein Google-Konto einmalig. Danach stehen alle Kalender, die du in Google Kalender siehst, zur Zuordnung bereit.",
        }));
        actions.replaceChildren(h("button", {
            type: "button", class: "btn btn-primary", id: "google-connect-btn",
            on: { click: (e) => startGoogleConnect(e.currentTarget) },
        }, icon("external"), "Mit Google verbinden"));
        return;
    }

    // Verbunden: Konto, seit wann, von wem – und wie viele Kalender verfügbar sind.
    setBadge("badge-green", "Verbunden");
    const since = googleStatus.connected_at ? new Date(googleStatus.connected_at) : null;
    const meta = [
        since && !isNaN(since.getTime()) ? `Verbunden seit ${FMT_GOOGLE_DATE.format(since)}` : null,
        googleStatus.connected_by ? `von ${googleStatus.connected_by}` : null,
    ].filter(Boolean).join(" ");
    let calendarsLine = null;
    if (googleCalendarsError) {
        calendarsLine = h("p", { class: "flex items-center gap-1.5 text-warning" }, icon("alert", "size-3.5 shrink-0"), h("span", { text: googleCalendarsError }));
    } else if (googleCalendars) {
        const n = googleCalendars.length;
        calendarsLine = h("p", { text: n === 1 ? "1 Kalender verfügbar" : `${n} Kalender verfügbar` });
    }
    details.replaceChildren(
        h("p", {},
            "Konto: ",
            h("span", { class: "font-medium break-all text-fg", text: googleStatus.account_email || "unbekannt" }),
        ),
        meta ? h("p", { text: meta }) : null,
        calendarsLine,
    );
    actions.replaceChildren(
        h("button", {
            type: "button", class: "btn btn-secondary", id: "google-reload-btn",
            on: { click: (e) => reloadGoogleCalendars(e.currentTarget) },
        }, icon("rotate"), "Kalender neu laden"),
        h("button", {
            type: "button", class: "btn btn-soft-danger", id: "google-disconnect-btn",
            on: { click: disconnectGoogle },
        }, icon("x-circle"), "Verbindung trennen"),
    );
}

/**
 * Startet die Anmeldung bei Google: Das Backend liefert die Anmelde-URL,
 * der Browser wechselt komplett dorthin (keine Popups – funktioniert auch
 * auf dem Smartphone). Google leitet danach zurück auf /members?google=...
 * Spricht mit: POST /api/v1/google/oauth/start
 *
 * @param {HTMLButtonElement} btn
 */
async function startGoogleConnect(btn) {
    setBusy(btn, true, "Weiterleitung …");
    try {
        const res = await apiFetch("/api/v1/google/oauth/start", { method: "POST" });
        const data = await readJson(res);
        if (!res.ok) throw new Error(data.error || "Die Verbindung konnte nicht gestartet werden.");
        const target = parseGoogleUrl(data.authorization_url);
        if (!target) throw new Error("Ungültige Anmelde-Adresse vom Server erhalten.");
        window.location.assign(target);
        return; // Seite wird verlassen → Button bleibt im Lade-Zustand
    } catch (err) {
        toast(err.message || "Netzwerkfehler.", "error");
    }
    setBusy(btn, false);
}

/**
 * Prüft die Anmelde-Adresse vom Server: Weitergeleitet wird nur zu Google
 * (https + google.com bzw. *.google.com) – nie zu einer beliebigen Adresse.
 * @param {string} value
 * @returns {?string} Geprüfte URL oder null.
 */
function parseGoogleUrl(value) {
    try {
        const url = new URL(value);
        const isGoogle = url.hostname === "google.com" || url.hostname.endsWith(".google.com");
        return url.protocol === "https:" && isGoogle ? url.href : null;
    } catch (e) {
        return null; // keine gültige absolute URL
    }
}

/**
 * Lädt die Kalenderliste neu (z. B. nachdem in Google ein Kalender
 * freigegeben wurde) und meldet das Ergebnis.
 * @param {HTMLButtonElement} btn
 */
async function reloadGoogleCalendars(btn) {
    setBusy(btn, true, "Lädt …");
    const ok = await loadGoogleCalendars(true);
    setBusy(btn, false);
    renderGoogleCard();
    if (ok) {
        const n = googleCalendars.length;
        toast(n === 1 ? "1 Kalender geladen." : `${n} Kalender geladen.`);
    } else {
        toast(googleCalendarsError, "error");
    }
}

/**
 * Trennt die Verbindung zum Google-Konto (nach Rückfrage).
 * Spricht mit: POST /api/v1/google/disconnect
 */
async function disconnectGoogle() {
    const ok = await confirmDialog({
        title: "Google-Verbindung trennen?",
        message: "Danach werden keine Termine mehr in Google-Kalender übertragen und keine Belegt-Zeiten mehr angezeigt. Die bei den Mitarbeitern hinterlegten Kalender-IDs bleiben gespeichert.",
        confirmText: "Verbindung trennen",
    });
    if (!ok) return;
    try {
        const res = await apiFetch("/api/v1/google/disconnect", { method: "POST" });
        const data = await readJson(res);
        if (!res.ok) throw new Error(data.error || "Die Verbindung konnte nicht getrennt werden.");
        toast(data.message || "Google-Verbindung getrennt.");
    } catch (err) {
        toast(err.message || "Netzwerkfehler.", "error");
    }
    loadGoogleStatus(); // Karte zeigt in jedem Fall den echten Stand
}

/* ------------------------------------------------------------------ */
/* Google-Kalender: Feld im Mitarbeiter-Dialog                        */
/* ------------------------------------------------------------------ */

/**
 * Bereitet das Feld "Google-Kalender" im Dialog vor:
 *   - verbunden     → Auswahlliste aus dem Google-Konto
 *   - sonst         → Texteingabe für die Kalender-ID
 * Label (for=) und Hinweistext folgen dem jeweils sichtbaren Feld.
 *
 * @param {?string} currentId - Aktuell zugeordnete Kalender-ID.
 */
function prepareGoogleField(currentId) {
    gcalOriginal = currentId || "";
    document.getElementById("m-gcal-input").value = gcalOriginal;
    showGoogleCheckResult(null);
    const connected = Boolean(googleStatus && googleStatus.connected);
    if (connected && !googleCalendars && !googleCalendarsError) {
        // Liste lädt noch (oder wurde noch nie geladen) → Platzhalter, danach füllen.
        showGoogleField("select", "Kalender werden geladen …");
        const select = document.getElementById("m-gcal-select");
        select.replaceChildren(new Option("Kalender werden geladen …", ""));
        select.disabled = true;
        loadGoogleCalendars().then(() => {
            // Nur füllen, wenn der Dialog noch offen ist (sonst beim nächsten Öffnen).
            if (document.getElementById("manual-modal").open) fillGoogleField();
        });
        return;
    }
    fillGoogleField();
}

/**
 * Füllt das Feld anhand des aktuellen Cache-Zustands (Liste, Fehler,
 * nicht verbunden). Der bisherige Wert bleibt immer auswählbar.
 */
function fillGoogleField() {
    const connected = Boolean(googleStatus && googleStatus.connected);
    if (!connected || !googleCalendars) {
        let hint;
        if (connected && googleCalendarsError) {
            hint = `Kalenderliste nicht verfügbar (${googleCalendarsError}). Kalender-ID bitte von Hand eintragen.`;
        } else if (googleStatus && googleStatus.configured) {
            hint = "Google ist nicht verbunden – Kalender-ID von Hand eintragen. Bei persönlichen Kalendern ist das meist die Gmail-Adresse, sonst steht sie in Google Kalender unter Einstellungen → „Kalender integrieren“.";
        } else {
            hint = "Kalender-ID von Hand eintragen – bei persönlichen Kalendern meist die Gmail-Adresse.";
        }
        showGoogleField("input", hint);
        return;
    }

    const select = document.getElementById("m-gcal-select");
    const options = [new Option("– Kein Kalender –", "")];
    googleCalendars.forEach(c => {
        const role = GOOGLE_ACCESS_ROLES[c.access_role] || c.access_role || "unbekannt";
        const name = `${c.summary || c.id}${c.primary ? " (Hauptkalender)" : ""}`;
        // new Option(text, value) setzt beides als Text → kein HTML aus Google-Daten.
        options.push(new Option(`${name} – ${role}`, c.id));
    });
    // Bisherige Zuordnung behalten, auch wenn der Kalender nicht (mehr) in der Liste steht.
    if (gcalOriginal && !googleCalendars.some(c => c.id === gcalOriginal)) {
        options.splice(1, 0, new Option(`Aktuell: ${gcalOriginal}`, gcalOriginal));
    }
    select.replaceChildren(...options);
    select.disabled = false;
    select.value = gcalOriginal;
    const n = googleCalendars.length;
    showGoogleField("select", n === 0
        ? "Im verbundenen Google-Konto wurden keine Kalender gefunden."
        : `Auswahl aus dem verbundenen Google-Konto (${n === 1 ? "1 Kalender" : `${n} Kalender`}).`);
}

/**
 * Blendet Auswahl bzw. Texteingabe ein und setzt Label + Hinweis.
 * @param {"select"|"input"} mode
 * @param {string} hint - Text unter dem Feld.
 */
function showGoogleField(mode, hint) {
    const select = document.getElementById("m-gcal-select");
    const input = document.getElementById("m-gcal-input");
    select.hidden = mode !== "select";
    input.hidden = mode !== "input";
    document.getElementById("m-gcal-label").htmlFor = mode === "select" ? select.id : input.id;
    document.getElementById("m-gcal-status").textContent = hint;
}

/**
 * Liefert die im Dialog gewählte Kalender-ID ("" = keine).
 * Lädt die Liste noch, gilt der bisherige Wert – sonst würde ein schnelles
 * Speichern die Zuordnung versehentlich löschen.
 * @returns {string}
 */
function getGoogleFieldValue() {
    const select = document.getElementById("m-gcal-select");
    if (!select.hidden) return select.disabled ? gcalOriginal : select.value;
    return document.getElementById("m-gcal-input").value.trim();
}

/**
 * Prüft, ob das verbundene Konto auf den gewählten Kalender zugreifen kann.
 * Spricht mit: POST /api/v1/google/calendars/check {calendar_id}
 *   → {ok: true, access_role, message} bzw. {ok: false, message}
 * @param {HTMLButtonElement} btn
 */
async function checkGoogleCalendar(btn) {
    const calendarId = getGoogleFieldValue();
    if (!calendarId) {
        showGoogleCheckResult("Bitte zuerst einen Kalender auswählen oder eine Kalender-ID eintragen.", "warning");
        return;
    }
    showGoogleCheckResult(null);
    setBusy(btn, true, "Prüft …");
    try {
        const res = await apiFetch("/api/v1/google/calendars/check", { method: "POST", body: { calendar_id: calendarId } });
        const data = await readJson(res);
        if (res.ok) {
            showGoogleCheckResult(data.message || (data.ok ? "Zugriff auf den Kalender bestätigt." : "Kein Zugriff auf diesen Kalender."), data.ok ? "success" : "error");
        } else {
            showGoogleCheckResult(data.error || "Die Prüfung ist fehlgeschlagen.", "error");
        }
    } catch (err) {
        showGoogleCheckResult("Netzwerkfehler.", "error");
    }
    setBusy(btn, false);
}

/**
 * Zeigt das Prüfergebnis direkt im Dialog an. Ein Toast wäre hier nicht
 * lesbar: showModal() legt den Dialog in den Top-Layer, über alle Toasts.
 * @param {?string} message - null blendet die Meldung aus.
 * @param {"success"|"error"|"warning"} [type="success"]
 */
function showGoogleCheckResult(message, type = "success") {
    const box = document.getElementById("m-gcal-result");
    box.hidden = !message;
    if (!message) return;
    box.className = `alert alert-${type} mt-2`;
    box.setAttribute("role", type === "error" ? "alert" : "status");
    box.textContent = message; // Text aus der API → nie als HTML
}

/* ------------------------------------------------------------------ */
/* Seitenstart                                                        */
/* ------------------------------------------------------------------ */

document.addEventListener("DOMContentLoaded", async () => {
    const me = await window.currentUserPromise;
    if (!me) return; // app.js leitet bereits auf /login um
    viewerRole = me.role;

    handleGoogleReturn();
    loadUsers();
    loadGoogleStatus();
    setupCsvImport();
    setupManualForm();
    document.getElementById("m-gcal-check").addEventListener("click", (e) => checkGoogleCalendar(e.currentTarget));
    // Anderer Kalender → altes Prüfergebnis gilt nicht mehr.
    document.getElementById("m-gcal-select").addEventListener("change", () => showGoogleCheckResult(null));
    document.getElementById("m-gcal-input").addEventListener("input", () => showGoogleCheckResult(null));
    // Event-Delegation: EIN Listener an der Tabelle statt einer pro Button.
    document.getElementById("users-table-body").addEventListener("click", onUserTableClick);
    document.getElementById("member-search").addEventListener("input", renderUsers);
    document.getElementById("member-role-filter").addEventListener("change", renderUsers);
    document.getElementById("member-gcal-filter").addEventListener("change", renderUsers);
});
