let globalCalendar = null;
let currentUserRole = null;

function toDatetimeLocal(dateObj) {
    if (!dateObj) return "";
    const pad = n => n < 10 ? '0'+n : n;
    return dateObj.getFullYear() + '-' + pad(dateObj.getMonth()+1) + '-' + pad(dateObj.getDate()) + 'T' + pad(dateObj.getHours()) + ':' + pad(dateObj.getMinutes());
}

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
            
            const allowedTabs = {
                'nav-compare': ['CEO', 'ADMIN', 'TEAM_LEADER'],
                'nav-logs': ['CEO', 'ADMIN'],
                'nav-members': ['CEO', 'ADMIN'],
                'nav-customers': ['CEO', 'ADMIN']
            };
            
            for (const [tabId, roles] of Object.entries(allowedTabs)) {
                const el = document.getElementById(tabId);
                if (el) {
                    if (!roles.includes(currentUserRole)) el.classList.add('hidden');
                    else el.classList.remove('hidden');
                }
            }
            
            if (document.getElementById("user-name")) {
                document.getElementById("user-name").innerText = `${data.first_name} ${data.last_name} (${data.role})`;
            }
            if (['CEO', 'ADMIN', 'TEAM_LEADER'].includes(currentUserRole)) {
                document.getElementById("open-modal-btn")?.classList.remove("hidden");
                loadTrainers(token);
                loadSkills(token);
                loadCustomers(token);
                loadNotifications(token);
                
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
        setupEventCreation(token); 
        setupRSVPModals();
    }
    setupAuth();

    const cb = document.getElementById("event-is-all-day");
    if (cb) {
        cb.addEventListener("change", (e) => {
            document.getElementById("event-start").type = e.target.checked ? "date" : "datetime-local";
            document.getElementById("event-end").type = e.target.checked ? "date" : "datetime-local";
        });
    }
});

function loadTrainers(token) {
    fetch("/api/v1/auth/trainers", { headers: { "Authorization": `Bearer ${token}` } }).then(res => res.json()).then(data => {
        const select1 = document.getElementById("event-assignee");
        const select2 = document.getElementById("reassign-select");
        data.forEach(t => {
            if(select1) { const opt = document.createElement("option"); opt.value = t.id; opt.innerText = t.name; select1.appendChild(opt); }
            if(select2) { const opt = document.createElement("option"); opt.value = t.id; opt.innerText = t.name; select2.appendChild(opt); }
        });
    }).catch(console.error);
}

function loadSkills(token) {
    fetch("/api/v1/skills", { headers: { "Authorization": `Bearer ${token}` } }).then(res => res.json()).then(data => {
        const container = document.getElementById("skills-container");
        if (container && data.skills) {
            container.innerHTML = data.skills.length === 0 ? "<span class='text-gray-500'>Keine Qualifikationen im System.</span>" : data.skills.map(s => `
                <label class="flex items-center space-x-2">
                    <input type="checkbox" value="${s.id}" class="skill-checkbox rounded text-[#2B6CB0]">
                    <span>${s.name}</span>
                </label>`).join('');
        }
    }).catch(console.error);
}

