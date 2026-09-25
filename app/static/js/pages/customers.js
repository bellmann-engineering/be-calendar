/**
 * =====================================================================
 * Datei: app/static/js/pages/customers.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Logik der Kundenverwaltung (customers.html, nur CEO/ADMIN):
 *   Liste mit Suche, Anlegen/Bearbeiten mit Farbwahl, Kürzeln und Logo, Löschen.
 *
 * Mit welchen Backend-Endpunkten spricht diese Datei?
 *   GET    /api/v1/customers             → Liste [{id, name, email, color_hex, short_codes, logo_url}]
 *   POST   /api/v1/customers             → neuen Kunden anlegen
 *   PUT    /api/v1/customers/<id>        → Kunden bearbeiten
 *   DELETE /api/v1/customers/<id>        → Kunden löschen
 *   PUT    /api/v1/customers/<id>/logo   → Logo hochladen (multipart, Feld "file")
 *   DELETE /api/v1/customers/<id>/logo   → Logo entfernen
 *
 * Abhängigkeiten:
 *   app.js (apiFetch, readJson, isValidHexColor, DEFAULT_EVENT_COLOR),
 *   ui.js (h, icon, emptyRow, toast, confirmDialog, openDialog,
 *   closeDialog, setBusy, showFormError, hideFormError, readableTextColor).
 *
 * Sicherheit:
 *   Name/E-Mail werden als Text eingefügt. Farben werden auf #RRGGBB
 *   geprüft und nur über element.style (CSSOM) gesetzt – CSP-konform.
 * =====================================================================
 */

/**
 * Zwischenspeicher der geladenen Kunden (ID → Kunde).
 * @type {Map<number, object>}
 */
const customersById = new Map();

/** Anzahl Tabellenspalten (für leere Zustände). */
const CUSTOMER_COLUMNS = 5;

/** Logo-Auswahl im Dialog: neue Datei, "entfernen" gewählt, Objekt-URL der Vorschau. */
const logoState = { file: null, remove: false, previewUrl: null };

/** Farbvorschläge: gut unterscheidbar und mit weißer Schrift lesbar. */
const COLOR_PRESETS = [
    ["#2B6CB0", "Bellmann-Blau"], ["#1A365D", "Navy"], ["#0F766E", "Petrol"], ["#15803D", "Grün"],
    ["#B45309", "Bernstein"], ["#C2410C", "Orange"], ["#BE123C", "Rot"], ["#7E22CE", "Violett"],
    ["#475569", "Schiefer"],
];

/**
 * Färbt ein Element sicher über das CSSOM ein (kein style-Attribut im HTML).
 * @param {HTMLElement} el
 * @param {string} color - bereits validierte Farbe #RRGGBB.
 */
function paint(el, color) {
    el.style.backgroundColor = color;
    el.style.color = readableTextColor(color);
}

/* ------------------------------------------------------------------ */
/* Liste                                                              */
/* ------------------------------------------------------------------ */

/**
 * Lädt alle Kunden und zeichnet die Tabelle.
 * Spricht mit: GET /api/v1/customers
 */
async function loadCustomersTable() {
    const tbody = document.getElementById("c-tbody");
    try {
        const res = await apiFetch("/api/v1/customers");
        if (!res.ok) {
            tbody.replaceChildren(emptyRow(CUSTOMER_COLUMNS, "lock", "Keine Berechtigung",
                "Diese Seite ist nur für CEO und Administration verfügbar."));
            return;
        }
        const data = await readJson(res);
        customersById.clear();
        (Array.isArray(data) ? data : []).forEach(c => customersById.set(Number(c.id), c));
        renderCustomers();
    } catch (err) {
        tbody.replaceChildren(emptyRow(CUSTOMER_COLUMNS, "alert", "Netzwerkfehler", "Die Liste konnte nicht geladen werden."));
    } finally {
        tbody.removeAttribute("aria-busy");
    }
}

/**
 * Zeichnet die Tabelle (gefiltert nach dem Suchfeld).
 */
