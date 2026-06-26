"use strict";

const STYLE_META = {
  yumor:  { label: "😄 Yumor / Sarkazm", short: "😄", badge: "badge--yumor", cls: "yumor" },
  aqlli:  { label: "🧠 Aqlli burchak",   short: "🧠", badge: "badge--aqlli", cls: "aqlli" },
  bahsli: { label: "🔥 Bahsli",          short: "🔥", badge: "badge--bahsli", cls: "bahsli" },
};
const ACTION_ICON = { like: "❤️", repost: "🔁", story: "📖", view: "👁" };
// Akkaunt xususiyatlari (backend prompts.py bilan mos bo'lsin)
const PERSONAS = {
  yumor: "😄 Hazilkash", heyter: "😈 Heyter", maqtov: "👏 Maqtovchi",
  qollab: "🤝 Ma'qullovchi", bilmasvoy: "🤔 Bilmasvoy",
};
const RING_C = 2 * Math.PI * 16; // r=16

// === Repost / Story vaqtincha O'CHIRILGAN (GB tejash uchun) ===
// Proxy GB (internet trafigi) cheklangan. Repost va Story video yuklab oladi va
// qayta joylaydi — har biri ~20-30 MB, ya'ni GB ni juda tez tugatadi.
// Komment/like esa juda kam trafik. Proxy + yetarli GB tayyor bo'lgach,
// pastdagi flag'ni `true` qilib qayta yoqamiz.
const REPOST_STORY_ENABLED = false;
const REPOST_STORY_MSG =
  "🚫 Repost va Story hozircha vaqtincha O'CHIRILGAN\n\n" +
  "SABABI:\n" +
  "• Repost/Story postdagi VIDEO ni yuklab olib, qayta joylaydi.\n" +
  "• Har bir repost/story ~20-30 MB proxy interneti (GB) sarflaydi.\n" +
  "• Bizda proxy GB cheklangan (hozir atigi bir necha GB) — bularni\n" +
  "  ishlatsak, internet bir necha kunda tugab qoladi.\n\n" +
  "HOZIR NIMA QILSA BO'LADI:\n" +
  "• ✅ Komment yozish va ❤️ Like — bular juda kam trafik (~1 MB),\n" +
  "  bemalol ishlatavering.\n" +
  "• 🧠 AI komment generatsiyasi umuman proxy GB ishlatmaydi.\n\n" +
  "QACHON YOQILADI:\n" +
  "• Yetarli proxy GB ulanib, balans to'lgach Repost/Story qayta ochiladi.";

let state = { mediaId: null, url: "", comments: null, accounts: [] };

const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const err = new Error(data.detail || `Xato (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

let toastTimer;
function toast(msg, kind = "info") {
  const t = $("toast");
  t.textContent = msg;
  t.className = `toast ${kind}`;
  t.style.animation = "none"; void t.offsetWidth; t.style.animation = "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 5200);
}

function setLoading(btn, on) { btn.classList.toggle("loading", on); btn.disabled = on; }

// ---------- Theme ----------
function initTheme() {
  const saved = localStorage.getItem("kq-theme") || "light";
  document.documentElement.dataset.theme = saved;
  $("theme-toggle").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("kq-theme", next);
  };
}

// ---------- Count-up ----------
function animateCount(el, to) {
  const from = parseInt(el.textContent, 10) || 0;
  if (from === to) { el.textContent = to; return; }
  const dur = 700, start = performance.now();
  function tick(now) {
    const p = Math.min(1, (now - start) / dur);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(from + (to - from) * eased);
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// global gradient def for rings
function injectRingGradient() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "0"); svg.setAttribute("height", "0");
  svg.style.position = "absolute";
  svg.innerHTML = `<defs><linearGradient id="ringgrad" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#7c5cff"/><stop offset="100%" stop-color="#d6457b"/></linearGradient></defs>`;
  document.body.appendChild(svg);
}

// ---------- Status ----------
async function loadStatus() {
  const s = await api("/api/status");
  if (s.auth_required && !s.authed) {
    $("login-overlay").classList.remove("hidden");
    $("app").classList.add("hidden");
    return false;
  }
  $("login-overlay").classList.add("hidden");
  $("app").classList.remove("hidden");

  state.accounts = s.accounts || [];
  renderAccounts(state.accounts);
  renderProviders(s.providers || [], s.default_provider);
  renderPickAccounts(state.accounts);
  loadModems();

  const n = state.accounts.length;
  $("accounts-count").textContent = `${n} akkaunt`;
  $("pill-accounts").classList.toggle("online", n > 0);

  // stats
  animateCount($("stat-accounts"), n);
  animateCount($("stat-today"), state.accounts.reduce((a, x) => a + (x.daily_count || 0), 0));
  animateCount($("stat-ai"), (s.providers || []).length);
  return true;
}

