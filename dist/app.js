const state = {
  sessions: [],
  selected: new Set(),
  sort: "created",
  sortDesc: true,
  editingProvider: "",
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = {error: text};
    }
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

function setStatus(id, message, kind = "") {
  const el = $(id);
  el.textContent = message || "";
  const tone = kind === "ok" ? "text-emerald-600" : kind === "err" ? "text-red-600" : "text-slate-500";
  if (!el.dataset.baseClass) el.dataset.baseClass = el.className || "status";
  el.className = `${el.dataset.baseClass} ${tone}`;
}

function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === name);
  });
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.id === "tab-" + name);
  });
}

function openAddProviderModal() {
  setStatus("addProviderStatus", "");
  $("addProviderModal").classList.add("active");
  $("providerName").focus();
}

function closeAddProviderModal() {
  $("addProviderModal").classList.remove("active");
}

async function loadProfiles() {
  try {
    const data = await api("/api/provider-profiles");
    $("codexDir").textContent = data.codex_dir;
    const list = $("profileList");
    list.innerHTML = "";
    if (!data.profiles.length) {
      list.innerHTML = '<div class="rounded-lg border border-dashed border-slate-300 bg-white/50 p-5 text-sm text-slate-500">还没有 provider profile。</div>';
      return;
    }
    for (const profile of data.profiles) {
      const item = document.createElement("div");
      item.className = "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-slate-200/70 bg-white/65 p-4 transition hover:bg-white max-md:grid-cols-1";
      item.innerHTML = `
        <div class="min-w-0">
          <strong class="block truncate text-sm font-semibold text-slate-950">${escapeHtml(profile.name)}</strong>
          <div class="mt-2 flex flex-wrap gap-1.5">
            <span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-bold text-slate-600">${profile.has_config ? "config.toml" : "缺 config"}</span>
            <span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-bold text-slate-600">${profile.has_auth ? "auth.json" : "缺 auth"}</span>
          </div>
        </div>
        <div class="flex flex-wrap items-center justify-end gap-2 max-md:justify-start">
          <button data-edit-profile="${escapeAttr(profile.name)}" class="rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-800 transition hover:bg-white hover:shadow-sm">查看/编辑</button>
          <button data-switch="${escapeAttr(profile.name)}" class="primary rounded-full bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm shadow-blue-600/20 transition hover:bg-blue-700">切换</button>
          <button data-delete-profile="${escapeAttr(profile.name)}" class="danger rounded-full border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-600 transition hover:bg-red-100">删除</button>
        </div>`;
      list.appendChild(item);
    }
  } catch (error) {
    setStatus("providerStatus", error.message, "err");
  }
}

async function editProfile(name) {
  try {
    const data = await api(`/api/provider-profiles/detail?name=${encodeURIComponent(name)}`);
    state.editingProvider = data.name;
    $("editProviderTitle").textContent = data.name;
    $("editProviderConfig").value = data.config_toml || "";
    $("editProviderAuth").value = data.auth_json || "";
    setStatus("editProviderStatus", "");
    $("providerModal").classList.add("active");
  } catch (error) {
    setStatus("providerStatus", error.message, "err");
  }
}

async function saveProfileEdits() {
  if (!state.editingProvider) return;
  try {
    await api("/api/provider-profiles/update", {
      method: "POST",
      body: JSON.stringify({
        name: state.editingProvider,
        config_toml: $("editProviderConfig").value,
        auth_json: $("editProviderAuth").value,
      }),
    });
    setStatus("editProviderStatus", "Profile 已保存。", "ok");
    setStatus("providerStatus", `Provider "${state.editingProvider}" 已更新。`, "ok");
    await loadProfiles();
  } catch (error) {
    setStatus("editProviderStatus", error.message, "err");
  }
}

async function addProvider() {
  try {
    await api("/api/provider-profiles", {
      method: "POST",
      body: JSON.stringify({
        name: $("providerName").value,
        config_toml: $("providerConfig").value,
        auth_json: $("providerAuth").value,
      }),
    });
    setStatus("addProviderStatus", "Provider 已添加。", "ok");
    setStatus("providerStatus", "Provider 已添加。", "ok");
    $("providerName").value = "";
    $("providerConfig").value = "";
    $("providerAuth").value = "";
    await loadProfiles();
    closeAddProviderModal();
  } catch (error) {
    setStatus("addProviderStatus", error.message, "err");
  }
}