function renderCustomers() {
    const tbody = document.getElementById("c-tbody");
    const query = document.getElementById("customer-search").value.trim().toLowerCase();
    const all = Array.from(customersById.values());
    const visible = all.filter(c => !query || `${c.name} ${c.email || ""} ${(c.short_codes || []).join(" ")}`.toLowerCase().includes(query));
    document.getElementById("customer-count").textContent =
        visible.length === all.length ? `${all.length} Kunden` : `${visible.length} von ${all.length} Kunden`;

    if (visible.length === 0) {
        const addBtn = h("button", { type: "button", class: "btn btn-primary btn-sm", on: { click: () => openCustomerModal() } },
            icon("plus"), "Kunde anlegen");
        tbody.replaceChildren(all.length === 0
            ? emptyRow(CUSTOMER_COLUMNS, "building", "Noch keine Kunden", "Kunden geben Terminen im Kalender ihre Farbe.", addBtn)
            : emptyRow(CUSTOMER_COLUMNS, "search", "Keine Treffer", "Kein Kunde entspricht der Suche."));
        return;
    }
    tbody.replaceChildren(...visible.map(customerRow));
}

/**
 * Baut eine Tabellenzeile für einen Kunden.
 * @param {object} c - Kunde aus der API.
 * @returns {HTMLTableRowElement}
 */
function customerRow(c) {
    // Ungültige Farben fallen auf die Standardfarbe zurück.
    const color = isValidHexColor(c.color_hex) ? c.color_hex : DEFAULT_EVENT_COLOR;
    // Logo (falls vorhanden) statt des Anfangsbuchstabens.
    let monogram;
    if (c.logo_url) {
        monogram = h("span", { class: "flex h-9 w-14 shrink-0 items-center justify-center rounded-lg border border-line bg-white p-1" },
            h("img", { src: c.logo_url, alt: "", class: "max-h-full max-w-full object-contain" }));
    } else {
        monogram = h("span", {
            class: "flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold",
            "aria-hidden": "true", text: (c.name || "?").trim().charAt(0).toUpperCase(),
        });
        paint(monogram, color);
    }
    const codes = (c.short_codes || []).length
        ? h("span", { class: "flex flex-wrap gap-1" }, ...c.short_codes.map(code => h("span", { class: "badge badge-gray font-mono", text: code })))
        : h("span", { class: "text-fg-subtle", text: "–" });
    const swatch = h("span", { class: "size-3.5 rounded-full ring-1 ring-black/10", "aria-hidden": "true" });
    swatch.style.backgroundColor = color;

    const action = (name, iconName, label, extraClass = "") => h("button", {
        type: "button", class: `btn-icon btn-icon-sm ${extraClass}`,
        "aria-label": `${label}: ${c.name}`, title: label, dataset: { action: name, id: c.id },
    }, icon(iconName));

    // relative: auf dem Smartphone stehen die Aktionen oben rechts in der Karte.
    return h("tr", { class: "relative" },
        h("td", { class: "pr-24 md:pr-5" },
            h("div", { class: "flex items-center gap-3" }, monogram,
                h("div", { class: "min-w-0" },
                    h("p", { class: "truncate font-medium text-fg", text: c.name }),
                    h("p", { class: "truncate text-xs text-fg-muted md:hidden", text: c.email || "Keine E-Mail" }),
                ),
            ),
        ),
        h("td", { class: "mt-2 block md:mt-0 md:table-cell" },
            h("span", { class: "md:hidden text-xs text-fg-muted", text: "Kürzel: " }), codes),
        h("td", { class: "hidden text-fg-muted md:table-cell", text: c.email || "–" }),
        h("td", { class: "mt-2 hidden md:table-cell" },
            h("span", { class: "inline-flex items-center gap-2 font-mono text-xs text-fg-muted uppercase" }, swatch, color)),
        h("td", { class: "absolute top-3 right-3 md:static md:text-right" },
            h("div", { class: "flex gap-0.5 md:justify-end" },
                action("edit", "pencil", "Bearbeiten"),
                action("delete", "trash", "Löschen", "btn-icon-danger"),
            ),
        ),
    );
}

/**
 * Löscht einen Kunden nach Rückfrage.
 * Spricht mit: DELETE /api/v1/customers/<id>
 * @param {object} customer
 */
async function deleteCustomer(customer) {
    const ok = await confirmDialog({
        title: "Kunde löschen?",
        message: `„${customer.name}“ wird entfernt. Bestehende Termine behalten ihren Inhalt, verlieren aber die Kundenfarbe.`,
        confirmText: "Löschen",
    });
    if (!ok) return;
    const res = await apiFetch(`/api/v1/customers/${encodeURIComponent(customer.id)}`, { method: "DELETE" });
    if (res.ok) {
        toast("Kunde gelöscht.");
    } else {
        const data = await readJson(res);
        toast(data.error || "Kunde konnte nicht gelöscht werden.", "error");
    }
    loadCustomersTable();
}

