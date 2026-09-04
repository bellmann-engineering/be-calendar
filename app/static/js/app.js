let globalCalendar = null;
let currentUserRole = null;

document.addEventListener("DOMContentLoaded", () => {
    const token = localStorage.getItem("access_token");
    const currentPath = window.location.pathname;

    if (!token && currentPath !== "/login") {
        window.location.href = "/login"; return;
    }
    if (token) {
        if (currentPath === "/login") { window.location.href = "/dashboard"; return; }
        
        document.getElementById("user-info")?.classList.remove("hidden");
        document.getElementById("dashboard-content")?.classList.remove("hidden");

        fetch("/api/v1/auth/me", { headers: { "Authorization": `Bearer ${token}` } })
        .then(res => res.json())
        .then(data => {
            currentUserRole = data.role;
            if (document.getElementById("user-name")) {
                document.getElementById("user-name").innerText = `${data.first_name} ${data.last_name} (${data.role})`;
            }
            if (['CEO', 'ADMIN', 'TEAM_LEADER'].includes(currentUserRole)) {
                document.getElementById("open-modal-btn")?.classList.remove("hidden");
                loadTrainers(token);
                loadSkills(token);
                loadNotifications(token);
                
                // Toggle Dropdown
                document.getElementById("notification-bell")?.addEventListener("click", () => {
                    document.getElementById("notif-dropdown")?.classList.toggle("hidden");
                });
            } else {
                document.getElementById("notification-bell")?.classList.add("hidden");
            }
        });

        if (document.getElementById("calendar-container")) {
            renderCalendar(token, document.getElementById("calendar-container"));
        }
        setupAILogic(token); setupEventCreation(token); setupRSVPModals();
    }
    setupAuth();
});

function loadTrainers(token) {
    fetch("/api/v1/auth/trainers", { headers: { "Authorization": `Bearer ${token}` } })
    .then(res => res.json())
    .then(data => {
        const select1 = document.getElementById("event-assignee");
        const select2 = document.getElementById("reassign-select");
        data.forEach(t => {
            if(select1) { const opt = document.createElement("option"); opt.value = t.id; opt.innerText = t.name; select1.appendChild(opt); }
            if(select2) { const opt = document.createElement("option"); opt.value = t.id; opt.innerText = t.name; select2.appendChild(opt); }
        });
    }).catch(console.error);
}

function loadSkills(token) {
    fetch("/api/v1/skills", { headers: { "Authorization": `Bearer ${token}` } })
    .then(res => res.json())
    .then(data => {
        const container = document.getElementById("skills-container");
        if (container && data.skills) {
            if (data.skills.length === 0) {
                container.innerHTML = "<span class='text-gray-500'>Keine Qualifikationen im System.</span>";
            } else {
                container.innerHTML = data.skills.map(s => `
                    <label class="flex items-center space-x-2">
                        <input type="checkbox" value="${s.id}" class="skill-checkbox rounded text-[#2B6CB0]">
                        <span>${s.name}</span>
                    </label>
                `).join('');
            }
        }
    }).catch(console.error);
}

function loadNotifications(token) {
    fetch("/api/v1/notifications", { headers: { "Authorization": `Bearer ${token}` } })
    .then(res => res.json())
    .then(data => {
        const unread = data.notifications.filter(n => !n.is_read);
        const badge = document.getElementById("notif-badge");
        const list = document.getElementById("notif-list");
        
        if (unread.length > 0) {
            badge.innerText = unread.length; badge.classList.remove("hidden");
        } else {
            badge.classList.add("hidden");
        }

        if (data.notifications.length === 0) {
            list.innerHTML = "<div class='px-4 py-3 text-sm text-gray-500'>Keine Benachrichtigungen.</div>";
        } else {
            list.innerHTML = data.notifications.map(n => `
                <div class="px-4 py-3 border-b hover:bg-gray-50 ${n.is_read ? 'opacity-50' : 'bg-blue-50'} cursor-pointer" onclick="markRead(${n.id}, '${token}')">
                    <p class="text-sm font-bold text-[#1A365D]">${n.title}</p>
                    <p class="text-xs text-gray-700 mt-1">${n.message}</p>
                </div>
            `).join('');
        }
    }).catch(console.error);
}