async function loadCurrentProviderFiles() {
  try {
    const data = await api("/api/provider-current");
    $("providerConfig").value = data.config_toml || "";
    $("providerAuth").value = data.auth_json || "";
    setStatus("addProviderStatus", "已读取当前 ~/.codex/config.toml 和 auth.json。", "ok");
  } catch (error) {
    setStatus("addProviderStatus", error.message, "err");
  }
}

async function switchProvider(name) {
  if (!confirm(`确认切换到 provider profile "${name}"? 当前 config/auth 会先备份。`)) return;
  try {
    const data = await api("/api/provider-profiles/switch", {
      method: "POST",
      body: JSON.stringify({name}),
    });
    setStatus("providerStatus", `已切换。备份目录: ${data.backup_dir}`, "ok");
  } catch (error) {
    setStatus("providerStatus", error.message, "err");
  }
}

async function deleteProfile(name) {
  if (!confirm(`删除 provider profile "${name}"?`)) return;
  try {
    await api("/api/provider-profiles/delete", {
      method: "POST",
      body: JSON.stringify({name}),
    });
    setStatus("providerStatus", "Profile 已删除。", "ok");
    await loadProfiles();
  } catch (error) {
    setStatus("providerStatus", error.message, "err");
  }
}

function sortParams() {
  return `sort=${encodeURIComponent(state.sort)}&desc=${state.sortDesc ? "1" : "0"}`;
}

async function loadSessions() {
  try {
    const q = encodeURIComponent($("sessionSearch").value);
    const archived = $("includeArchived").checked ? "1" : "0";
    const data = await api(`/api/sessions?q=${q}&include_archived=${archived}&${sortParams()}`);
    state.sessions = data.sessions;
    state.selected = new Set([...state.selected].filter((id) => state.sessions.some((s) => s.id === id)));
    renderSessions();
    setStatus("sessionStatus", `${data.sessions.length} sessions loaded. ${state.selected.size} selected.`);
  } catch (error) {
    setStatus("sessionStatus", error.message, "err");
  }
}

function renderSessions() {
  const body = $("sessionsBody");
  body.innerHTML = "";
  for (const session of state.sessions) {
    const tr = document.createElement("tr");
    tr.className = "transition hover:bg-white/65";
    tr.innerHTML = `
      <td class="px-4 py-3 align-top"><input class="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" type="checkbox" data-select="${escapeAttr(session.id)}" ${state.selected.has(session.id) ? "checked" : ""}></td>
      <td class="whitespace-nowrap px-4 py-3 align-top text-slate-600">${escapeHtml(session.created_label)}</td>
      <td class="px-4 py-3 align-top"><span class="inline-flex min-h-6 items-center rounded-full bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">${escapeHtml(session.model_provider)}</span></td>
      <td class="whitespace-nowrap px-4 py-3 align-top font-medium text-slate-700">${escapeHtml(session.project)}</td>
      <td class="max-w-[620px] truncate px-4 py-3 align-top text-slate-800" title="${escapeAttr(session.title)}">${escapeHtml(session.title)}</td>
      <td class="px-4 py-3 align-top"><button data-detail="${escapeAttr(session.id)}" class="rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-800 transition hover:bg-white hover:shadow-sm">详情</button></td>`;
    body.appendChild(tr);
  }
  $("selectAllSessions").checked = state.sessions.length > 0 && state.sessions.every((s) => state.selected.has(s.id));
  updateSortMarks();
}

function updateSortMarks() {
  $("createdSortMark").textContent = state.sort === "created" ? (state.sortDesc ? "↓" : "↑") : "";
  $("providerSortMark").textContent = state.sort === "provider" ? "*" : "";
  $("projectsSortMark").textContent = state.sort === "projects" ? "*" : "";
}