function loadCustomers(token) {
    fetch("/api/v1/customers", { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.json())
        .then(d => {
            const s = document.getElementById("event-customer");
            if (s) {
                d.forEach(c => {
                    const o = document.createElement("option");
                    o.value = c.id;
                    o.innerText = c.name;
                    s.appendChild(o);
                });
            }
        })
        .catch(e => console.log(e));
}

function loadNotifications(token) {
    fetch("/api/v1/notifications", { headers: { "Authorization": `Bearer ${token}` } }).then(res => res.json()).then(data => {
        const unread = data.notifications.filter(n => !n.is_read);
        const badge = document.getElementById("notif-badge");
        const list = document.getElementById("notif-list");
        
        if (unread.length > 0) { badge.innerText = unread.length; badge.classList.remove("hidden"); } else { badge.classList.add("hidden"); }
        if (data.notifications.length === 0) {
            list.innerHTML = "<div class='px-4 py-3 text-sm text-gray-500'>Keine Benachrichtigungen.</div>";
        } else {
            list.innerHTML = data.notifications.map(n => `
                <div class="px-4 py-3 border-b hover:bg-gray-50 ${n.is_read ? 'opacity-50' : 'bg-blue-50'} cursor-pointer" onclick="markRead(${n.id}, '${token}')">
                    <p class="text-sm font-bold text-[#1A365D]">${n.title}</p>
                    <p class="text-xs text-gray-700 mt-1">${n.message}</p>
                </div>`).join('');
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
                    backgroundColor: e.reallocation_required ? '#E53E3E' : (e.color || '#2B6CB0'),
                    extendedProps: { reallocation_required: e.reallocation_required, assigned_to_id: e.assigned_to_id, meeting_link: e.meeting_link, customer_id: e.customer_id, is_mandatory: e.is_mandatory, rejection_reason: e.rejection_reason }
                })));
            } catch (error) { failureCallback(error); }
        },
        eventClick: function(info) {
            const eventId = info.event.id;
            document.getElementById('detail-title').innerText = info.event.title;
            document.getElementById('detail-time').innerText = `${info.event.start.toLocaleString('de-DE')} - ${info.event.end ? info.event.end.toLocaleString('de-DE') : ''}`;
            
            const rsvpSection = document.getElementById('rsvp-section');
            const reassignSection = document.getElementById('reassign-section');
            const adminActions = document.getElementById('admin-actions');
            
            if (rsvpSection) rsvpSection.classList.add('hidden');
            if (reassignSection) reassignSection.classList.add('hidden');
            if (adminActions) adminActions.classList.add('hidden');
            
            document.getElementById('rsvp-error')?.classList.add('hidden');
            document.getElementById('decline-container')?.classList.add('hidden');
            if (document.getElementById('decline-reason')) document.getElementById('decline-reason').value = '';
            
            if (currentUserRole === 'TRAINER') {
                if (info.event.extendedProps.is_mandatory) {
                    if (rsvpSection) rsvpSection.classList.add('hidden');
                } else {
                    if (rsvpSection) rsvpSection.classList.remove('hidden');
                document.getElementById('btn-accept').onclick = () => submitRsvp(eventId, 'ACCEPTED', null, token);
                document.getElementById('btn-submit-decline').onclick = () => {
                    const reason = document.getElementById('decline-reason').value;
                    if (!reason) { document.getElementById('rsvp-error').innerText = "Bitte gib eine Begründung an."; document.getElementById('rsvp-error').classList.remove('hidden'); return; }
                    submitRsvp(eventId, 'DECLINED', reason, token);
                };
                }
            } else if (['CEO', 'ADMIN', 'TEAM_LEADER'].includes(currentUserRole)) {
                if (info.event.extendedProps.reallocation_required && reassignSection) {
                    reassignSection.classList.remove('hidden');
                    const reasonEl = document.getElementById('detail-rejection-reason');
                    if (reasonEl) {
                        if (info.event.extendedProps.rejection_reason) {
                            reasonEl.innerText = "Ablehnungsgrund: " + info.event.extendedProps.rejection_reason;
                            reasonEl.classList.remove('hidden');
                        } else {
                            reasonEl.classList.add('hidden');
                        }
                    }
                    document.getElementById('btn-reassign').onclick = () => {
                        const newAssignee = document.getElementById('reassign-select').value;
                        if(newAssignee) reassignEvent(eventId, newAssignee, token);
                    };
                }
                if (adminActions) {
                    adminActions.classList.remove('hidden');
                    document.getElementById('btn-delete').onclick = async () => {
                        if(confirm("Bist du sicher, dass du diesen Termin löschen möchtest?")) {
                            const res = await fetch(`/api/v1/events/${eventId}`, { method: 'DELETE', headers: { "Authorization": `Bearer ${token}` } });
                            if (res.ok) { document.getElementById('event-details-modal').classList.add('hidden'); globalCalendar.refetchEvents(); }
                        }
                    };
                    document.getElementById('btn-edit').onclick = () => {
                        document.getElementById('event-details-modal').classList.add('hidden');
                        document.getElementById('event-modal-title').innerText = "Termin bearbeiten";
                        document.getElementById('editing-event-id').value = eventId;
                        document.getElementById('event-title').value = info.event.title;
                        const cbMandatory = document.getElementById('event-is-mandatory');
                        if (cbMandatory) cbMandatory.checked = info.event.extendedProps.is_mandatory || false;
                        document.getElementById('event-start').value = toDatetimeLocal(info.event.start);
                        document.getElementById('event-end').value = toDatetimeLocal(info.event.end);
                        if (info.event.extendedProps.assigned_to_id) { document.getElementById('event-assignee').value = info.event.extendedProps.assigned_to_id; }
                        document.getElementById('event-modal').classList.remove('hidden');
                    };
                }
            }
            document.getElementById('event-details-modal').classList.remove('hidden');
        }
    });
    globalCalendar.render();
}

async function submitRsvp(eventId, status, reason, token) {
    try {
        const response = await fetch(`/api/v1/events/${eventId}/rsvp`, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }, body: JSON.stringify({ status: status, rejection_reason: reason }) });
        if (response.ok) { document.getElementById('event-details-modal').classList.add('hidden'); if (globalCalendar) globalCalendar.refetchEvents(); } 
        else { const data = await response.json(); document.getElementById('rsvp-error').innerText = data.error || "Fehler."; document.getElementById('rsvp-error').classList.remove('hidden'); }
    } catch (err) { console.error(err); }
}

