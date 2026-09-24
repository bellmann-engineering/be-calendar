/**
 * =====================================================================
 * Datei: app/static/js/pages/members.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Logik der Mitarbeiterverwaltung (members.html, nur CEO/ADMIN):
 *   Liste mit Suche/Filter, Anlegen/Bearbeiten, CSV-Import,
 *   Aktivieren/Deaktivieren, Rechte entziehen, Löschen.
 *
 * Mit welchen Backend-Endpunkten spricht diese Datei?
 *   GET    /api/v1/auth                        → Benutzerliste
 *   POST   /api/v1/auth/users                  → Benutzer anlegen
 *   PUT    /api/v1/auth/users/<id>             → Benutzer bearbeiten
 *   DELETE /api/v1/auth/users/<id>             → Benutzer löschen
 *   PUT    /api/v1/auth/<id>/status            → aktiv/gesperrt umschalten
 *   PUT    /api/v1/auth/users/<id>/revoke-role → Rolle auf TRAINER zurücksetzen
 *   POST   /api/v1/auth/csv                    → CSV-Import (multipart "file")
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
const MEMBER_COLUMNS = 5;

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
        renderUsers();
    } catch (err) {
        tbody.replaceChildren(emptyRow(MEMBER_COLUMNS, "alert", "Netzwerkfehler", "Die Liste konnte nicht geladen werden."));
    } finally {
        tbody.removeAttribute("aria-busy");
    }
}

/**
 * Zeichnet die Tabelle anhand von Suche und Rollenfilter neu.
 */
function renderUsers() {
    const tbody = document.getElementById("users-table-body");
    const query = document.getElementById("member-search").value.trim().toLowerCase();
    const role = document.getElementById("member-role-filter").value;
    const all = Array.from(usersById.values());
    const visible = all.filter(u => {
        if (role && u.role !== role) return false;
        if (!query) return true;
        return `${u.first_name} ${u.last_name} ${u.email}`.toLowerCase().includes(query);
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
    document.getElementById("m-role").value = isEdit ? user.role : "TRAINER";
    document.getElementById("m-pass").required = !isEdit;
    document.getElementById("m-pass-hint").textContent = isEdit ? "(leer lassen = unverändert)" : "";
    document.getElementById("manual-modal-title").textContent = isEdit ? "Mitarbeiter bearbeiten" : "Mitarbeiter anlegen";
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
/* Seitenstart                                                        */
/* ------------------------------------------------------------------ */

document.addEventListener("DOMContentLoaded", async () => {
    const me = await window.currentUserPromise;
    if (!me) return; // app.js leitet bereits auf /login um
    viewerRole = me.role;

    loadUsers();
    setupCsvImport();
    setupManualForm();
    // Event-Delegation: EIN Listener an der Tabelle statt einer pro Button.
    document.getElementById("users-table-body").addEventListener("click", onUserTableClick);
    document.getElementById("member-search").addEventListener("input", renderUsers);
    document.getElementById("member-role-filter").addEventListener("change", renderUsers);
});