function setSessionSort(sortKey) {
  if (sortKey === "created") {
    if (state.sort === "created") state.sortDesc = !state.sortDesc;
    else {
      state.sort = "created";
      state.sortDesc = true;
    }
  } else {
    state.sort = sortKey;
    state.sortDesc = false;
  }
  loadSessions();
}

async function updateSelectedProvider() {
  const ids = [...state.selected];
  const provider = $("targetProvider").value.trim();
  if (!ids.length) return setStatus("sessionStatus", "请先选择 session。", "err");
  if (!provider) return setStatus("sessionStatus", "请输入目标 provider。", "err");
  try {
    const data = await api("/api/sessions/provider", {
      method: "POST",
      body: JSON.stringify({ids, provider}),
    });
    setStatus("sessionStatus", `已更新 ${data.sqlite_rows} 条 sqlite 记录，${data.jsonl_files} 个 jsonl。`, "ok");
    await loadSessions();
  } catch (error) {
    setStatus("sessionStatus", error.message, "err");
  }
}

async function deleteSelectedSessions() {
  const ids = [...state.selected];
  if (!ids.length) return setStatus("sessionStatus", "请先选择 session。", "err");
  if (!confirm(`确认删除 ${ids.length} 个 session? 删除前会自动备份。`)) return;
  try {
    const data = await api("/api/sessions/delete", {
      method: "POST",
      body: JSON.stringify({ids}),
    });
    state.selected.clear();
    setStatus("sessionStatus", `已删除 ${data.sqlite_rows} 条 sqlite 记录，${data.jsonl_files} 个 jsonl。备份: ${data.backup_dir}`, "ok");
    await loadSessions();
  } catch (error) {
    setStatus("sessionStatus", error.message, "err");
  }
}

async function showDetail(id) {
  try {
    const data = await api(`/api/sessions/detail?id=${encodeURIComponent(id)}`);
    $("detailTitle").textContent = data.title || "Session 详情";
    $("detailMeta").innerHTML = `
      <div class="grid grid-cols-[96px_minmax(0,1fr)] gap-3"><strong class="text-slate-950">ID</strong><span class="break-all">${escapeHtml(data.id)}</span></div>
      <div class="grid grid-cols-[96px_minmax(0,1fr)] gap-3"><strong class="text-slate-950">CWD</strong><span class="break-all">${escapeHtml(data.cwd)}</span></div>
      <div class="grid grid-cols-[96px_minmax(0,1fr)] gap-3"><strong class="text-slate-950">Created</strong><span class="break-all">${escapeHtml(data.created_label)}</span></div>
      <div class="grid grid-cols-[96px_minmax(0,1fr)] gap-3"><strong class="text-slate-950">Provider</strong><span class="break-all">${escapeHtml(data.model_provider)}</span></div>
      <div class="grid grid-cols-[96px_minmax(0,1fr)] gap-3"><strong class="text-slate-950">Project</strong><span class="break-all">${escapeHtml(data.project)}</span></div>
      <div class="grid grid-cols-[96px_minmax(0,1fr)] gap-3"><strong class="text-slate-950">JSONL</strong><span class="break-all">${escapeHtml(data.rollout_path)}</span></div>`;
    $("detailConversation").textContent = data.conversation.join("\n");
    $("detailModal").classList.add("active");
  } catch (error) {
    setStatus("sessionStatus", error.message, "err");
  }
}

async function loadEnv() {
  try {
    const data = await api("/api/env");
    renderEnvRows(data.entries);
    setStatus("envStatus", data.exists ? "已读取 .env。" : "~/.codex/.env 不存在，保存后会创建。");
  } catch (error) {
    setStatus("envStatus", error.message, "err");
  }
}

function renderEnvRows(entries) {
  const root = $("envRows");
  root.innerHTML = "";
  const rows = entries.length ? entries : [{key: "", value: ""}];
  for (const entry of rows) addEnvRow(entry.key || "", entry.value || "");
}

