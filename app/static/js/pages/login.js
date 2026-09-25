/**
 * =====================================================================
 * Datei: app/static/js/pages/login.js
 * ---------------------------------------------------------------------
 * Zweck:
 *   Logik der Anmeldeseite (login.html):
 *     1. Login-Formular absenden
 *     2. Passwort ein-/ausblenden
 *     3. Dialog "Passwort vergessen"
 *
 * Mit welchen Backend-Endpunkten spricht diese Datei?
 *   POST /api/v1/auth/login            {email, password}
 *        → Server setzt die HttpOnly-Cookies (JWT + CSRF), das Frontend
 *          muss sich nichts merken.
 *   POST /api/v1/auth/forgot-password  {email}
 *        → Antwort ist IMMER dieselbe neutrale Meldung (Schutz vor
 *          "User Enumeration"), egal ob das Konto existiert.
 *
 * Abhängigkeiten:
 *   app.js (apiFetch, readJson, loginTarget), ui.js (setBusy, showFormError,
 *   hideFormError, openDialog, icon). Geladen von login.html (defer).
 * =====================================================================
 */

/**
 * Login-Formular: Anmelden und bei Erfolg zum Kalender wechseln.
 * Fehler (401 falsche Daten, 429 zu viele Versuche) erscheinen als Text.
 */
function setupLoginForm() {
    const form = document.getElementById("login-form");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const emailInput = document.getElementById("email");
        const passwordInput = document.getElementById("password");
        const submit = document.getElementById("login-submit");
        hideFormError("login-error");
        [emailInput, passwordInput].forEach(el => el.removeAttribute("aria-invalid"));

        // Eigene Prüfung statt Browser-Blase: Meldung im Design und für Screenreader.
        if (!emailInput.value.trim() || !passwordInput.value) {
            if (!emailInput.value.trim()) emailInput.setAttribute("aria-invalid", "true");
            if (!passwordInput.value) passwordInput.setAttribute("aria-invalid", "true");
            showFormError("login-error", "Bitte E-Mail-Adresse und Passwort eingeben.");
            return;
        }

        setBusy(submit, true, "Anmelden …");
        try {
            const res = await apiFetch("/api/v1/auth/login", {
                method: "POST",
                body: { email: emailInput.value.trim(), password: passwordInput.value },
            });
            const data = await readJson(res);
            if (res.ok) {
                window.location.href = loginTarget(); // ?next= oder /dashboard (app.js)
                return; // Button bleibt im Lade-Zustand, bis die neue Seite da ist
            }
            showFormError("login-error", data.error || "Anmeldung fehlgeschlagen.");
            passwordInput.select();
        } catch (err) {
            showFormError("login-error", "Server nicht erreichbar. Bitte später erneut versuchen.");
        }
        setBusy(submit, false);
    });
}

/**
 * Augen-Button: Passwort im Klartext zeigen/verbergen.
 * aria-pressed teilt Screenreadern den Zustand mit.
 */
function setupPasswordToggle() {
    const btn = document.getElementById("toggle-password");
    const input = document.getElementById("password");
    if (!btn || !input) return;
    btn.addEventListener("click", () => {
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.setAttribute("aria-pressed", String(show));
        btn.setAttribute("aria-label", show ? "Passwort verbergen" : "Passwort anzeigen");
        btn.replaceChildren(icon(show ? "eye-off" : "eye"));
    });
}

/**
 * Dialog "Passwort vergessen": E-Mail senden und die neutrale Antwort zeigen.
 */
function setupForgotPassword() {
    const dialog = document.getElementById("forgot-dialog");
    const form = document.getElementById("forgot-form");
    if (!dialog || !form) return;

    document.getElementById("forgot-password-link")?.addEventListener("click", () => {
        form.reset();
        hideFormError("forgot-error");
        document.getElementById("forgot-success").hidden = true;
        document.getElementById("forgot-submit").hidden = false;
        // Bereits eingegebene E-Mail übernehmen – spart Tipparbeit.
        document.getElementById("forgot-email").value = document.getElementById("email").value.trim();
        openDialog(dialog);
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = document.getElementById("forgot-email").value.trim();
        const submit = document.getElementById("forgot-submit");
        hideFormError("forgot-error");
        if (!email) {
            showFormError("forgot-error", "Bitte gib deine E-Mail-Adresse ein.");
            return;
        }
        setBusy(submit, true, "Wird gesendet …");
        try {
            const res = await apiFetch("/api/v1/auth/forgot-password", { method: "POST", body: { email } });
            const data = await readJson(res);
            if (res.ok) {
                const success = document.getElementById("forgot-success");
                success.replaceChildren(icon("check-circle"),
                    h("span", { text: data.message || "Falls ein Konto existiert, wurde eine E-Mail gesendet." }));
                success.hidden = false;
                setBusy(submit, false);
                submit.hidden = true; // nur noch "Schließen" anbieten
                return;
            }
            showFormError("forgot-error", data.error || "Anfrage fehlgeschlagen.");
        } catch (err) {
            showFormError("forgot-error", "Server nicht erreichbar. Bitte später erneut versuchen.");
        }
        setBusy(submit, false);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    setupLoginForm();
    setupPasswordToggle();
    setupForgotPassword();
});