window.markRead = async function(id, token) {
    await fetch(`/api/v1/notifications/${id}/read`, { method: 'PUT', headers: { "Authorization": `Bearer ${token}` } });
    loadNotifications(token);
}

function renderCalendar(token, container) {
    container.innerHTML = "";
    globalCalendar = new FullCalendar.Calendar(container, {
        initialView: 'timeGridWeek',
        headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,timeGridDay' },
        locale: 'de', allDaySlot: false, slotMinTime: '06:00:00', slotMaxTime: '22:00:00',
        events: async function(fetchInfo, successCallback, failureCallback) {
            try {
                const response = await fetch("/api/v1/events", { headers: { "Authorization": `Bearer ${token}` } });
                if (!response.ok) throw new Error("Fehler beim Laden");
                const data = await response.json();
                successCallback(data.map(e => ({
                    id: e.id, title: e.title, start: e.start_time, end: e.end_time,
                    backgroundColor: e.reallocation_required ? '#E53E3E' : '#2B6CB0',
                    extendedProps: { reallocation_required: e.reallocation_required }
                })));
            } catch (error) { failureCallback(error); }
        },
        eventClick: function(info) {
            const eventId = info.event.id;
            document.getElementById('detail-title').innerText = info.event.title;
            document.getElementById('detail-time').innerText = `${info.event.start.toLocaleString('de-DE')} - ${info.event.end ? info.event.end.toLocaleString('de-DE') : ''}`;
            
            const rsvpSection = document.getElementById('rsvp-section');
            const reassignSection = document.getElementById('reassign-section');
            
            if (rsvpSection) rsvpSection.classList.add('hidden');
            if (reassignSection) reassignSection.classList.add('hidden');
            document.getElementById('rsvp-error').classList.add('hidden');
            document.getElementById('decline-container').classList.add('hidden');
            document.getElementById('decline-reason').value = '';
            
            if (currentUserRole === 'TRAINER') {
                rsvpSection.classList.remove('hidden');
                document.getElementById('btn-accept').onclick = () => submitRsvp(eventId, 'ACCEPTED', null, token);
                document.getElementById('btn-submit-decline').onclick = () => {
                    const reason = document.getElementById('decline-reason').value;
                    if (!reason) {
                        document.getElementById('rsvp-error').innerText = "Bitte gib eine Begründung an.";
                        document.getElementById('rsvp-error').classList.remove('hidden'); return;
                    }
                    submitRsvp(eventId, 'DECLINED', reason, token);
                };
            } else if (['CEO', 'ADMIN', 'TEAM_LEADER'].includes(currentUserRole) && info.event.extendedProps.reallocation_required) {
                reassignSection.classList.remove('hidden');
                document.getElementById('btn-reassign').onclick = () => {
                    const newAssignee = document.getElementById('reassign-select').value;
                    if(newAssignee) reassignEvent(eventId, newAssignee, token);
                };
            }
            
            document.getElementById('event-details-modal').classList.remove('hidden');
        }
    });
    globalCalendar.render();
}

async function submitRsvp(eventId, status, reason, token) {
    try {
        const response = await fetch(`/api/v1/events/${eventId}/rsvp`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ status: status, rejection_reason: reason })
        });
        if (response.ok) {
            document.getElementById('event-details-modal').classList.add('hidden');
            if (globalCalendar) globalCalendar.refetchEvents();
        } else {
            const data = await response.json();
            document.getElementById('rsvp-error').innerText = data.error || "Fehler.";
            document.getElementById('rsvp-error').classList.remove('hidden');
        }
    } catch (err) { console.error(err); }
}

