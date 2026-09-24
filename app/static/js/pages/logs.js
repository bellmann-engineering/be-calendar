/**
 * =====================================================================
 * Datei: app/static/js/pages/logs.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Logik des Audit-Logs (logs.html, nur CEO/ADMIN): Laden aller
 *   Einträge, Filter im Browser (sofort, ohne neue Server-Anfrage),
 *   lesbare Darstellung der Details und etappenweises Rendern.
 *
 * Mit welchem Backend-Endpunkt spricht diese Datei?
 *   GET /api/v1/events/audit
 *     → [{timestamp, user_name, role, action, details}]
 *       `details` ist ein JSON-Objekt (oder null) aus audit_logs.details_json.
 *
 * Abhängigkeiten:
 *   app.js (apiFetch, readJson, roleLabel), ui.js (h, icon, emptyRow).
 *
 * Sicherheit:
 *   Details enthalten Benutzertexte. JEDER Wert – auch Schlüsselnamen –
 *   wird über h() als Textknoten eingefügt; es gibt kein innerHTML.
 * =====================================================================
 */

/** Alle vom Server geladenen Log-Einträge (Filter arbeiten auf dieser Kopie). */
let globalLogs = [];

/** Aktuell gefilterte Einträge und wie viele davon schon gezeichnet sind. */
let filteredLogs = [];
let renderedCount = 0;

/** So viele Zeilen werden pro Etappe gezeichnet (hält die Seite flüssig). */
const PAGE_SIZE = 100;

/** Anzahl Tabellenspalten. */
const LOG_COLUMNS = 4;

/** Formatierer für Zeitstempel (deutsch, mit Sekunden). */
const FMT_STAMP_DATE = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
const FMT_STAMP_TIME = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** Deutsche Bezeichnungen für bekannte Detail-Schlüssel. */
const DETAIL_LABELS = {
    title: "Termin-Titel", start_time: "Beginn", end_time: "Ende",
    assigned_to_id: "Zugewiesener Mitarbeiter (ID)", buffer_before_mins: "Puffer vorher (Min.)",
    buffer_after_mins: "Puffer nachher (Min.)", reallocation_required: "Neu zuzuweisen?",
    description: "Beschreibung", conflict_overridden: "Konflikt übergangen?",
    conflicting_event_id: "ID des kollidierenden Termins",
};

/**
 * Kategorie einer Aktion (für Filter und Badge-Farbe).
 * @param {string} action - z. B. "CREATE_EVENT".
 * @returns {"CEO"|"RSVP"|"EVENT"|"USER_TEAM"|"OTHER"}
 */
function actionCategory(action) {
    const act = action || "";
    if (act.includes("CEO")) return "CEO";
    if (act.includes("RSVP")) return "RSVP";
    if (act.includes("EVENT")) return "EVENT";
    if (["USER", "TEAM", "ASSIGN", "ROLE"].some(kw => act.includes(kw))) return "USER_TEAM";
    return "OTHER";
}

/** Badge-Farbe je Kategorie. */
const CATEGORY_BADGES = { CEO: "badge-red", RSVP: "badge-violet", EVENT: "badge-blue", USER_TEAM: "badge-amber", OTHER: "badge-gray" };

/* ------------------------------------------------------------------ */
/* Filter                                                             */
/* ------------------------------------------------------------------ */

/**
 * Befüllt die Auswahlfelder Mitarbeiter/Rolle/Aktion mit den Werten,
 * die in den geladenen Logs tatsächlich vorkommen.
 * `new Option(text, value)` setzt den Text sicher (kein HTML).
 *
 * @param {object[]} logs
 */
function populateDropdowns(logs) {
    const users = new Set(), roles = new Set(), actions = new Set();
    logs.forEach(l => {
        if (l.user_name) users.add(l.user_name);
        if (l.role) roles.add(l.role);
        if (l.action) actions.add(l.action);
    });
    const userSel = document.getElementById("f-user");
    const roleSel = document.getElementById("f-role");
    const actionSel = document.getElementById("f-action");
    Array.from(users).sort().forEach(u => userSel.add(new Option(u, u)));
    Array.from(roles).sort().forEach(r => roleSel.add(new Option(roleLabel(r), r)));
    Array.from(actions).sort().forEach(a => actionSel.add(new Option(a, a)));
}

