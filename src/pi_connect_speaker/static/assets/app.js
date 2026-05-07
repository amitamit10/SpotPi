const state = {
  schema: null,
  config: null,
  activeSection: "device",
};

const els = {
  subtitle: document.querySelector("#device-subtitle"),
  tabs: document.querySelector("#tabs"),
  form: document.querySelector("#settings-form"),
  sectionTitle: document.querySelector("#section-title"),
  notice: document.querySelector("#notice"),
  statusGrid: document.querySelector("#status-grid"),
  systemGrid: document.querySelector("#system-grid"),
  doctorSummary: document.querySelector("#doctor-summary"),
  doctorList: document.querySelector("#doctor-list"),
  audioDevices: document.querySelector("#audio-devices"),
  mixerState: document.querySelector("#mixer-state"),
  mixerVolume: document.querySelector("#mixer-volume"),
  logs: document.querySelector("#logs"),
  logTarget: document.querySelector("#log-target"),
  commandPreview: document.querySelector("#command-preview"),
  profileList: document.querySelector("#profile-list"),
  profileName: document.querySelector("#profile-name"),
  backupList: document.querySelector("#backup-list"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      const pin = window.prompt("PIN");
      if (pin) {
        localStorage.setItem("piConnectPin", pin);
        return api(path, options);
      }
    }
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function authHeaders() {
  const pin = localStorage.getItem("piConnectPin");
  return pin ? { "X-Pi-Connect-Pin": pin } : {};
}

function showNotice(message, isError = false) {
  els.notice.textContent = message;
  els.notice.className = `notice${isError ? " error" : ""}`;
  els.notice.hidden = false;
  clearTimeout(showNotice.timer);
  showNotice.timer = setTimeout(() => {
    els.notice.hidden = true;
  }, 4500);
}

function setBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
}

async function init() {
  const [schema, settings] = await Promise.all([
    api("/api/schema"),
    api("/api/settings"),
  ]);
  state.schema = schema;
  state.config = settings.config;
  applyTheme();
  renderTabs();
  renderSettings();
  await Promise.allSettled([
    refreshStatus(),
    refreshDoctor(),
    refreshAudio(),
    refreshMixer(),
    refreshNowPlaying(),
    refreshLogs(),
    refreshProfiles(),
    refreshBackups(),
    refreshPreview(),
  ]);
  startAutoRefresh();
}