function renderAccounts(accounts) {
  const box = $("accounts-list");
  if (!accounts.length) {
    box.innerHTML = '<p class="muted empty">Hali akkaunt qo\'shilmagan. Quyidan qo\'shing.</p>';
    return;
  }
  box.innerHTML = "";
  accounts.forEach((a, idx) => {
    const pct = a.daily_limit ? Math.min(1, a.daily_count / a.daily_limit) : 0;
    const hasProxy = !!a.proxy;
    const row = document.createElement("div");
    row.className = "account-row";
    row.style.animationDelay = `${Math.min(idx, 20) * 25}ms`;
    const persona = a.personality || "yumor";
    const opts = Object.entries(PERSONAS).map(
      ([k, v]) => `<option value="${k}"${k === persona ? " selected" : ""}>${v}</option>`
    ).join("");
    const hp = a.health || {};
    const hcls = hp.alive === true ? "alive" : hp.alive === false ? "dead" : "unknown";
    const htitle = hp.alive === true ? "Tirik ✓" : hp.alive === false ? "O'lik — qayta ulang" : "Tekshirilmagan";
    row.innerHTML = `
      <span class="acc-name" title="@${a.username}"><span class="dot dot--${hcls}" title="${htitle}"></span>@${a.username}</span>
      <select class="persona-sel" title="Akkaunt xususiyati — shunga mos komment yoziladi">${opts}</select>
      <span class="acc-usage" title="Bugun: ${a.daily_count}/${a.daily_limit}">
        <i class="usage-bar"><b style="width:${(pct * 100).toFixed(0)}%"></b></i>${a.daily_count}/${a.daily_limit}
      </span>
      <button class="proxy-chip ${hasProxy ? "has-proxy" : "no-proxy"}" data-act="setproxy"
        title="${hasProxy ? a.proxy : "Proxysiz — o'rnatish uchun bosing"}">${hasProxy ? "🛡" : "⚠️"}</button>
      <button class="acc-icon" data-act="testproxy" title="Proxyni tekshirish">↻</button>
      <button class="acc-icon acc-remove" title="O'chirish">×</button>`;
    row.querySelector(".persona-sel").onchange = (e) => doSetPersonality(a.username, e.target.value);
    row.querySelector('[data-act="setproxy"]').onclick = () => doSetProxy(a.username, a.proxy);
    row.querySelector('[data-act="testproxy"]').onclick = (e) => doTestProxy(a.username, e.currentTarget);
    row.querySelector(".acc-remove").onclick = () => doRemoveAccount(a.username);
    box.appendChild(row);
  });
}

function renderProviders(providers, defaultId) {
  const sel = $("provider-select");
  sel.innerHTML = "";
  if (!providers.length) {
    sel.innerHTML = '<option value="">(API kaliti yo\'q)</option>';
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
  for (const p of providers) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = `${p.name} · ${p.model}`;
    if (p.id === defaultId) opt.selected = true;
    sel.appendChild(opt);
  }
}

function renderPickAccounts(accounts) {
  const box = $("pick-accounts");
  if (!accounts.length) { box.innerHTML = '<p class="muted">Avval yuqorida akkaunt qo\'shing.</p>'; return; }
  box.innerHTML = "";
  for (const a of accounts) {
    const label = document.createElement("label");
    label.className = "pick-item";
    label.innerHTML = `<input type="checkbox" value="${a.username}" checked /> @${a.username}`;
    box.appendChild(label);
  }
}

const selectedUsernames = () =>
  [...document.querySelectorAll("#pick-accounts input:checked")].map((c) => c.value);

// ---------- Login ----------
async function doLogin() {
  $("login-error").textContent = "";
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify({ password: $("login-password").value }) });
    await loadStatus();
    await loadHistory();
  } catch (e) { $("login-error").textContent = e.message; }
}
async function doLogout() { await api("/api/logout", { method: "POST" }); location.reload(); }

// ---------- Accounts add/remove ----------
function refreshAccountsUI() {
  renderAccounts(state.accounts);
  renderPickAccounts(state.accounts);
  $("accounts-count").textContent = `${state.accounts.length} akkaunt`;
  $("pill-accounts").classList.toggle("online", state.accounts.length > 0);
  animateCount($("stat-accounts"), state.accounts.length);
  animateCount($("stat-today"), state.accounts.reduce((a, x) => a + (x.daily_count || 0), 0));
}

