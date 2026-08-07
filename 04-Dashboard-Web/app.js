const API = ""; // same origin (backend serves /dashboard + /api)

const els = {
  loginView: document.getElementById("view-login"),
  appView: document.getElementById("view-app"),
  loginForm: document.getElementById("login-form"),
  loginError: document.getElementById("login-error"),
  userLabel: document.getElementById("user-label"),
  btnLogout: document.getElementById("btn-logout"),
  btnRefresh: document.getElementById("btn-refresh"),
  btnRefreshStudents: document.getElementById("btn-refresh-students"),
  chatList: document.getElementById("chat-list"),
  settingsForm: document.getElementById("settings-form"),
  settingsMsg: document.getElementById("settings-msg"),
  deviceFace: document.getElementById("device-face"),
  deviceLabel: document.getElementById("device-label"),
  panelHistory: document.getElementById("panel-history"),
  panelSettings: document.getElementById("panel-settings"),
  panelStudents: document.getElementById("panel-students"),
  langTr: document.getElementById("lang-tr"),
  langEn: document.getElementById("lang-en"),
  studentSelect: document.getElementById("student-select"),
  studentName: document.getElementById("student-name"),
  gradeSelect: document.getElementById("grade-select"),
  btnSaveStudent: document.getElementById("btn-save-student"),
  studentBand: document.getElementById("student-band"),
  studentsMsg: document.getElementById("students-msg"),
  activityLog: document.getElementById("activity-log"),
};

let token = localStorage.getItem("meb_token") || "";
let user = JSON.parse(localStorage.getItem("meb_user") || "null");
let pollTimer = null;
let studentsCache = [];
let suppressStudentEvents = false;

function errorDetail(data, fallback) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0]?.msg) return d.map((x) => x.msg).join("; ");
  return fallback || "İstek başarısız";
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(API + path, { ...opts, headers });
  const data = await res.json().catch(() => ({}));

  if (path === "/api/login") {
    if (!res.ok) throw new Error(errorDetail(data, "Giriş başarısız"));
    return data;
  }

  if (res.status === 401) {
    logout(true);
    throw new Error("Oturum sona erdi — tekrar giriş yapın");
  }
  if (!res.ok) throw new Error(errorDetail(data));
  return data;
}

function bandLabel(sinif) {
  const n = Number(sinif);
  if (n === 0) return "Tümü — karışık sınıf kitapları";
  if (n <= 4) return "İlkokul arayüzü (1–4) — tatlı yüz";
  if (n <= 8) return "Ortaokul arayüzü (5–8) — sade & sıcak";
  return "Lise arayüzü (9–12) — mevcut tasarım";
}

function showApp() {
  els.loginView.hidden = true;
  els.appView.hidden = false;
  els.userLabel.textContent = `${user.display_name} (${user.role})`;
  loadChats().catch(() => {});
  loadSettings().catch(() => {});
  loadStudents().catch(() => {});
  startStatusPoll();
}

function showLogin() {
  els.loginView.hidden = false;
  els.appView.hidden = true;
  stopStatusPoll();
}

function logout(clear = true) {
  if (clear) {
    localStorage.removeItem("meb_token");
    localStorage.removeItem("meb_user");
  }
  token = "";
  user = null;
  showLogin();
}

els.loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  els.loginError.hidden = true;
  try {
    const body = {
      username: document.getElementById("username").value.trim(),
      password: document.getElementById("password").value,
    };
    const data = await api("/api/login", { method: "POST", body: JSON.stringify(body) });
    token = data.token;
    user = data.user;
    localStorage.setItem("meb_token", token);
    localStorage.setItem("meb_user", JSON.stringify(user));
    showApp();
  } catch (err) {
    els.loginError.textContent = err.message || "Giriş başarısız";
    els.loginError.hidden = false;
  }
});

els.btnLogout.addEventListener("click", () => logout(true));
els.btnRefresh.addEventListener("click", () => loadChats());
els.btnRefreshStudents.addEventListener("click", () => loadStudents());

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const panel = btn.dataset.panel;
    els.panelHistory.hidden = panel !== "history";
    els.panelSettings.hidden = panel !== "settings";
    els.panelStudents.hidden = panel !== "students";
    if (panel === "students") loadStudents().catch(() => {});
  });
});