/**
 * Wendet alle Filter auf globalLogs an und zeichnet das Ergebnis neu.
 * Der Server liefert die Einträge bereits "neueste zuerst".
 */
function applyFilters() {
    const value = id => document.getElementById(id).value;
    const search = value("f-search").trim().toLowerCase();
    const dateFrom = value("f-date-from");
    const dateTo = value("f-date-to");
    const user = value("f-user");
    const role = value("f-role");
    const action = value("f-action");
    const category = value("f-category");
    const sort = value("f-sort");

    filteredLogs = globalLogs.filter(l => {
        const act = l.action || "";
        if (search) {
            const rowText = `${l.user_name} ${l.role} ${act} ${JSON.stringify(l.details)}`.toLowerCase();
            if (!rowText.includes(search)) return false;
        }
        const logDate = new Date(l.timestamp);
        // "YYYY-MM-DDT00:00" ohne Offset = lokale Mitternacht (nicht UTC!)
        if (dateFrom && logDate < new Date(`${dateFrom}T00:00:00`)) return false;
        if (dateTo && logDate > new Date(`${dateTo}T23:59:59`)) return false;
        if (user && l.user_name !== user) return false;
        if (role && l.role !== role) return false;
        if (action && act !== action) return false;
        if (category && actionCategory(act) !== category) return false;
        return true;
    });
    // slice() vor reverse(), damit globalLogs selbst nicht umgedreht wird.
    if (sort === "asc") filteredLogs = filteredLogs.slice().reverse();

    // Anzahl aktiver Filter im eingeklappten Kopf anzeigen (Sortierung zählt nicht).
    const active = [search, dateFrom, dateTo, user, role, action, category].filter(Boolean).length;
    const badge = document.getElementById("active-filter-count");
    badge.hidden = active === 0;
    badge.textContent = `${active} aktiv`;

    document.getElementById("results-count").textContent =
        `${filteredLogs.length} von ${globalLogs.length} Einträgen`;
    renderedCount = 0;
    document.getElementById("logs-table-body").replaceChildren();
    renderMore();
}

/* ------------------------------------------------------------------ */
/* Darstellung                                                        */
/* ------------------------------------------------------------------ */

/**
 * Lesbare Bezeichnung für einen Detail-Schlüssel.
 * @param {string} key
 * @returns {string}
 */
function translateKey(key) {
    return DETAIL_LABELS[key] || String(key).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

/**
 * Formatiert einen Detailwert als lesbaren TEXT (kein HTML).
 * ISO-Zeitstempel werden in deutsche Lokalzeit umgerechnet.
 *
 * @param {*} v
 * @returns {string}
 */
function formatValue(v) {
    if (v === null || v === undefined || v === "") return "leer";
    if (v === true) return "Ja";
    if (v === false) return "Nein";
    if (Array.isArray(v)) return v.length > 0 ? v.join(", ") : "keine";
    if (typeof v === "object") return JSON.stringify(v);
    if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) {
        const d = new Date(v);
        if (!isNaN(d.getTime())) {
            return d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) + " Uhr";
        }
    }
    return String(v);
}

/**
 * Eine Zeile "Bezeichnung: Inhalt" in den Details.
 * @param {string} key
 * @param {...Node|string} content
 * @returns {HTMLElement}
 */
function detailLine(key, ...content) {
    return h("div", { class: "grid gap-0.5 sm:grid-cols-[13rem_minmax(0,1fr)] sm:gap-3" },
        h("span", { class: "text-xs font-medium text-fg-muted sm:text-sm", text: translateKey(key) }),
        h("span", { class: "min-w-0 break-words text-fg" }, ...content),
    );
}

/**
 * Baut die Darstellung der Details eines Log-Eintrags.
 * Drei Fälle:
 *   1. Update  → {previous, new}: nur geänderte Felder als "alt → neu"
 *   2. RSVP    → {previous_status, new_status, rejection_reason}
 *   3. Sonst   → alle Schlüssel/Werte als Liste
 *
 * @param {object|string|null} details
 * @returns {Node}
 */