/* ------------------------------------------------------------------ */
/* Dialog                                                             */
/* ------------------------------------------------------------------ */

/**
 * Aktualisiert Farbvorschau und die Markierung des gewählten Vorschlags.
 */
function updateColorPreview() {
    const value = document.getElementById("c-color").value;
    const color = isValidHexColor(value) ? value : DEFAULT_EVENT_COLOR;
    const preview = document.getElementById("c-preview");
    preview.textContent = document.getElementById("c-name").value.trim() || "Vorschau";
    paint(preview, color);
    document.querySelectorAll("#c-swatches [data-color]").forEach(btn => {
        btn.setAttribute("aria-pressed", String(btn.dataset.color.toLowerCase() === color.toLowerCase()));
    });
}

/**
 * Erzeugt die runden Farbvorschläge (einmalig beim Seitenstart).
 */
function renderSwatches() {
    const container = document.getElementById("c-swatches");
    container.replaceChildren(...COLOR_PRESETS.map(([color, name]) => {
        const btn = h("button", {
            type: "button", class: "swatch", title: name,
            "aria-label": `Farbe ${name}`, "aria-pressed": "false", dataset: { color },
            on: {
                click: () => {
                    document.getElementById("c-color").value = color.toLowerCase();
                    updateColorPreview();
                },
            },
        });
        btn.style.backgroundColor = color;
        return btn;
    }));
}

/**
 * Zeigt das Logo im Dialog: gewählte Datei, sonst das gespeicherte, sonst "kein Logo".
 * @param {?string} url
 */
function showLogoPreview(url) {
    const img = document.getElementById("c-logo-preview");
    img.hidden = !url;
    if (url) img.src = url; else img.removeAttribute("src");
    document.getElementById("c-logo-empty").hidden = Boolean(url);
    document.getElementById("c-logo-remove").hidden = !url;
}

/** Gibt die Objekt-URL der Vorschau frei (sonst bleibt die Datei im Speicher). */
function resetLogoState() {
    if (logoState.previewUrl) URL.revokeObjectURL(logoState.previewUrl);
    Object.assign(logoState, { file: null, remove: false, previewUrl: null });
}

/**
 * Öffnet den Kunden-Dialog – leer (neu) oder befüllt (bearbeiten).
 * @param {object|null} customer
 */
function openCustomerModal(customer = null) {
    resetLogoState();
    document.getElementById("c-form").reset();
    document.getElementById("c-id").value = customer ? customer.id : "";
    document.getElementById("c-name").value = customer ? customer.name : "";
    document.getElementById("c-email").value = customer ? (customer.email || "") : "";
    document.getElementById("c-codes").value = customer ? (customer.short_codes || []).join(", ") : "";
    showLogoPreview(customer ? customer.logo_url : null);
    document.getElementById("c-color").value =
        (customer && isValidHexColor(customer.color_hex) ? customer.color_hex : DEFAULT_EVENT_COLOR).toLowerCase();
    document.getElementById("c-modal-title").textContent = customer ? "Kunde bearbeiten" : "Kunde anlegen";
    hideFormError("c-err");
    updateColorPreview();
    openDialog("c-modal");
    document.getElementById("c-name").focus();
}

/**
 * Speichern. Spricht mit: POST /api/v1/customers bzw. PUT /api/v1/customers/<id>
 * @param {SubmitEvent} e
 */