async function doAddAccount() {
  const sid = $("sessionid-input").value.trim();
  if (!sid) { toast("sessionid kiriting", "err"); return; }
  const proxy = $("proxy-input").value.trim();
  const use_proxy = $("sessionid-useproxy").checked;
  const btn = $("ig-add-btn");
  setLoading(btn, true);
  try {
    const res = await api("/api/accounts", { method: "POST", body: JSON.stringify({ sessionid: sid, proxy, use_proxy }) });
    $("sessionid-input").value = "";
    $("proxy-input").value = "";
    toast("Akkaunt qo'shildi: @" + res.username, "ok");
    state.accounts = res.accounts;
    refreshAccountsUI();
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

// Plan B: login + parol bilan kirish (2FA bilan)
let _pendingLoginToken = null;

async function doLoginAccount() {
  const username = $("iglogin-username").value.trim();
  const password = $("iglogin-password").value;
  if (!username || !password) { toast("Username va parol kiriting", "err"); return; }
  const proxy = $("iglogin-proxy").value.trim();
  const use_proxy = $("iglogin-useproxy").checked;
  const btn = $("ig-login-btn");
  setLoading(btn, true);
  try {
    const res = await api("/api/accounts/login", {
      method: "POST", body: JSON.stringify({ username, password, proxy, use_proxy }),
    });
    if (res.status === "2fa") {
      _pendingLoginToken = res.token;
      $("twofa-row").style.display = "";
      $("iglogin-2fa").focus();
      toast("2FA kodi yuborildi — kodni kiriting", "info");
      return;
    }
    _finishAccountAdded(res, "@" + res.username + " kirdi");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

async function doVerify2FA() {
  const code = $("iglogin-2fa").value.trim();
  if (!code) { toast("2FA kodini kiriting", "err"); return; }
  if (!_pendingLoginToken) { toast("Avval login qiling", "err"); return; }
  const btn = $("ig-2fa-btn");
  setLoading(btn, true);
  try {
    const res = await api("/api/accounts/login/2fa", {
      method: "POST", body: JSON.stringify({ token: _pendingLoginToken, code }),
    });
    _pendingLoginToken = null;
    $("twofa-row").style.display = "none";
    $("iglogin-2fa").value = "";
    _finishAccountAdded(res, "@" + res.username + " kirdi (2FA)");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

function _finishAccountAdded(res, msg) {
  $("iglogin-username").value = "";
  $("iglogin-password").value = "";
  $("iglogin-proxy").value = "";
  toast(msg, "ok");
  state.accounts = res.accounts;
  refreshAccountsUI();
}

async function doSetProxy(username) {
  const val = prompt(`@${username} uchun proxy (masalan: http://user:pass@host:port yoki socks5://host:port).\nO'chirish uchun bo'sh qoldiring:`, "");
  if (val === null) return;
  try {
    const res = await api(`/api/accounts/${encodeURIComponent(username)}/proxy`, {
      method: "POST", body: JSON.stringify({ proxy: val.trim() }),
    });
    state.accounts = res.accounts;
    renderAccounts(state.accounts);
    renderPickAccounts(state.accounts);
    toast(val.trim() ? "Proxy o'rnatildi" : "Proxy o'chirildi", "ok");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  }
}

async function doTestProxy(username, btn) {
  setLoading(btn, true);
  try {
    const res = await api(`/api/accounts/${encodeURIComponent(username)}/proxy/test`, { method: "POST" });
    toast(`@${username}: ishlayapti ✓ (${res.username})`, "ok");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(`@${username}: ${e.message}`, "err");
  } finally { setLoading(btn, false); }
}

async function doRemoveAccount(username) {
  if (!confirm(`@${username} o'chirilsinmi?`)) return;
  try {
    const res = await api(`/api/accounts/${encodeURIComponent(username)}`, { method: "DELETE" });
    state.accounts = res.accounts;
    refreshAccountsUI();
    toast(`@${username} o'chirildi`, "info");
  } catch (e) { toast(e.message, "err"); }
}

async function doSetPersonality(username, personality) {
  try {
    const res = await api(`/api/accounts/${encodeURIComponent(username)}/personality`, {
      method: "POST", body: JSON.stringify({ personality }),
    });
    state.accounts = res.accounts;
    toast(`@${username}: ${PERSONAS[personality] || personality} belgilandi`, "ok");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  }
}

async function doCheckAll() {
  const btn = $("check-all-btn");
  setLoading(btn, true);
  try {
    const start = await api("/api/accounts/check", { method: "POST", body: JSON.stringify({}) });
    toast(`Tekshiruv: ${start.total} akkaunt...`, "info");
    const res = await pollJob(start.job_id, "Tekshiruv");
    if (res) {
      const alive = res.results.filter((r) => r.ok).length;
      state.accounts = res.accounts; refreshAccountsUI();
      toast(`🟢 ${alive} tirik · 🔴 ${res.total - alive} o'lik`, alive ? "ok" : "err");
    }
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

async function doWarmupAll() {
  const btn = $("warmup-all-btn");
  if (!confirm("Akkauntlarni 'isitish' (yengil feed ko'rish) — sessiya uzoq yashashiga yordam. Davom etamizmi?")) return;
  setLoading(btn, true);
  try {
    const start = await api("/api/accounts/warmup", { method: "POST", body: JSON.stringify({}) });
    toast(`Isitish: ${start.total} akkaunt...`, "info");
    const res = await pollJob(start.job_id, "Isitish");
    if (res) { state.accounts = res.accounts; refreshAccountsUI(); reportResults(res, "Isitish"); }
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

// AVTO: link uchun har akkaunt o'z xususiyatiga mos komment yozadi + like bosadi
async function doAutoRun() {
  const text = $("input-text").value.trim();
  const m = text.match(/https?:\/\/(www\.)?instagram\.com\/\S+/);
  if (!m) { toast("Avval Instagram havolasini kiriting", "err"); return; }
  const provider = $("provider-select").value;
  const btn = $("auto-btn");
  setLoading(btn, true);
  try {
    const r = await api("/api/run", {
      method: "POST", body: JSON.stringify({ url: m[0], provider, like: true }),
    });
    const eta = r.last_at ? new Date(r.last_at * 1000).toLocaleString() : "?";
    toast(`✅ ${r.queued} akkaunt navbatga qo'shildi. Vaqtga taqsimlab (≥3 daq oraliq) joylanadi. Oxirgisi ~${eta}`, "ok");
    loadQueue();
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

// ---------- Navbat (global queue) ----------
async function loadQueue() {
  try {
    const q = await api("/api/queue");
    const el = $("queue-info");
    if (!el) return;
    if (q.pending === 0) {
      el.innerHTML = `<span class="muted">Navbat bo'sh</span> · ✅ ${q.done} joylangan${q.failed ? " · ❌ " + q.failed : ""}`;
    } else {
      const mins = Math.round((q.next_in || 0) / 60);
      const lastTxt = q.last_at ? new Date(q.last_at * 1000).toLocaleString() : "?";
      el.innerHTML = `⏳ <b>${q.pending}</b> kutyapti · keyingisi ~${mins} daq · oxirgisi ${lastTxt} · ✅ ${q.done}${q.failed ? " · ❌ " + q.failed : ""}`;
    }
  } catch (_) {}
}

async function doClearQueue() {
  if (!confirm("Navbatdagi (hali joylanmagan) kommentlarni bekor qilamizmi?")) return;
  try {
    const r = await api("/api/queue/clear", { method: "POST" });
    toast(`${r.cleared} ta navbatdan o'chirildi`, "info");
    loadQueue();
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  }
}

// ---------- Modemlar (o'z 4G IP pool) ----------
async function loadModems() {
  try {
    const res = await api("/api/modems");
    renderModems(res.modems || []);
  } catch (_) { /* modem yo'q bo'lsa jim */ }
}

function renderModems(modems) {
  const box = $("modems-list");
  if (!modems.length) {
    box.innerHTML = '<p class="muted empty">Hali modem yo\'q. Quyidan qo\'shing yoki Avto-aniqlash bosing.</p>';
    return;
  }
  box.innerHTML = "";
  modems.forEach((m) => {
    const row = document.createElement("div");
    row.className = "account-row";
    const rot = m.rotate_type ? `↻ ${m.rotate_type}` : "rotation yo'q";
    row.innerHTML = `
      <span class="acc-name" title="${m.label}"><span class="dot"></span>${m.label}</span>
      <span class="acc-usage" title="Biriktirilgan akkauntlar">${m.accounts} akk · <code>${m.ext_ip}</code></span>
      <span class="muted modem-ip" id="mip-${m.id}" title="Joriy tashqi IP">?</span>
      <button class="acc-icon" data-act="ip" title="IP'ni tekshirish">🌐</button>
      <button class="acc-icon" data-act="rot" title="${rot} — IP'ni yangilash">↻</button>
      <button class="acc-icon acc-remove" title="O'chirish">×</button>`;
    row.querySelector('[data-act="ip"]').onclick = (e) => doModemIp(m.id, e.currentTarget);
    row.querySelector('[data-act="rot"]').onclick = (e) => doRotateModem(m.id, e.currentTarget);
    row.querySelector(".acc-remove").onclick = () => doRemoveModem(m.id);
    box.appendChild(row);
  });
}

async function doAddModem() {
  const ext_ip = $("modem-extip").value.trim();
  if (!ext_ip) { toast("ext_ip kiriting", "err"); return; }
  const label = $("modem-label").value.trim();
  const rotate_type = $("modem-rotate-type").value;
  const rv = $("modem-rotate-val").value.trim();
  const body = { ext_ip, label, rotate_type,
    rotate_url: rotate_type === "huawei" ? rv : "",
    rotate_serial: rotate_type === "adb" ? rv : "" };
  const btn = $("modem-add-btn");
  setLoading(btn, true);
  try {
    const res = await api("/api/modems", { method: "POST", body: JSON.stringify(body) });
    $("modem-extip").value = ""; $("modem-label").value = ""; $("modem-rotate-val").value = "";
    renderModems(res.modems);
    toast(`Modem qo'shildi: ${res.modem.label} → port ${res.modem.port}`, "ok");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

async function doRemoveModem(id) {
  if (!confirm(`${id} modem o'chirilsinmi? (akkauntlar bo'shaydi)`)) return;
  try {
    const res = await api(`/api/modems/${encodeURIComponent(id)}`, { method: "DELETE" });
    renderModems(res.modems);
    toast(`${id} o'chirildi`, "info");
  } catch (e) { toast(e.message, "err"); }
}

async function doModemIp(id, btn) {
  setLoading(btn, true);
  try {
    const res = await api(`/api/modems/${encodeURIComponent(id)}/ip`, { method: "POST" });
    const el = $(`mip-${id}`); if (el) el.textContent = res.ip;
    toast(`${id}: ${res.ip}`, "ok");
  } catch (e) { toast(`${id}: ${e.message}`, "err"); }
  finally { setLoading(btn, false); }
}

async function doRotateModem(id, btn) {
  setLoading(btn, true);
  try {
    const res = await api(`/api/modems/${encodeURIComponent(id)}/rotate`, { method: "POST" });
    const el = $(`mip-${id}`); if (el) el.textContent = res.ip;
    toast(`${id}: yangi IP → ${res.ip}`, "ok");
  } catch (e) { toast(`${id}: ${e.message}`, "err"); }
  finally { setLoading(btn, false); }
}

async function doDetectModems(btn) {
  setLoading(btn, true);
  try {
    const res = await api("/api/modems/detect", { method: "POST" });
    const c = res.candidates || [];
    if (!c.length) { toast("Modemga o'xshash interfeys topilmadi", "info"); return; }
    // Birinchi taklifni formaga to'ldiramiz
    $("modem-extip").value = c[0].ext_ip;
    if (c[0].guess_rotate_url) {
      $("modem-rotate-type").value = "huawei";
      $("modem-rotate-val").value = c[0].guess_rotate_url;
    }
    toast(`${c.length} ta nomzod topildi — birinchisi formaga to'ldirildi`, "ok");
  } catch (e) { toast(e.message, "err"); }
  finally { setLoading(btn, false); }
}

async function doGenConfig(btn) {
  setLoading(btn, true);
  try {
    const res = await api("/api/modems/config", { method: "POST" });
    const out = $("modems-config-out");
    out.style.display = "";
    out.textContent = `# saqlandi: ${res.path}\n\n${res.config}`;
    toast("3proxy config yaratildi", "ok");
  } catch (e) { toast(e.message, "err"); }
  finally { setLoading(btn, false); }
}

async function doAssignAll(btn) {
  if (!confirm("Barcha akkauntlar modemlarga balanslab taqsimlansinmi?")) return;
  setLoading(btn, true);
  try {
    const res = await api("/api/modems/assign-all", { method: "POST" });
    state.accounts = res.accounts;
    refreshAccountsUI();
    renderModems(res.modems);
    toast("Akkauntlar modemlarga taqsimlandi ✓", "ok");
  } catch (e) { toast(e.message, "err"); }
  finally { setLoading(btn, false); }
}

// ---------- Generate ----------
async function doGenerate() {
  const text = $("input-text").value.trim();
  if (!text) { toast("Avval havola yoki mavzu kiriting", "err"); return; }
  const provider = $("provider-select").value;
  if (!provider) { toast("AI provayder yo'q — .env'da API kalit qo'shing", "err"); return; }

  const btn = $("generate-btn");
  setLoading(btn, true);
  $("generate-hint").textContent = "O'qilmoqda va kommentlar yaratilmoqda...";
  try {
    const data = await api("/api/generate", { method: "POST", body: JSON.stringify({ text, provider }) });
    state.mediaId = data.media_id; state.url = data.url; state.comments = data.comments;
    renderResults(data);
    $("results").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); $("generate-hint").textContent = ""; }
}

function renderResults(data) {
  $("results").classList.remove("hidden");
  $("desc-text").textContent = data.description;
  $("pick-accounts-card").classList.toggle("hidden", !data.has_media);
  $("actions-card").classList.toggle("hidden", !data.has_media);

  const grid = $("comments-grid");
  grid.innerHTML = "";
  ["yumor", "aqlli", "bahsli"].forEach((key, i) => {
    const meta = STYLE_META[key];
    const card = document.createElement("div");
    card.className = "comment-card";
    card.style.setProperty("--i", i);
    card.innerHTML = `
      <span class="badge ${meta.badge}">${meta.label}</span>
      <p></p>
      <div class="comment-actions">
        <button class="btn btn--ghost btn--sm" data-act="copy">Nusxalash</button>
        <button class="btn btn--primary btn--sm" data-act="post" ${data.has_media ? "" : "disabled"}>
          ${data.has_media ? "Joylash" : "Havola yo'q"}
        </button>
      </div>`;
    card.querySelector("p").textContent = data.comments[key];
    card.querySelector('[data-act="copy"]').onclick = () => {
      navigator.clipboard.writeText(data.comments[key]); toast("Nusxalandi", "ok");
    };
    if (data.has_media) {
      const pb = card.querySelector('[data-act="post"]');
      pb.onclick = () => doPost(key, data.comments[key], pb);
    }
    grid.appendChild(card);
  });
}

// ---------- Post ----------
// Fon-job holatini so'rab turadi (504 bo'lmasin — amal fonда ketma-ket bajariladi).
async function pollJob(jobId, label) {
  while (true) {
    let j;
    try { j = await api(`/api/job/${jobId}`); }
    catch (e) { if (e.status === 401) { location.reload(); return null; } throw e; }
    if (j.finished) return j;
    const waitTxt = j.next_in > 0 ? ` · keyingisi ~${j.next_in}s dan keyin` : "";
    toast(`${label}: ${j.done}/${j.total} bajarildi${waitTxt}...`, "info");
    await new Promise((r) => setTimeout(r, 3000));
  }
}

async function doPost(style, text, btn) {
  const usernames = selectedUsernames();
  if (!usernames.length) { toast("Kamida bitta akkaunt belgilang", "err"); return; }
  setLoading(btn, true);
  try {
    const start = await api("/api/post", {
      method: "POST",
      body: JSON.stringify({ media_id: state.mediaId, style, text, url: state.url, usernames }),
    });
    toast(`Komment: ${start.total} akkaunt navbatda (fon rejimi)...`, "info");
    const res = await pollJob(start.job_id, "Komment");
    if (!res) return;
    const ok = res.results.filter((r) => r.ok);
    const fail = res.results.filter((r) => !r.ok);
    state.accounts = res.accounts;
    refreshAccountsUI();

    if (ok.length) {
      btn.classList.remove("btn--primary", "loading");
      btn.classList.add("btn--success");
      btn.textContent = `✓ ${ok.length} akkaunt`;
      btn.disabled = true;
    } else setLoading(btn, false);

    if (fail.length) {
      toast(`${ok.length} ta joylandi, ${fail.length} xato: ${fail.map((f) => "@" + f.username + " — " + f.error).join("; ")}`,
            ok.length ? "info" : "err");
    } else toast(`${ok.length} ta akkauntdan joylandi`, "ok");
    loadHistory();
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err"); setLoading(btn, false);
  }
}

// ---------- Like / Repost ----------
function reportResults(res, label) {
  const ok = res.results.filter((r) => r.ok);
  const fail = res.results.filter((r) => !r.ok);
  state.accounts = res.accounts;
  refreshAccountsUI();
  if (fail.length) {
    toast(`${label}: ${ok.length} ok, ${fail.length} xato — ${fail.map((f) => "@" + f.username + ": " + f.error).join("; ")}`,
          ok.length ? "info" : "err");
  } else {
    toast(`${label}: ${ok.length} akkauntda bajarildi`, "ok");
  }
  loadHistory();
}

async function doView(btn) {
  const usernames = selectedUsernames();
  if (!usernames.length) { toast("Kamida bitta akkaunt belgilang", "err"); return; }
  setLoading(btn, true);
  try {
    const start = await api("/api/view", {
      method: "POST",
      body: JSON.stringify({ media_id: state.mediaId, url: state.url, usernames }),
    });
    toast(`Ko'rish: ${start.total} akkaunt navbatda...`, "info");
    const res = await pollJob(start.job_id, "Ko'rish");
    if (res) reportResults(res, "Ko'rish");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

async function doLike(btn) {
  const usernames = selectedUsernames();
  if (!usernames.length) { toast("Kamida bitta akkaunt belgilang", "err"); return; }
  setLoading(btn, true);
  try {
    const start = await api("/api/like", {
      method: "POST",
      body: JSON.stringify({ media_id: state.mediaId, url: state.url, usernames }),
    });
    toast(`Like: ${start.total} akkaunt navbatda...`, "info");
    const res = await pollJob(start.job_id, "Like");
    if (res) reportResults(res, "Like");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

async function doStory(btn) {
  if (!REPOST_STORY_ENABLED) { alert(REPOST_STORY_MSG); return; }
  const usernames = selectedUsernames();
  if (!usernames.length) { toast("Kamida bitta akkaunt belgilang", "err"); return; }
  if (!confirm("Story: post yuklab olinib, tanlangan akkauntlar Story'siga joylanadi (24 soat).\nDavom etamizmi?")) return;
  setLoading(btn, true);
  try {
    const res = await api("/api/story", {
      method: "POST",
      body: JSON.stringify({ url: state.url, usernames }),
    });
    reportResults(res, "Story");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

async function doRepost(btn) {
  if (!REPOST_STORY_ENABLED) { alert(REPOST_STORY_MSG); return; }
  const usernames = selectedUsernames();
  if (!usernames.length) { toast("Kamida bitta akkaunt belgilang", "err"); return; }
  if (!confirm("Repost: post yuklab olinib, tanlangan akkauntlar profiliga joylanadi.\nBan xavfi yuqori. Davom etamizmi?")) return;
  setLoading(btn, true);
  try {
    const res = await api("/api/repost", {
      method: "POST",
      body: JSON.stringify({ url: state.url, caption: $("repost-caption").value, usernames }),
    });
    reportResults(res, "Repost");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

// ---------- History + distribution ----------
async function loadHistory() {
  try {
    const { items } = await api("/api/history");
    animateCount($("stat-history"), items.length);
    renderDistribution(items);

    const list = $("history-list");
    if (!items.length) { list.innerHTML = '<p class="muted empty">Hozircha bo\'sh.</p>'; return; }
    list.innerHTML = "";
    items.forEach((it, i) => {
      const meta = STYLE_META[it.style];
      const row = document.createElement("div");
      row.className = "history-item";
      row.style.animationDelay = `${Math.min(i, 10) * 35}ms`;
      row.innerHTML = `
        <span class="badge ${meta ? meta.badge : "badge--neutral"}">${meta ? meta.short : (ACTION_ICON[it.style] || it.style)}</span>
        <div class="h-body">
          <div class="h-text"></div>
          <div class="meta">${it.username ? "@" + it.username + " · " : ""}${it.time}</div>
        </div>`;
      row.querySelector(".h-text").textContent = it.text;
      list.appendChild(row);
    });
  } catch (_) {}
}

function renderDistribution(items) {
  const box = $("dist");
  if (!items.length) { box.innerHTML = ""; return; }
  const counts = { yumor: 0, aqlli: 0, bahsli: 0 };
  items.forEach((it) => { if (counts[it.style] !== undefined) counts[it.style]++; });
  const max = Math.max(1, ...Object.values(counts));
  box.innerHTML = "";
  for (const key of ["yumor", "aqlli", "bahsli"]) {
    const meta = STYLE_META[key];
    const row = document.createElement("div");
    row.className = "dist-row";
    row.innerHTML = `
      <span class="lbl">${meta.short} ${key}</span>
      <span class="dist-track"><span class="dist-fill ${meta.cls}"></span></span>
      <span class="val">${counts[key]}</span>`;
    box.appendChild(row);
    const fill = row.querySelector(".dist-fill");
    requestAnimationFrame(() => { fill.style.width = (counts[key] / max * 100) + "%"; });
  }
}

// ---------- Sozlamalar ----------
const SET_FIELDS = [
  "claude_model", "groq_model", "mistral_model",
  "max_comments_per_day", "min_seconds_between_comments",
  "random_delay_min", "random_delay_max",
];
const SECRET_STATE = {
  claude: "anthropic_api_key_set",
  groq: "groq_api_key_set",
  mistral: "mistral_api_key_set",
};

function setProvState(prov, set) {
  const el = $("state-" + prov);
  if (!el) return;
  el.textContent = set ? "● ulangan" : "● yo'q";
  el.className = "prov-state " + (set ? "on" : "off");
}

async function openSettings() {
  try {
    const data = await api("/api/settings");
    SET_FIELDS.forEach((k) => { const el = $("set-" + k); if (el && data[k] != null) el.value = data[k]; });
    // maxfiy kalit inputlari bo'sh, holat span'lar ko'rsatadi
    ["anthropic_api_key", "groq_api_key", "mistral_api_key", "panel_password"].forEach((k) => {
      const el = $("set-" + k); if (el) el.value = "";
    });
    for (const [prov, key] of Object.entries(SECRET_STATE)) setProvState(prov, !!data[key]);
    $("settings-msg").textContent = "";
    $("settings-overlay").classList.remove("hidden");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  }
}

function closeSettings() { $("settings-overlay").classList.add("hidden"); }

async function saveSettings() {
  const btn = $("settings-save");
  setLoading(btn, true);
  const payload = {};
  SET_FIELDS.forEach((k) => { const el = $("set-" + k); if (el) payload[k] = el.value; });
  ["anthropic_api_key", "groq_api_key", "mistral_api_key", "panel_password"].forEach((k) => {
    const v = $("set-" + k).value.trim();
    if (v) payload[k] = v; // bo'sh bo'lsa yubormaymiz (eskisi saqlanadi)
  });
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify(payload) });
    toast("Sozlamalar saqlandi", "ok");
    closeSettings();
    await loadStatus();   // provayderlar/limit yangilanadi
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

async function testProvider(prov, btn) {
  const keyEl = $("set-" + (prov === "claude" ? "anthropic" : prov) + "_api_key");
  const modelEl = $("set-" + (prov === "claude" ? "claude" : prov) + "_model");
  setLoading(btn, true);
  setProvState(prov, false);
  $("state-" + prov).textContent = "tekshirilmoqda…";
  $("state-" + prov).className = "prov-state";
  try {
    const res = await api("/api/settings/test", {
      method: "POST",
      body: JSON.stringify({ provider: prov, api_key: keyEl ? keyEl.value.trim() : "", model: modelEl ? modelEl.value.trim() : "" }),
    });
    $("state-" + prov).textContent = "✓ ishlaydi";
    $("state-" + prov).className = "prov-state on";
    toast(res.message, "ok");
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    $("state-" + prov).textContent = "✕ xato";
    $("state-" + prov).className = "prov-state off";
    toast(e.message, "err");
  } finally { setLoading(btn, false); }
}

// ---------- Wire up ----------
initTheme();
injectRingGradient();
$("login-btn").onclick = doLogin;
$("login-password").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
$("logout-btn").onclick = doLogout;
$("ig-add-btn").onclick = doAddAccount;
$("sessionid-input").addEventListener("keydown", (e) => { if (e.key === "Enter") doAddAccount(); });
$("ig-login-btn").onclick = doLoginAccount;
$("ig-2fa-btn").onclick = doVerify2FA;
$("iglogin-password").addEventListener("keydown", (e) => { if (e.key === "Enter") doLoginAccount(); });
$("iglogin-2fa").addEventListener("keydown", (e) => { if (e.key === "Enter") doVerify2FA(); });
$("modem-add-btn").onclick = doAddModem;
$("modems-detect-btn").onclick = (e) => doDetectModems(e.currentTarget);
$("modems-config-btn").onclick = (e) => doGenConfig(e.currentTarget);
$("modems-assign-btn").onclick = (e) => doAssignAll(e.currentTarget);
$("generate-btn").onclick = doGenerate;
$("auto-btn").onclick = doAutoRun;
if ($("queue-refresh")) $("queue-refresh").onclick = loadQueue;
if ($("queue-clear")) $("queue-clear").onclick = doClearQueue;
$("check-all-btn").onclick = doCheckAll;
if ($("warmup-all-btn")) $("warmup-all-btn").onclick = doWarmupAll;  // warm-up olib tashlandi (ixtiyoriy)
$("view-btn").onclick = () => doView($("view-btn"));
$("like-btn").onclick = () => doLike($("like-btn"));
$("story-btn").onclick = () => doStory($("story-btn"));
$("repost-btn").onclick = () => doRepost($("repost-btn"));

// Repost/Story o'chirilgan bo'lsa — vizual "off" ko'rinish (bosilsa xabar chiqadi).
if (!REPOST_STORY_ENABLED) {
  for (const id of ["story-btn", "repost-btn"]) {
    const b = $(id);
    if (!b) continue;
    b.classList.add("btn--off");
    b.title = "Vaqtincha o'chirilgan — GB tejash uchun (bosing: batafsil)";
    b.textContent = b.textContent.trim() + " 🔒";
  }
}
$("refresh-history").onclick = loadHistory;
$("settings-toggle").onclick = openSettings;
$("settings-close").onclick = closeSettings;
$("settings-cancel").onclick = closeSettings;
$("settings-save").onclick = saveSettings;
$("settings-overlay").addEventListener("click", (e) => { if (e.target.id === "settings-overlay") closeSettings(); });
document.querySelectorAll(".prov-test").forEach((b) => { b.onclick = () => testProvider(b.dataset.prov, b); });
$("toggle-all").onclick = () => {
  const boxes = [...document.querySelectorAll("#pick-accounts input")];
  const allOn = boxes.every((b) => b.checked);
  boxes.forEach((b) => (b.checked = !allOn));
};

(async () => { const ok = await loadStatus(); if (ok) { loadHistory(); loadQueue(); setInterval(loadQueue, 30000); } })();