async function reassignEvent(eventId, assigneeId, token) {
    try {
        const response = await fetch(`/api/v1/events/${eventId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ assigned_to_id: parseInt(assigneeId) })
        });
        if (response.ok) {
            document.getElementById('event-details-modal').classList.add('hidden');
            if (globalCalendar) globalCalendar.refetchEvents();
            loadNotifications(token); // Neu laden, da evtl. die Zuweisungs-Notiz behoben ist
        } else {
            alert("Fehler bei der Zuweisung.");
        }
    } catch (err) { console.error(err); }
}

function setupEventCreation(token) {
    const modal = document.getElementById("event-modal");
    const form = document.getElementById("event-form");
    document.getElementById("open-modal-btn")?.addEventListener("click", () => modal.classList.remove("hidden"));
    document.getElementById("close-modal-btn")?.addEventListener("click", () => { modal.classList.add("hidden"); form.reset(); });

    form?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const title = document.getElementById("event-title").value;
        const start_time = document.getElementById("event-start").value + ":00Z";
        const end_time = document.getElementById("event-end").value + ":00Z";
        const assignee_id = document.getElementById("event-assignee").value;
        const errorDiv = document.getElementById("event-error");
        
        const skillCheckboxes = document.querySelectorAll('.skill-checkbox:checked');
        const required_skill_ids = Array.from(skillCheckboxes).map(cb => parseInt(cb.value));

        const payload = { title, start_time, end_time };
        if (assignee_id) payload.assigned_to_id = parseInt(assignee_id);
        if (required_skill_ids.length > 0) payload.required_skill_ids = required_skill_ids;

        try {
            const response = await fetch("/api/v1/events", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            
            if (response.ok) {
                if (data.event && data.event.qualification_warning) {
                    alert("Achtung: " + data.event.qualification_warning);
                }
                modal.classList.add("hidden"); form.reset(); errorDiv.classList.add("hidden");
                if (globalCalendar) globalCalendar.refetchEvents();
            } else {
                errorDiv.innerText = data.error || "Fehler."; errorDiv.classList.remove("hidden");
            }
        } catch (err) { errorDiv.innerText = "Netzwerkfehler."; errorDiv.classList.remove("hidden"); }
    });
}

function setupAILogic(token) {
    const btn = document.getElementById("run-ai-btn");
    const box = document.getElementById("ai-result-box");
    btn?.addEventListener("click", async () => {
        if (!globalCalendar) return;
        const events = globalCalendar.getEvents().map(e => ({ title: e.title, start: e.startStr, end: e.endStr }));
        btn.innerText = "Analysiere..."; btn.disabled = true;
        box.classList.remove("hidden"); box.innerHTML = "<span class='text-emerald-600 animate-pulse'>Lade...</span>";
        try {
            const res = await fetch("/api/v1/ai/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
                body: JSON.stringify({ events })
            });
            const data = await res.json();
            box.innerHTML = res.ok ? `<div class='text-gray-800 text-sm pl-2'>${data.analysis}</div>` : `<span class='text-red-600'>Fehler: ${data.error}</span>`;
        } catch (err) { box.innerHTML = "<span class='text-red-600'>Netzwerkfehler.</span>"; } 
        finally { btn.innerText = "Konflikte analysieren"; btn.disabled = false; }
    });
}

function setupRSVPModals() {
    document.getElementById('btn-decline')?.addEventListener('click', () => { document.getElementById('decline-container').classList.remove('hidden'); });
    document.getElementById('close-details-btn')?.addEventListener('click', () => { document.getElementById('event-details-modal').classList.add('hidden'); });
}

function setupAuth() {
    document.getElementById("login-form")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = document.getElementById("email").value; const password = document.getElementById("password").value;
        const errDiv = document.getElementById("login-error");
        try {
            const res = await fetch("/api/v1/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
            const data = await res.json();
            if (res.ok) { localStorage.setItem("access_token", data.access_token); window.location.href = "/dashboard"; } 
            else { errDiv.innerText = data.error; errDiv.classList.remove("hidden"); }
        } catch (err) { errDiv.innerText = "Fehler."; errDiv.classList.remove("hidden"); }
    });
    document.getElementById("logout-btn")?.addEventListener("click", () => { localStorage.removeItem("access_token"); window.location.href = "/login"; });
}