function formatAuditDetails(details) {
    if (!details) return h("span", { class: "text-fg-subtle italic", text: "Keine Details" });

    // Fallback für ältere Einträge, bei denen die Details nur als Text vorliegen.
    if (typeof details === "string") {
        try { details = JSON.parse(details); }
        catch (e) { return h("span", { class: "font-mono text-xs break-all text-fg-muted", text: details }); }
    }
    if (typeof details !== "object") return document.createTextNode(String(details));

    const box = h("div", { class: "space-y-2 text-sm" });

    // FALL 1: Feldänderungen (Update)
    if (details.previous && details.new) {
        let changed = 0;
        for (const key of Object.keys(details.new)) {
            const oldVal = details.previous[key];
            const newVal = details.new[key];
            if (JSON.stringify(oldVal) === JSON.stringify(newVal)) continue;
            changed += 1;
            box.append(detailLine(key,
                h("span", { class: "inline-flex flex-wrap items-center gap-1.5" },
                    h("del", { class: "rounded bg-danger-soft px-1.5 py-0.5 text-xs text-danger", text: formatValue(oldVal) }),
                    icon("arrow-right", "size-3.5 text-fg-subtle"),
                    h("ins", { class: "rounded bg-success-soft px-1.5 py-0.5 text-xs font-semibold text-success no-underline", text: formatValue(newVal) }),
                )));
        }
        if (!changed) box.append(h("span", { class: "text-fg-subtle italic", text: "Keine Felder verändert." }));
        if (details.conflict_overridden) {
            box.append(h("div", { class: "alert alert-warning py-2" }, icon("alert"),
                h("span", { text: "Ein Terminkonflikt wurde vom CEO bewusst übergangen." })));
        }
    }
    // FALL 2: Rückmeldungen (RSVP)
    else if (details.new_status || details.previous_status) {
        const declined = details.new_status === "DECLINED";
        box.append(h("div", { class: "flex flex-wrap items-center gap-1.5" },
            h("span", { class: "text-xs font-medium text-fg-muted", text: "Status:" }),
            h("span", { class: "badge badge-gray", text: details.previous_status || "NEU" }),
            icon("arrow-right", "size-3.5 text-fg-subtle"),
            h("span", { class: `badge ${declined ? "badge-red" : "badge-green"}`, text: details.new_status }),
        ));
        if (details.rejection_reason) {
            box.append(h("blockquote", {
                class: "rounded-lg border-l-4 border-danger bg-danger-soft px-3 py-2 text-sm break-words text-fg",
                text: `„${details.rejection_reason}“`,
            }));
        }
    }
    // FALL 3: Erstellung / allgemeine Informationen
    else {
        for (const [key, value] of Object.entries(details)) {
            if (value === null || value === "") continue;
            box.append(detailLine(key, formatValue(value)));
        }
        if (!box.childElementCount) box.append(h("span", { class: "text-fg-subtle italic", text: "Keine Details" }));
    }
    return box;
}

/**
 * Baut eine Tabellenzeile für einen Log-Eintrag.
 * @param {object} l
 * @returns {HTMLTableRowElement}
 */
function logRow(l) {
    const date = new Date(l.timestamp);
    const valid = !isNaN(date.getTime());
    return h("tr", { class: "md:align-top" },
        h("td", { class: "md:align-top" },
            h("time", { datetime: valid ? date.toISOString() : null, class: "tabular text-xs text-fg-muted" },
                h("span", { class: "font-medium text-fg", text: valid ? FMT_STAMP_DATE.format(date) : "–" }),
                " ", valid ? FMT_STAMP_TIME.format(date) : "")),
        h("td", { class: "md:align-top" },
            h("div", { class: "flex items-center gap-2.5" },
                h("span", { class: "avatar avatar-sm", "aria-hidden": "true", text: initials(...String(l.user_name || "").split(" ")) }),
                h("div", { class: "min-w-0" },
                    h("p", { class: "truncate font-medium text-fg", text: l.user_name || "System" }),
                    h("p", { class: "text-xs text-fg-muted", text: roleLabel(l.role) }),
                ),
            )),
        h("td", { class: "md:align-top" },
            h("span", { class: `badge ${CATEGORY_BADGES[actionCategory(l.action)]} font-mono text-[0.6875rem] tracking-wide`, text: l.action })),
        h("td", { class: "pt-2 md:pt-3.5" }, formatAuditDetails(l.details)),
    );
}