async function loadChats() {
  const data = await api("/api/chats?limit=80");
  const chats = data.chats || [];
  if (!chats.length) {
    els.chatList.innerHTML = `<p class="hint">Henüz kayıt yok. Cihazda soru sordukça burada görünür.</p>`;
    return;
  }
  els.chatList.innerHTML = chats
    .map(
      (c) => `
      <article class="chat-item">
        <div class="chat-meta">${escapeHtml(c.created_at)} · ${escapeHtml(c.dil)} · ${escapeHtml(c.cihaz_id)}</div>
        <div class="chat-q">${escapeHtml(c.soru)}</div>
        <div class="chat-a">${escapeHtml(c.cevap)}</div>
      </article>`
    )
    .join("");
}

function renderActivity(log) {
  if (!log || !log.length) {
    els.activityLog.innerHTML = `<p class="hint">Henüz öğrenci/sınıf değişikliği yok.</p>`;
    return;
  }
  els.activityLog.innerHTML = log
    .map(
      (row) => `
      <article class="chat-item">
        <div class="chat-meta">${escapeHtml(row.created_at)} · ${escapeHtml(row.user_name)} · ${escapeHtml(row.olay)}</div>
        <div class="chat-a">${escapeHtml(row.detay)}</div>
      </article>`
    )
    .join("");
}

async function loadStudents() {
  const data = await api("/api/students");
  studentsCache = data.students || [];
  const aktif = data.aktif || studentsCache.find((s) => s.aktif) || studentsCache[0] || { ad: "", sinif: 1 };
  els.studentName.value = aktif.ad || "";
  els.gradeSelect.value = String(aktif.sinif ?? 0);
  const label = aktif.ad ? aktif.ad : "İsimsiz öğrenci";
  const sn = Number(aktif.sinif ?? 0);
  const sinifTxt = sn === 0 ? "Tümü" : `${sn}. sınıf`;
  els.studentBand.textContent = `${label} · ${sinifTxt} · ${bandLabel(aktif.sinif)}`;
  renderActivity(data.log || []);
}

els.btnSaveStudent.addEventListener("click", async () => {
  const ad = (els.studentName.value || "").trim();
  const sinif = Number(els.gradeSelect.value);
  try {
    const data = await api("/api/students/profile", {
      method: "PUT",
      body: JSON.stringify({ ad, sinif }),
    });
    const a = data.aktif || {};
    els.studentName.value = a.ad || "";
    els.gradeSelect.value = String(a.sinif || sinif);
    els.studentBand.textContent = `${a.ad || "İsimsiz öğrenci"} · ${bandLabel(a.sinif)}`;
    renderActivity(data.log || []);
    els.studentsMsg.textContent = "Kaydedildi — cihaz ve cevaplar güncellendi.";
    els.studentsMsg.hidden = false;
  } catch (err) {
    els.studentsMsg.textContent = err.message || "Hata";
    els.studentsMsg.hidden = false;
  }
});

async function loadSettings() {
  const data = await api("/api/settings");
  const s = data.settings || {};
  const form = els.settingsForm;
  for (const [k, v] of Object.entries(s)) {
    if (form.elements[k]) form.elements[k].value = v;
  }
  setLangChips(s.dil || "Türkçe");
}

function setLangChips(dil) {
  const en = String(dil).toLowerCase().startsWith("en") || dil === "English";
  els.langTr.classList.toggle("active", !en);
  els.langEn.classList.toggle("active", en);
}

async function saveLang(dil) {
  setLangChips(dil);
  await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify({ dil }),
  });
  els.settingsMsg.textContent = `Dil: ${dil}`;
  els.settingsMsg.hidden = false;
}

els.langTr.addEventListener("click", () => saveLang("Türkçe"));
els.langEn.addEventListener("click", () => saveLang("English"));

els.settingsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(els.settingsForm);
  const body = Object.fromEntries(fd.entries());
  await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
  els.settingsMsg.textContent = "Ayarlar kaydedildi.";
  els.settingsMsg.hidden = false;
});

const STATE_TR = {
  idle: "Bekliyor",
  listening: "Dinliyor",
  thinking: "Düşünüyor",
  speaking: "Konuşuyor",
};

function setDeviceState(value) {
  const v = (value || "idle").toLowerCase();
  els.deviceFace.className = `device-face state-${v}`;
  els.deviceLabel.textContent = STATE_TR[v] || v;
}

async function pollStatus() {
  try {
    const data = await api("/api/device/status");
    setDeviceState(data.value);
  } catch {
    /* ignore */
  }
}

function startStatusPoll() {
  stopStatusPoll();
  pollStatus();
  pollTimer = setInterval(pollStatus, 2000);
}
function stopStatusPoll() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function boot() {
  if (token && user) {
    try {
      await api("/api/chats?limit=1");
      showApp();
      return;
    } catch {
      logout(true);
    }
  }
  showLogin();
}

boot();