function renderTabs() {
  els.tabs.innerHTML = "";
  for (const section of state.schema.sections) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tab${section.key === state.activeSection ? " active" : ""}`;
    button.textContent = section.label;
    button.addEventListener("click", () => {
      collectSection();
      state.activeSection = section.key;
      renderTabs();
      renderSettings();
    });
    els.tabs.append(button);
  }
}

function renderSettings() {
  const section = state.activeSection;
  const meta = state.schema.sections.find((item) => item.key === section);
  els.sectionTitle.textContent = meta ? meta.label : "Settings";
  els.subtitle.textContent = state.config.device.name;
  applyTheme();
  applyVisibility();
  els.form.innerHTML = "";
  for (const field of state.schema.fields[section]) {
    els.form.append(renderField(section, field, state.config[section][field.key]));
  }
}

function renderField(section, field, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";
  wrapper.dataset.section = section;
  wrapper.dataset.key = field.key;
  wrapper.dataset.type = field.type;

  const label = document.createElement("label");
  label.textContent = field.label;
  label.htmlFor = `${section}-${field.key}`;
  wrapper.append(label);

  let input;
  if (field.type === "boolean") {
    const toggle = document.createElement("div");
    toggle.className = "toggle";
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(value);
    toggle.append(input);
    wrapper.append(toggle);
  } else if (field.type === "enum") {
    input = document.createElement("select");
    for (const choice of field.choices) {
      const option = document.createElement("option");
      option.value = String(choice);
      option.textContent = String(choice);
      option.selected = choice === value;
      input.append(option);
    }
    wrapper.append(input);
  } else if (field.type === "integer" || field.type === "float") {
    input = document.createElement("input");
    input.type = "number";
    input.value = String(value);
    if (field.min !== undefined) input.min = String(field.min);
    if (field.max !== undefined) input.max = String(field.max);
    if (field.type === "float") input.step = "0.1";
    wrapper.append(input);
  } else if (field.type === "string_list") {
    input = document.createElement("textarea");
    input.value = Array.isArray(value) ? value.join("\n") : "";
    wrapper.append(input);
  } else {
    input = document.createElement("input");
    input.type = field.type === "secret" ? "password" : "text";
    input.value = value || "";
    wrapper.append(input);
  }

  input.id = `${section}-${field.key}`;
  input.dataset.section = section;
  input.dataset.key = field.key;
  input.dataset.type = field.type;
  if (field.type === "enum") {
    input.dataset.choices = JSON.stringify(field.choices);
  }
  input.addEventListener("change", collectSection);
  input.addEventListener("input", collectSection);

  if (field.unit) {
    const unit = document.createElement("span");
    unit.className = "unit";
    unit.textContent = field.unit;
    wrapper.append(unit);
  }
  return wrapper;
}

function collectSection() {
  for (const input of els.form.querySelectorAll("[data-section][data-key]")) {
    const section = input.dataset.section;
    const key = input.dataset.key;
    state.config[section][key] = readInputValue(input);
  }
  els.subtitle.textContent = state.config.device.name;
  applyTheme();
  applyVisibility();
}

function readInputValue(input) {
  const type = input.dataset.type;
  if (type === "boolean") return input.checked;
  if (type === "integer") return Number.parseInt(input.value || "0", 10);
  if (type === "float") return Number.parseFloat(input.value || "0");
  if (type === "string_list") {
    return input.value.split("\n").map((item) => item.trim()).filter(Boolean);
  }
  if (type === "enum") {
    const choices = JSON.parse(input.dataset.choices || "[]");
    const numeric = choices.find((choice) => typeof choice === "number");
    return numeric === undefined ? input.value : Number(input.value);
  }
  return input.value;
}

async function saveSettings({ restart = false } = {}) {
  collectSection();
  const payload = await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify({ config: state.config }),
  });
  state.config = payload.config;
  if (state.config.web.auth_mode === "pin" && state.config.web.auth_pin) {
    localStorage.setItem("piConnectPin", state.config.web.auth_pin);
  }
  renderSettings();
  if (restart) {
    await api("/api/service/spotify/restart", { method: "POST", body: "{}" });
  }
  await Promise.allSettled([refreshStatus(), refreshDoctor(), refreshPreview(), refreshBackups()]);
  showNotice(restart ? "Saved and restarted" : "Saved");
}

function applyTheme() {
  if (!state.config) return;
  const theme = state.config.web.theme;
  if (theme === "system") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.dataset.theme = theme;
  }
}

function applyVisibility() {
  const preview = document.querySelector("#preview-panel");
  if (preview) preview.hidden = !state.config.diagnostics.show_command_preview;
}

async function refreshStatus() {
  const status = await api("/api/status");
  const items = [
    ["Spotify", status.spotify.active, status.spotify.active_ok ? "ok" : "warn"],
    ["Spotify autostart", status.spotify.enabled, status.spotify.enabled_ok ? "ok" : "warn"],
    ["Web UI", status.web.active, status.web.active_ok ? "ok" : "warn"],
    ["Device", status.device_name, "ok"],
  ];
  els.statusGrid.innerHTML = "";
  for (const [label, value, tone] of items) {
    const item = document.createElement("div");
    item.className = "status-item";
    item.innerHTML = `<div class="status-label">${escapeHtml(label)}</div><div class="status-value ${tone}">${escapeHtml(value || "unknown")}</div>`;
    els.statusGrid.append(item);
  }

  const system = await api("/api/system");
  els.systemGrid.innerHTML = "";
  const systemItems = [
    ["Hostname", system.hostname || "unknown"],
    ["IP", (system.ip_addresses || []).join(", ") || "unknown"],
    ["CPU temp", system.cpu_temperature_c === null ? "unknown" : `${system.cpu_temperature_c} C`],
  ];
  for (const [label, value] of systemItems) {
    const item = document.createElement("div");
    item.className = "status-item";
    item.innerHTML = `<div class="status-label">${escapeHtml(label)}</div><div class="status-value">${escapeHtml(value)}</div>`;
    els.systemGrid.append(item);
  }
}

async function refreshDoctor() {
  const report = await api("/api/doctor");
  els.doctorSummary.innerHTML = "";
  const summaryItems = [
    ["OK", report.summary.ok, "ok"],
    ["Warnings", report.summary.warning, "warn"],
    ["Errors", report.summary.error, "danger"],
  ];
  for (const [label, value, tone] of summaryItems) {
    const pill = document.createElement("span");
    pill.className = `pill ${tone}`;
    pill.textContent = `${label}: ${value}`;
    els.doctorSummary.append(pill);
  }

  els.doctorList.innerHTML = "";
  for (const check of report.checks) {
    const row = document.createElement("div");
    row.className = "check-row";
    row.dataset.status = check.status;
    const text = document.createElement("div");
    text.innerHTML = `<strong>${escapeHtml(check.name)}</strong><div class="device-meta">${escapeHtml(check.detail)}</div>${check.fix ? `<div class="device-meta">${escapeHtml(check.fix)}</div>` : ""}`;
    const status = document.createElement("span");
    status.className = `pill ${check.status === "error" ? "danger" : check.status === "warning" ? "warn" : "ok"}`;
    status.textContent = check.status;
    row.append(text, status);
    els.doctorList.append(row);
  }
}

async function refreshAudio() {
  const payload = await api("/api/audio/devices");
  els.audioDevices.innerHTML = "";
  if (!payload.hardware.length && !payload.logical.length) {
    els.audioDevices.textContent = "No ALSA devices returned";
    return;
  }
  for (const device of payload.hardware) {
    els.audioDevices.append(deviceRow(device.id, `${device.card_name} / ${device.device_name}`, device.id));
  }
  for (const name of payload.logical) {
    els.audioDevices.append(deviceRow(name, name, "logical"));
  }
  if (payload.mixer && payload.mixer.controls.length) {
    const meta = document.createElement("div");
    meta.className = "device-row";
    meta.innerHTML = `<div><div class="device-title">Mixer controls</div><div class="device-meta">${escapeHtml(payload.mixer.controls.join(", "))}</div></div>`;
    els.audioDevices.append(meta);
  }
}

function deviceRow(id, title, meta) {
  const row = document.createElement("div");
  row.className = "device-row";
  const info = document.createElement("div");
  info.innerHTML = `<div class="device-title">${escapeHtml(title)}</div><div class="device-meta">${escapeHtml(meta)}</div>`;
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Use";
  button.addEventListener("click", () => {
    state.config.audio.device_selection = "manual";
    state.config.audio.device = id;
    state.config.audio.alsa_mixer_device = id.startsWith("hw:") ? id.replace(/,\d+$/, "") : id;
    if (state.activeSection === "audio") renderSettings();
    showNotice(`Audio device set to ${id}`);
  });
  row.append(info, button);
  return row;
}

async function refreshNowPlaying() {
  const data = await api("/api/nowplaying");
  renderNowPlaying(data);
}

function renderNowPlaying(data) {
  const card = document.querySelector("#nowplaying-card");
  const art = document.querySelector("#nowplaying-art");
  const title = document.querySelector("#nowplaying-title");
  const artist = document.querySelector("#nowplaying-artist");
  const album = document.querySelector("#nowplaying-album");
  const labelText = document.querySelector("#nowplaying-label-text");

  const event = data.event || "unknown";
  card.dataset.state = event;

  if (event === "playing" || event === "changed" || event === "started") {
    title.textContent = data.name || "Unknown track";
    artist.textContent = data.artists || "";
    album.textContent = data.album || "";
    labelText.textContent = "Now Playing";
    if (data.cover_url) {
      art.style.backgroundImage = `url(${JSON.stringify(data.cover_url)})`;
      art.textContent = "";
    } else {
      art.style.backgroundImage = "";
      art.textContent = "♫";
    }
  } else if (event === "paused") {
    labelText.textContent = "Paused";
    title.textContent = data.name || "Unknown track";
    artist.textContent = data.artists || "";
    album.textContent = data.album || "";
    if (data.cover_url) {
      art.style.backgroundImage = `url(${JSON.stringify(data.cover_url)})`;
      art.textContent = "";
    } else {
      art.style.backgroundImage = "";
      art.textContent = "♫";
    }
  } else {
    title.textContent = "Nothing playing";
    artist.textContent = "";
    album.textContent = "";
    art.style.backgroundImage = "";
    art.textContent = "♫";
    labelText.textContent = "Now Playing";
  }
}

async function refreshMixer() {
  const payload = await api("/api/audio/mixer");
  const volume = payload.volume_percent;
  const resolved = volume === null ? state.config.volume.startup_volume_percent : volume;
  els.mixerVolume.value = resolved;
  els.mixerState.textContent = `${payload.device} / ${payload.control} / ${volume === null ? "unknown" : `${volume}%`}`;
  const dashVol = document.querySelector("#dash-volume");
  const dashLabel = document.querySelector("#dash-volume-label");
  if (dashVol) dashVol.value = resolved;
  if (dashLabel) dashLabel.textContent = volume === null ? "—" : `${volume}%`;
}

async function setMixerVolume() {
  const percent = Number.parseInt(els.mixerVolume.value || "0", 10);
  const payload = await api("/api/audio/volume", {
    method: "POST",
    body: JSON.stringify({ percent }),
  });
  await refreshMixer();
  showNotice(payload.ok ? `Volume set to ${percent}%` : payload.stderr || "Volume change failed", !payload.ok);
}

async function refreshLogs() {
  const target = els.logTarget.value || "spotify";
  const payload = await api(`/api/logs?target=${encodeURIComponent(target)}&lines=${state.config.diagnostics.log_lines}`);
  els.logs.textContent = payload.stdout || payload.stderr || "No logs returned";
}

async function refreshPreview() {
  const payload = await api("/api/librespot/preview");
  els.commandPreview.textContent = payload.command || payload.args.join(" ");
}

async function refreshProfiles() {
  const payload = await api("/api/profiles");
  els.profileList.innerHTML = "";
  if (!payload.profiles.length) {
    els.profileList.textContent = "No profiles";
    return;
  }
  for (const profile of payload.profiles) {
    const row = document.createElement("div");
    row.className = "profile-row";
    const name = document.createElement("div");
    name.textContent = profile.name;
    const buttons = document.createElement("div");
    buttons.className = "button-row";
    const load = document.createElement("button");
    load.type = "button";
    load.textContent = "Load";
    load.addEventListener("click", async () => {
      const payload = await api("/api/profiles/load", { method: "POST", body: JSON.stringify({ name: profile.name }) });
      state.config = payload.config;
      renderSettings();
      await Promise.allSettled([refreshStatus(), refreshPreview()]);
      showNotice(`Loaded ${profile.name}`);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Delete";
    remove.addEventListener("click", async () => {
      await api(`/api/profiles/${encodeURIComponent(profile.name)}`, { method: "DELETE" });
      await refreshProfiles();
      showNotice(`Deleted ${profile.name}`);
    });
    buttons.append(load, remove);
    row.append(name, buttons);
    els.profileList.append(row);
  }
}

async function refreshBackups() {
  const payload = await api("/api/backups");
  els.backupList.innerHTML = "";
  if (!payload.backups.length) {
    els.backupList.textContent = "No backups";
    return;
  }
  for (const backup of payload.backups) {
    const row = document.createElement("div");
    row.className = "profile-row";
    const info = document.createElement("div");
    info.innerHTML = `<div class="device-title">${escapeHtml(backup.name)}</div><div class="device-meta">${escapeHtml(backup.modified)} / ${backup.size} bytes</div>`;
    const restore = document.createElement("button");
    restore.type = "button";
    restore.textContent = "Restore";
    restore.addEventListener("click", async () => {
      const payload = await api("/api/backups/restore", { method: "POST", body: JSON.stringify({ name: backup.name }) });
      state.config = payload.config;
      renderSettings();
      await Promise.allSettled([refreshStatus(), refreshDoctor(), refreshPreview()]);
      showNotice(`Restored ${backup.name}`);
    });
    row.append(info, restore);
    els.backupList.append(row);
  }
}

async function saveProfile() {
  collectSection();
  const name = els.profileName.value.trim();
  if (!name) {
    showNotice("Profile name is required", true);
    return;
  }
  await api("/api/profiles/save", {
    method: "POST",
    body: JSON.stringify({ name, config: state.config }),
  });
  els.profileName.value = "";
  await refreshProfiles();
  showNotice(`Saved ${name}`);
}

async function serviceAction(target, action) {
  await api(`/api/service/${target}/${action}`, { method: "POST", body: "{}" });
  await Promise.allSettled([refreshStatus(), refreshDoctor(), refreshLogs()]);
  showNotice(`${action} requested`);
}

async function testSound() {
  const payload = await api("/api/diagnostics/test-sound", { method: "POST", body: "{}" });
  showNotice(payload.ok ? "Test sound started" : payload.stderr || "Test sound failed", !payload.ok);
}

function startAutoRefresh() {
  const seconds = Number(state.config.diagnostics.auto_refresh_seconds || 0);
  if (seconds <= 0) return;
  setInterval(() => {
    Promise.allSettled([refreshStatus(), refreshMixer(), refreshNowPlaying()]);
  }, seconds * 1000);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.querySelector("#save-settings").addEventListener("click", async (event) => {
  setBusy(event.currentTarget, true);
  try {
    await saveSettings();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setBusy(event.currentTarget, false);
  }
});

document.querySelector("#save-restart").addEventListener("click", async (event) => {
  setBusy(event.currentTarget, true);
  try {
    await saveSettings({ restart: true });
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setBusy(event.currentTarget, false);
  }
});

document.querySelector("#refresh-status").addEventListener("click", () => Promise.allSettled([refreshStatus(), refreshDoctor()]).catch((error) => showNotice(error.message, true)));
document.querySelector("#run-doctor").addEventListener("click", () => refreshDoctor().catch((error) => showNotice(error.message, true)));
document.querySelector("#refresh-doctor").addEventListener("click", () => refreshDoctor().catch((error) => showNotice(error.message, true)));
document.querySelector("#refresh-audio").addEventListener("click", () => Promise.allSettled([refreshAudio(), refreshMixer()]).catch((error) => showNotice(error.message, true)));
document.querySelector("#refresh-logs").addEventListener("click", () => refreshLogs().catch((error) => showNotice(error.message, true)));
document.querySelector("#refresh-preview").addEventListener("click", () => refreshPreview().catch((error) => showNotice(error.message, true)));
document.querySelector("#save-profile").addEventListener("click", () => saveProfile().catch((error) => showNotice(error.message, true)));
document.querySelector("#refresh-backups").addEventListener("click", () => refreshBackups().catch((error) => showNotice(error.message, true)));
document.querySelector("#test-sound").addEventListener("click", () => testSound().catch((error) => showNotice(error.message, true)));
document.querySelector("#set-volume").addEventListener("click", () => setMixerVolume().catch((error) => showNotice(error.message, true)));

const dashVolume = document.querySelector("#dash-volume");
const dashVolumeLabel = document.querySelector("#dash-volume-label");
dashVolume.addEventListener("input", () => {
  dashVolumeLabel.textContent = `${dashVolume.value}%`;
});
document.querySelector("#dash-set-volume").addEventListener("click", async () => {
  const percent = Number.parseInt(dashVolume.value || "0", 10);
  try {
    const payload = await api("/api/audio/volume", {
      method: "POST",
      body: JSON.stringify({ percent }),
    });
    await refreshMixer();
    dashVolumeLabel.textContent = `${percent}%`;
    showNotice(payload.ok ? `Volume set to ${percent}%` : payload.stderr || "Volume change failed", !payload.ok);
  } catch (error) {
    showNotice(error.message, true);
  }
});

for (const button of document.querySelectorAll("[data-service-action]")) {
  button.addEventListener("click", () => serviceAction(button.dataset.serviceTarget, button.dataset.serviceAction).catch((error) => showNotice(error.message, true)));
}

init().catch((error) => showNotice(error.message, true));