function addEnvRow(key = "", value = "") {
  const row = document.createElement("div");
  row.className = "env-row grid grid-cols-[minmax(180px,260px)_minmax(260px,1fr)_auto] items-center gap-3 max-md:grid-cols-1";
  row.innerHTML = `
    <input class="rounded-lg border border-slate-200 bg-white/85 px-3 py-2.5 text-sm text-slate-950 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10" placeholder="KEY" value="${escapeAttr(key)}">
    <input class="rounded-lg border border-slate-200 bg-white/85 px-3 py-2.5 text-sm text-slate-950 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10" placeholder="VALUE" value="${escapeAttr(value)}">
    <button class="danger rounded-full border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-600 transition hover:bg-red-100">删除</button>`;
  row.querySelector("button").addEventListener("click", () => row.remove());
  $("envRows").appendChild(row);
}

async function saveEnv() {
  const entries = [...document.querySelectorAll(".env-row")].map((row) => {
    const inputs = row.querySelectorAll("input");
    return {key: inputs[0].value.trim(), value: inputs[1].value};
  }).filter((entry) => entry.key);
  try {
    await api("/api/env", {
      method: "POST",
      body: JSON.stringify({entries}),
    });
    setStatus("envStatus", "已保存 .env。", "ok");
    await loadEnv();
  } catch (error) {
    setStatus("envStatus", error.message, "err");
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function escapeAttr(value) {
  return escapeHtml(value);
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.body.addEventListener("click", (event) => {
  const switchName = event.target.dataset.switch;
  const deleteName = event.target.dataset.deleteProfile;
  const editName = event.target.dataset.editProfile;
  const detailId = event.target.dataset.detail;
  if (switchName) switchProvider(switchName);
  if (deleteName) deleteProfile(deleteName);
  if (editName) editProfile(editName);
  if (detailId) showDetail(detailId);
});

document.body.addEventListener("change", (event) => {
  const selectId = event.target.dataset.select;
  if (selectId) {
    if (event.target.checked) state.selected.add(selectId);
    else state.selected.delete(selectId);
    renderSessions();
    setStatus("sessionStatus", `${state.sessions.length} sessions loaded. ${state.selected.size} selected.`);
  }
});

$("addProviderBtn").addEventListener("click", addProvider);
$("openAddProviderBtn").addEventListener("click", openAddProviderModal);
$("closeAddProviderModalBtn").addEventListener("click", closeAddProviderModal);
$("addProviderModal").addEventListener("click", (event) => {
  if (event.target.id === "addProviderModal") closeAddProviderModal();
});
$("loadCurrentProviderBtn").addEventListener("click", loadCurrentProviderFiles);
$("sessionSearch").addEventListener("input", () => loadSessions());
$("includeArchived").addEventListener("change", () => loadSessions());
$("refreshSessionsBtn").addEventListener("click", loadSessions);
$("changeProviderBtn").addEventListener("click", updateSelectedProvider);
$("deleteSessionsBtn").addEventListener("click", deleteSelectedSessions);
$("selectAllSessions").addEventListener("change", (event) => {
  if (event.target.checked) state.sessions.forEach((s) => state.selected.add(s.id));
  else state.selected.clear();
  renderSessions();
  setStatus("sessionStatus", `${state.sessions.length} sessions loaded. ${state.selected.size} selected.`);
});
document.querySelectorAll("th.sortable").forEach((th) => {
  th.addEventListener("click", () => setSessionSort(th.dataset.sort));
});
$("closeDetailBtn").addEventListener("click", () => $("detailModal").classList.remove("active"));
$("detailModal").addEventListener("click", (event) => {
  if (event.target.id === "detailModal") $("detailModal").classList.remove("active");
});
$("closeProviderModalBtn").addEventListener("click", () => $("providerModal").classList.remove("active"));
$("providerModal").addEventListener("click", (event) => {
  if (event.target.id === "providerModal") $("providerModal").classList.remove("active");
});
$("saveProviderEditBtn").addEventListener("click", saveProfileEdits);
$("addEnvRowBtn").addEventListener("click", () => addEnvRow());
$("saveEnvBtn").addEventListener("click", saveEnv);
$("reloadEnvBtn").addEventListener("click", loadEnv);

loadProfiles();
loadSessions();
loadEnv();