async function reassignEvent(eventId, assigneeId, token) {
    try {
        const response = await fetch(`/api/v1/events/${eventId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }, body: JSON.stringify({ assigned_to_id: parseInt(assigneeId) }) });
        if (response.ok) { document.getElementById('event-details-modal').classList.add('hidden'); if (globalCalendar) globalCalendar.refetchEvents(); loadNotifications(token); } 
        else { alert("Fehler bei der Zuweisung."); }
    } catch (err) { console.error(err); }
}

function setupEventCreation(token) {
    const modal = document.getElementById("event-modal"); const form = document.getElementById("event-form");
    document.getElementById("open-modal-btn")?.addEventListener("click", () => { document.getElementById('event-modal-title').innerText = "Neuen Termin anlegen"; document.getElementById('editing-event-id').value = ""; form.reset(); modal.classList.remove("hidden"); });
    document.getElementById("close-modal-btn")?.addEventListener("click", () => { modal.classList.add("hidden"); form.reset(); });

    form?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const editingId = document.getElementById("editing-event-id").value;
        const title = document.getElementById("event-title").value;
        
        let s_val = document.getElementById("event-start").value; 
        let e_val = document.getElementById("event-end").value; 

        let start_time = s_val;
        let end_time = e_val;
        if (s_val.includes('.')) {
            const parts = s_val.split(' ');
            const dmy = parts[0].split('.');
            start_time = `${dmy[2]}-${dmy[1]}-${dmy[0]}T${parts[1] || '00:00'}:00`;
        }
        if (e_val.includes('.')) {
            const parts = e_val.split(' ');
            const dmy = parts[0].split('.');
            end_time = `${dmy[2]}-${dmy[1]}-${dmy[0]}T${parts[1] || '00:00'}:00`;
        }

        if (start_time.length === 10) start_time += "T00:00:00";
        if (end_time.length === 10) end_time += "T23:59:59";

        const assignee_id = document.getElementById("event-assignee").value;
        const meeting_link = document.getElementById("event-meeting-link")?.value;
        const is_all_day = document.getElementById("event-is-all-day")?.checked;
        const is_mandatory = document.getElementById("event-is-mandatory")?.checked;
        const customer_id = document.getElementById("event-customer")?.value;
        const errorDiv = document.getElementById("event-error");
        
        const skillCheckboxes = document.querySelectorAll('.skill-checkbox:checked');
        const required_skill_ids = Array.from(skillCheckboxes).map(cb => parseInt(cb.value));

        const payload = { title, start_time, end_time };
        if (assignee_id) payload.assigned_to_id = parseInt(assignee_id);
        if (meeting_link) payload.meeting_link = meeting_link;
        payload.is_all_day = is_all_day || false;
        
        if (customer_id) payload.customer_id = parseInt(customer_id); else payload.customer_id = null;
        if (required_skill_ids.length > 0) payload.required_skill_ids = required_skill_ids;

        try {
            const response = await fetch(editingId ? `/api/v1/events/${editingId}` : "/api/v1/events", {
                method: editingId ? "PUT" : "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            
            if (response.ok) {
                if (data.event && data.event.qualification_warning) alert("Achtung: " + data.event.qualification_warning);
                modal.classList.add("hidden"); form.reset(); errorDiv.classList.add("hidden");
                if (globalCalendar) globalCalendar.refetchEvents();
            } else {
                errorDiv.innerText = data.message || data.error || "Fehler beim Speichern."; 
                errorDiv.classList.remove("hidden");
            }
        } catch (err) { 
            errorDiv.innerText = "Netzwerkfehler oder Server nicht erreichbar."; 
            errorDiv.classList.remove("hidden"); 
        }
    });
}

function setupRSVPModals() {
    document.getElementById('btn-decline')?.addEventListener('click', () => { document.getElementById('decline-container').classList.remove('hidden'); });
    document.getElementById('close-details-btn')?.addEventListener('click', () => { document.getElementById('event-details-modal').classList.add('hidden'); });
}

function setupAuth() {
    document.getElementById("login-form")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = document.getElementById("email").value; 
        const password = document.getElementById("password").value;
        const errDiv = document.getElementById("login-error");
        try {
            const res = await fetch("/api/v1/auth/login", { 
                method: "POST", 
                headers: { "Content-Type": "application/json" }, 
                body: JSON.stringify({ email, password }) 
            });
            const data = await res.json();
            if (res.ok) { 
                localStorage.setItem("access_token", data.access_token); 
                window.location.href = "/dashboard"; 
            } else { 
                errDiv.innerText = data.error; 
                errDiv.classList.add("hidden"); 
            }
        } catch (err) { 
            errDiv.innerText = "Fehler."; 
            errDiv.classList.add("hidden"); 
        }
    });
    document.getElementById("logout-btn")?.addEventListener("click", () => { 
        localStorage.removeItem("access_token"); 
        window.location.href = "/login"; 
    });
}