async function submitCustomer(e) {
    e.preventDefault();
    hideFormError("c-err");
    const nameInput = document.getElementById("c-name");
    const emailInput = document.getElementById("c-email");
    if (!nameInput.value.trim()) {
        nameInput.setAttribute("aria-invalid", "true");
        showFormError("c-err", "Bitte gib einen Namen ein.");
        nameInput.focus();
        return;
    }
    nameInput.removeAttribute("aria-invalid");
    if (!emailInput.checkValidity()) {
        emailInput.setAttribute("aria-invalid", "true");
        showFormError("c-err", "Bitte gib eine gültige E-Mail-Adresse ein.");
        emailInput.focus();
        return;
    }
    emailInput.removeAttribute("aria-invalid");

    const id = document.getElementById("c-id").value;
    const payload = {
        name: nameInput.value.trim(),
        email: emailInput.value.trim(),
        color_hex: document.getElementById("c-color").value,
        short_codes: document.getElementById("c-codes").value,
    };
    const submit = document.getElementById("c-submit");
    setBusy(submit, true, "Speichert …");
    try {
        const res = await apiFetch(id ? `/api/v1/customers/${encodeURIComponent(id)}` : "/api/v1/customers", {
            method: id ? "PUT" : "POST",
            body: payload,
        });
        if (res.ok) {
            const saved = await readJson(res);
            const logoError = await saveLogo(id || saved.id);
            if (logoError) {
                // Kunde ist gespeichert, nur das Logo nicht → Dialog offen lassen.
                document.getElementById("c-id").value = id || saved.id;
                showFormError("c-err", logoError);
                loadCustomersTable();
                setBusy(submit, false);
                return;
            }
            closeDialog("c-modal");
            resetLogoState();
            toast(id ? "Kunde aktualisiert." : "Kunde angelegt.");
            loadCustomersTable();
        } else {
            const data = await readJson(res);
            showFormError("c-err", data.error || "Kunde konnte nicht gespeichert werden.");
        }
    } catch (err) {
        showFormError("c-err", "Netzwerkfehler.");
    }
    setBusy(submit, false);
}

/**
 * Lädt ein neu gewähltes Logo hoch bzw. entfernt es (nach dem Speichern der Daten).
 * Spricht mit: PUT / DELETE /api/v1/customers/<id>/logo
 * @param {number|string} customerId
 * @returns {Promise<?string>} Fehlermeldung oder null.
 */
async function saveLogo(customerId) {
    if (!customerId) return null;
    try {
        if (logoState.file) {
            const form = new FormData();
            form.append("file", logoState.file);
            const res = await apiFetch(`/api/v1/customers/${encodeURIComponent(customerId)}/logo`, { method: "PUT", body: form });
            if (!res.ok) return (await readJson(res)).error || "Logo konnte nicht gespeichert werden.";
        } else if (logoState.remove) {
            const res = await apiFetch(`/api/v1/customers/${encodeURIComponent(customerId)}/logo`, { method: "DELETE" });
            if (!res.ok) return (await readJson(res)).error || "Logo konnte nicht entfernt werden.";
        }
    } catch (err) {
        return "Netzwerkfehler beim Speichern des Logos.";
    }
    return null;
}

/**
 * Datei gewählt: prüfen (Typ, Größe) und als Vorschau anzeigen.
 * Gespeichert wird erst mit "Speichern".
 * @param {Event} e
 */
function onLogoChosen(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = ""; // dieselbe Datei erneut wählbar
    if (!file) return;
    hideFormError("c-err");
    if (!["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type)) {
        showFormError("c-err", "Bitte ein PNG-, JPEG-, WebP- oder GIF-Bild wählen.");
        return;
    }
    if (file.size > 2 * 1024 * 1024) {
        showFormError("c-err", "Das Bild ist größer als 2 MB.");
        return;
    }
    resetLogoState();
    logoState.file = file;
    logoState.previewUrl = URL.createObjectURL(file);
    showLogoPreview(logoState.previewUrl);
}

/* ------------------------------------------------------------------ */
/* Seitenstart                                                        */
/* ------------------------------------------------------------------ */

document.addEventListener("DOMContentLoaded", async () => {
    const me = await window.currentUserPromise;
    if (!me) return; // Umleitung auf /login erledigt app.js

    renderSwatches();
    loadCustomersTable();

    document.getElementById("open-customer-btn").addEventListener("click", () => openCustomerModal());
    document.getElementById("c-form").addEventListener("submit", submitCustomer);
    document.getElementById("c-color").addEventListener("input", updateColorPreview);
    document.getElementById("c-name").addEventListener("input", updateColorPreview);
    document.getElementById("customer-search").addEventListener("input", renderCustomers);
    document.getElementById("c-logo").addEventListener("change", onLogoChosen);
    document.getElementById("c-logo-remove").addEventListener("click", () => {
        resetLogoState();
        logoState.remove = true;
        showLogoPreview(null);
    });

    // Event-Delegation für Bearbeiten/Löschen in der Tabelle.
    document.getElementById("c-tbody").addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-action]");
        if (!btn) return;
        const customer = customersById.get(Number(btn.dataset.id));
        if (!customer) return;
        if (btn.dataset.action === "edit") openCustomerModal(customer);
        if (btn.dataset.action === "delete") deleteCustomer(customer);
    });
});
