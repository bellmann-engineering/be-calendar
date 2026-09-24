/**
 * =====================================================================
 * Datei: app/static/js/pages/reset-password.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Logik der Seite "Neues Passwort festlegen" (reset_password.html).
 *   Liest den Einmal-Token aus der URL (?token=...) und sendet ihn
 *   zusammen mit dem neuen Passwort an den Server.
 *
 * Mit welchem Backend-Endpunkt spricht diese Datei?
 *   POST /api/v1/auth/reset-password {token, password}
 *
 * Abhängigkeiten:
 *   app.js (apiFetch, readJson), ui.js (setBusy, showFormError,
 *   hideFormError, icon). Geladen von reset_password.html (defer).
 * =====================================================================
 */

/** Mindestlänge – muss mit der Server-Validierung übereinstimmen. */
const MIN_PASSWORD_LENGTH = 10;

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("reset-form");
    const submit = document.getElementById("reset-btn");
    const password = document.getElementById("new-password");
    const confirmation = document.getElementById("confirm-password");
    const rule = document.getElementById("password-rule");
    const ruleIcon = document.getElementById("password-rule-icon");
    // URLSearchParams dekodiert den Token korrekt (URL-sichere Zeichen).
    const token = new URLSearchParams(window.location.search).get("token");

    if (!token) {
        showFormError("reset-error", "Der Link ist ungültig oder unvollständig. Bitte fordere einen neuen an.");
        submit.disabled = true;
        return;
    }

    // Live-Feedback zur Mindestlänge: Icon + Farbe wechseln (nicht nur Farbe → WCAG 1.4.1).
    password.addEventListener("input", () => {
        const ok = password.value.length >= MIN_PASSWORD_LENGTH;
        rule.classList.toggle("text-success", ok);
        ruleIcon.replaceChildren(icon(ok ? "check-circle" : "info", "size-3.5"));
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideFormError("reset-error");

        // Clientseitige Prüfung nur für schnelles Feedback – der Server prüft erneut.
        if (password.value.length < MIN_PASSWORD_LENGTH) {
            password.setAttribute("aria-invalid", "true");
            showFormError("reset-error", `Das Passwort muss mindestens ${MIN_PASSWORD_LENGTH} Zeichen lang sein.`);
            return;
        }
        password.removeAttribute("aria-invalid");
        if (password.value !== confirmation.value) {
            confirmation.setAttribute("aria-invalid", "true");
            showFormError("reset-error", "Die Passwörter stimmen nicht überein.");
            return;
        }
        confirmation.removeAttribute("aria-invalid");

        setBusy(submit, true, "Speichert …");
        try {
            const res = await apiFetch("/api/v1/auth/reset-password", {
                method: "POST",
                body: { token, password: password.value },
            });
            const data = await readJson(res);
            if (res.ok) {
                document.getElementById("reset-panel").hidden = true;
                document.getElementById("reset-success-text").textContent =
                    data.message || "Dein Passwort wurde geändert. Du kannst dich jetzt anmelden.";
                document.getElementById("reset-success").hidden = false;
                return;
            }
            showFormError("reset-error", data.error || "Das Passwort konnte nicht geändert werden.");
        } catch (err) {
            showFormError("reset-error", "Netzwerkfehler oder Server nicht erreichbar.");
        }
        setBusy(submit, false);
    });
});
