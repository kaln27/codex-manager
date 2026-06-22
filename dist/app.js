const state = {
  sessions: [],
  selected: new Set(),
  sort: "created",
  sortDesc: true,
  editingProvider: "",
  switchingProvider: "",
  confirmResolve: null,
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
  if (response.status === 401) {
    window.location.href = "/login.html";
    throw new Error(data.error || "Authentication required.");
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

async function logout() {
  try {
    await api("/api/logout", {method: "POST", body: JSON.stringify({})});
  } finally {
    window.location.href = "/login.html";
  }
}

function setStatus(id, message, kind = "") {
  const el = $(id);
  if (!el) return;
  el.textContent = message || "";
  el.classList.remove("status--ok", "status--err");
  if (kind === "ok") el.classList.add("status--ok");
  else if (kind === "err") el.classList.add("status--err");
}

let toastTimer;
function toast(message, kind = "") {
  const el = $("toast");
  const text = $("toastText");
  if (!el || !text) return;
  text.textContent = message;
  el.classList.toggle("err", kind === "err");
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
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

function openConfirmModal({title, message, eyebrow = "CONFIRM", okText = "确认", danger = false}) {
  $("confirmEyebrow").textContent = eyebrow;
  $("confirmTitle").textContent = title;
  $("confirmMessage").textContent = message;
  $("confirmOkBtn").textContent = okText;
  $("confirmOkBtn").className = danger ? "btn btn-danger" : "btn btn-primary";
  $("confirmModal").classList.add("active");
  return new Promise((resolve) => {
    state.confirmResolve = resolve;
  });
}

function resolveConfirmModal(value) {
  $("confirmModal").classList.remove("active");
  if (state.confirmResolve) state.confirmResolve(value);
  state.confirmResolve = null;
}

function openSwitchProviderModal(name) {
  state.switchingProvider = name;
  $("switchProviderTitle").textContent = `切换到 ${name}`;
  $("backupCurrentProviderCheck").checked = false;
  $("backupProviderName").value = "";
  $("backupProviderNameWrap").style.display = "none";
  setStatus("switchProviderStatus", "");
  $("switchProviderModal").classList.add("active");
}

function closeSwitchProviderModal() {
  $("switchProviderModal").classList.remove("active");
  state.switchingProvider = "";
}

async function loadProfiles() {
  try {
    const data = await api("/api/provider-profiles");
    $("codexDir").textContent = data.codex_dir;
    $("profileCount").textContent = data.profiles.length;
    const list = $("profileList");
    list.innerHTML = "";
    if (!data.profiles.length) {
      list.innerHTML = `
        <div class="empty">
          <div class="empty-icon">{ }</div>
          <p class="empty-text">还没有 provider profile。</p>
          <button data-open-add="1" class="btn btn-accent btn-sm"><span style="font-size:16px; line-height:1;">+</span> 添加第一个 Provider</button>
        </div>`;
      return;
    }
    for (const profile of data.profiles) {
      const initial = (profile.name || "?").trim().charAt(0).toUpperCase() || "?";
      const item = document.createElement("div");
      item.className = "profile-row";
      item.innerHTML = `
        <div class="profile-left">
          <div class="avatar">${escapeHtml(initial)}</div>
          <div class="profile-info">
            <div class="profile-name-row">
              <span class="profile-name">${escapeHtml(profile.name)}</span>
              <span class="badge ${profile.has_config ? "ok" : "miss"}">${profile.has_config ? "config.toml" : "缺 config"}</span>
              <span class="badge ${profile.has_auth ? "ok" : "miss"}">${profile.has_auth ? "auth.json" : "缺 auth"}</span>
            </div>
            <span class="profile-meta">provider profile</span>
          </div>
        </div>
        <div class="profile-actions">
          <button data-edit-profile="${escapeAttr(profile.name)}" class="btn btn-ghost btn-xs">查看/编辑</button>
          <button data-switch="${escapeAttr(profile.name)}" class="btn btn-accent btn-xs">切换</button>
          <button data-delete-profile="${escapeAttr(profile.name)}" class="btn-icon" title="删除">✕</button>
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
    toast(`已保存 “${state.editingProvider}”`);
    await loadProfiles();
  } catch (error) {
    setStatus("editProviderStatus", error.message, "err");
  }
}

async function addProvider() {
  try {
    const name = $("providerName").value;
    await api("/api/provider-profiles", {
      method: "POST",
      body: JSON.stringify({
        name,
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
    toast(`已保存 “${(name || "").trim() || "Provider"}”`);
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
  openSwitchProviderModal(name);
}

async function confirmSwitchProvider() {
  const name = state.switchingProvider;
  if (!name) return;
  const shouldBackup = $("backupCurrentProviderCheck").checked;
  const backupName = $("backupProviderName").value.trim();
  try {
    if (shouldBackup) {
      if (!backupName) {
        setStatus("switchProviderStatus", "请输入备份 Profile 名称。", "err");
        return;
      }
      const current = await api("/api/provider-current");
      await api("/api/provider-profiles", {
        method: "POST",
        body: JSON.stringify({
          name: backupName,
          config_toml: current.config_toml || "",
          auth_json: current.auth_json || "",
        }),
      });
    }
    const data = await api("/api/provider-profiles/switch", {
      method: "POST",
      body: JSON.stringify({name}),
    });
    setStatus(
      "providerStatus",
      shouldBackup ? `已保存当前 provider 为 "${backupName}"，并切换到 "${data.name}"。` : `已切换到 "${data.name}"。`,
      "ok",
    );
    toast(shouldBackup ? `已备份并切换到 “${data.name}”` : `已切换到 “${data.name}”`);
    closeSwitchProviderModal();
    await loadProfiles();
  } catch (error) {
    setStatus("switchProviderStatus", error.message, "err");
  }
}

async function deleteProfile(name) {
  const ok = await openConfirmModal({
    eyebrow: "DELETE PROVIDER",
    title: "删除 Provider Profile",
    message: `确认删除 provider profile "${name}"?`,
    okText: "删除",
    danger: true,
  });
  if (!ok) return;
  try {
    await api("/api/provider-profiles/delete", {
      method: "POST",
      body: JSON.stringify({name}),
    });
    setStatus("providerStatus", "Profile 已删除。", "ok");
    toast("已移除 profile");
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
  if (!state.sessions.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="7" style="padding:0;">
      <div class="empty" style="margin:8px;">
        <div class="empty-icon">~</div>
        <p class="empty-text">还没有 session 记录。</p>
      </div></td>`;
    body.appendChild(tr);
    updateSortMarks();
    return;
  }
  for (const session of state.sessions) {
    const tr = document.createElement("tr");
    tr.className = "sess-row";
    tr.dataset.rowDetail = session.id;
    const archivedLabel = session.archived ? "Yes" : "No";
    const archivedClass = session.archived ? "pill-yes" : "pill-no";
    tr.innerHTML = `
      <td class="col-check"><input class="checkbox" type="checkbox" data-select="${escapeAttr(session.id)}" ${state.selected.has(session.id) ? "checked" : ""}></td>
      <td class="cell-nowrap">${escapeHtml(session.created_label)}</td>
      <td><span class="pill pill-provider">${escapeHtml(session.model_provider)}</span></td>
      <td class="cell-project">${escapeHtml(session.project)}</td>
      <td><span class="pill ${archivedClass}">${archivedLabel}</span></td>
      <td class="cell-title" title="${escapeAttr(session.title)}">${escapeHtml(session.title)}</td>
      <td><button data-detail="${escapeAttr(session.id)}" class="btn btn-ghost btn-xs">详情</button></td>`;
    body.appendChild(tr);
  }
  $("selectAllSessions").checked = state.sessions.length > 0 && state.sessions.every((s) => state.selected.has(s.id));
  updateSortMarks();
}

function updateSortMarks() {
  $("createdSortMark").textContent = state.sort === "created" ? (state.sortDesc ? "↓" : "↑") : "";
  $("providerSortMark").textContent = state.sort === "provider" ? "↑" : "";
  $("projectsSortMark").textContent = state.sort === "projects" ? "↑" : "";
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
    toast(`已更新 ${ids.length} 个 session 的 provider`);
    await loadSessions();
  } catch (error) {
    setStatus("sessionStatus", error.message, "err");
  }
}

async function deleteSelectedSessions() {
  const ids = [...state.selected];
  if (!ids.length) return setStatus("sessionStatus", "请先选择 session。", "err");
  const ok = await openConfirmModal({
    eyebrow: "DELETE SESSIONS",
    title: "删除选中的 Sessions",
    message: `确认删除 ${ids.length} 个 session? 删除前会自动备份。`,
    okText: "删除",
    danger: true,
  });
  if (!ok) return;
  try {
    const data = await api("/api/sessions/delete", {
      method: "POST",
      body: JSON.stringify({ids}),
    });
    state.selected.clear();
    setStatus("sessionStatus", `已删除 ${data.sqlite_rows} 条 sqlite 记录，${data.jsonl_files} 个 jsonl。备份: ${data.backup_dir}`, "ok");
    toast(`已删除 ${data.jsonl_files} 个 session（已备份）`);
    await loadSessions();
  } catch (error) {
    setStatus("sessionStatus", error.message, "err");
  }
}

async function showDetail(id) {
  try {
    const data = await api(`/api/sessions/detail?id=${encodeURIComponent(id)}`);
    $("detailTitle").textContent = data.title || "Session 详情";
    const archivedLabel = data.archived ? "Yes" : "No";
    const rows = [
      ["Title", data.title || "-"],
      ["ID", data.id],
      ["CWD", data.cwd],
      ["Created", data.created_label],
      ["Updated", data.updated_label || "-"],
      ["Provider", data.model_provider],
      ["Model", data.model || "-"],
      ["Project", data.project],
      ["Archived", archivedLabel],
      ["JSONL", data.rollout_path],
    ];
    $("detailMeta").innerHTML = rows
      .map(([label, value]) => `<div class="detail-row"><strong>${label}</strong><span>${escapeHtml(value)}</span></div>`)
      .join("");
    const detailBlocks = [];
    if (data.preview) detailBlocks.push(`Preview:\n${data.preview}`);
    detailBlocks.push(`Conversation:\n${data.conversation.join("\n")}`);
    $("detailConversation").textContent = detailBlocks.join("\n\n");
    $("detailModal").classList.add("active");
  } catch (error) {
    setStatus("sessionStatus", error.message, "err");
  }
}

async function loadEnv() {
  try {
    const data = await api("/api/env");
    $("envText").value = data.text || "";
    setStatus("envStatus", data.exists ? "已读取 ~/.codex/.env。" : "~/.codex/.env 不存在，保存后会创建。");
  } catch (error) {
    setStatus("envStatus", error.message, "err");
  }
}

function parseEnvText(text) {
  const entries = [];
  for (const line of String(text).split(/\r?\n/)) {
    const stripped = line.trim();
    if (!stripped || stripped.startsWith("#")) continue;
    const index = stripped.indexOf("=");
    if (index === -1) {
      entries.push({key: stripped, value: ""});
    } else {
      entries.push({key: stripped.slice(0, index).trim(), value: stripped.slice(index + 1)});
    }
  }
  return entries.filter((entry) => entry.key);
}

async function saveEnv() {
  const entries = parseEnvText($("envText").value);
  try {
    await api("/api/env", {
      method: "POST",
      body: JSON.stringify({entries}),
    });
    setStatus("envStatus", "已保存 ~/.codex/.env。", "ok");
    toast("已保存 ~/.codex/.env");
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
  const row = event.target.closest("[data-row-detail]");
  const openAdd = event.target.closest("[data-open-add]");
  const switchName = event.target.dataset.switch;
  const deleteName = event.target.dataset.deleteProfile;
  const editName = event.target.dataset.editProfile;
  const detailId = event.target.dataset.detail;
  if (openAdd) openAddProviderModal();
  if (switchName) switchProvider(switchName);
  if (deleteName) deleteProfile(deleteName);
  if (editName) editProfile(editName);
  if (detailId) showDetail(detailId);
  if (
    row
    && !detailId
    && !event.target.closest("button, input, textarea, select, a")
  ) {
    showDetail(row.dataset.rowDetail);
  }
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
$("logoutBtn").addEventListener("click", async () => {
  const ok = await openConfirmModal({
    eyebrow: "LOGOUT",
    title: "退出登录？",
    message: "你将退出本地 console，已保存的 provider 不会被删除。",
    okText: "退出登录",
    danger: true,
  });
  if (!ok) return;
  toast("已退出登录");
  await logout();
});
$("openAddProviderBtn").addEventListener("click", openAddProviderModal);
$("closeAddProviderModalBtn").addEventListener("click", closeAddProviderModal);
$("closeAddProviderModalBtn2").addEventListener("click", closeAddProviderModal);
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
$("backupCurrentProviderCheck").addEventListener("change", (event) => {
  $("backupProviderNameWrap").style.display = event.target.checked ? "block" : "none";
  if (event.target.checked) $("backupProviderName").focus();
});
$("cancelSwitchProviderBtn").addEventListener("click", closeSwitchProviderModal);
$("confirmSwitchProviderBtn").addEventListener("click", confirmSwitchProvider);
$("switchProviderModal").addEventListener("click", (event) => {
  if (event.target.id === "switchProviderModal") closeSwitchProviderModal();
});
$("confirmCancelBtn").addEventListener("click", () => resolveConfirmModal(false));
$("confirmOkBtn").addEventListener("click", () => resolveConfirmModal(true));
$("confirmModal").addEventListener("click", (event) => {
  if (event.target.id === "confirmModal") resolveConfirmModal(false);
});
$("saveEnvBtn").addEventListener("click", saveEnv);

loadProfiles();
loadSessions();
loadEnv();