/**
 * Zeichnet die nächste Etappe (PAGE_SIZE Zeilen) der gefilterten Einträge.
 */
function renderMore() {
    const tbody = document.getElementById("logs-table-body");
    const moreWrap = document.getElementById("logs-more-wrap");
    if (filteredLogs.length === 0) {
        tbody.replaceChildren(globalLogs.length === 0
            ? emptyRow(LOG_COLUMNS, "logs", "Noch keine Einträge", "Sobald im System etwas passiert, erscheint es hier.")
            : emptyRow(LOG_COLUMNS, "filter", "Keine Treffer", "Kein Eintrag entspricht den gewählten Filtern."));
        moreWrap.hidden = true;
        return;
    }
    const next = filteredLogs.slice(renderedCount, renderedCount + PAGE_SIZE);
    tbody.append(...next.map(logRow));
    renderedCount += next.length;
    moreWrap.hidden = renderedCount >= filteredLogs.length;
    document.getElementById("logs-more").textContent =
        `Weitere ${Math.min(PAGE_SIZE, filteredLogs.length - renderedCount)} von ${filteredLogs.length - renderedCount} anzeigen`;
}

/**
 * Filterbereich auf-/zuklappen. Der Startzustand kommt aus dem CSS
 * (Smartphone zu, Desktop offen); hier wird nur der sichtbare Zustand
 * umgedreht und aria-expanded/Pfeil passend gesetzt.
 */
function setupFilterToggle() {
    const btn = document.getElementById("filter-toggle");
    const body = document.getElementById("filter-body");
    const chevron = document.getElementById("filter-chevron");
    const sync = () => {
        const open = body.offsetParent !== null; // sichtbar = aufgeklappt
        btn.setAttribute("aria-expanded", String(open));
        chevron.classList.toggle("rotate-180", open);
    };
    btn.addEventListener("click", () => {
        body.dataset.open = String(body.offsetParent === null);
        sync();
    });
    sync();
}

/* ------------------------------------------------------------------ */
/* Seitenstart                                                        */
/* ------------------------------------------------------------------ */

document.addEventListener("DOMContentLoaded", async () => {
    const me = await window.currentUserPromise;
    if (!me) return; // app.js leitet auf /login um

    setupFilterToggle();

    const tbody = document.getElementById("logs-table-body");
    try {
        const res = await apiFetch("/api/v1/events/audit");
        if (res.ok) {
            const data = await readJson(res);
            globalLogs = Array.isArray(data) ? data : [];
            populateDropdowns(globalLogs);
            applyFilters();
        } else {
            tbody.replaceChildren(emptyRow(LOG_COLUMNS, "lock", "Keine Berechtigung", "Das Audit-Log ist nur für CEO und Administration sichtbar."));
            document.getElementById("results-count").textContent = "";
        }
    } catch (err) {
        tbody.replaceChildren(emptyRow(LOG_COLUMNS, "alert", "Netzwerkfehler", "Das Audit-Log konnte nicht geladen werden."));
    } finally {
        tbody.removeAttribute("aria-busy");
    }

    // Jede Änderung an einem Filterfeld (ID beginnt mit "f-") filtert sofort neu.
    document.querySelectorAll('[id^="f-"]').forEach(el => el.addEventListener("input", applyFilters));
    document.getElementById("btn-reset-filters").addEventListener("click", () => {
        document.querySelectorAll('[id^="f-"]').forEach(el => { el.value = el.id === "f-sort" ? "desc" : ""; });
        applyFilters();
    });
    document.getElementById("logs-more").addEventListener("click", renderMore);
});
