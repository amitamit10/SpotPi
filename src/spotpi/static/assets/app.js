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
        localStorage.setItem("spotpiPin", pin);
        return api(path, options);
      }
    }
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function authHeaders() {
  const pin = localStorage.getItem("spotpiPin");
  return pin ? { "X-SpotPi-Pin": pin } : {};
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
    localStorage.setItem("spotpiPin", state.config.web.auth_pin);
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

function formatUptime(uptimeStr) {
  const secs = parseFloat((uptimeStr || "0").split(" ")[0]);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function renderStatusHero(status) {
  const hero = document.querySelector("#status-hero");
  if (!hero) return;
  const isOk = status.spotify.active_ok;
  hero.innerHTML = `
    <div class="hero-state">
      <div class="hero-dot ${isOk ? "hero-dot--on" : "hero-dot--off"}"></div>
      <span>${isOk ? "Spotify Connect Active" : "Spotify Connect Inactive"}</span>
    </div>
    <div class="hero-name">${escapeHtml(status.device_name)}</div>
    <div class="hero-hint">${isOk
      ? "Open Spotify → tap the speaker icon → select this device to play"
      : "Service is not running — tap Start or Enable below"}</div>
  `;
}

async function refreshStatus() {
  const [status, system] = await Promise.all([api("/api/status"), api("/api/system")]);

  renderStatusHero(status);

  const items = [
    ["Spotify", status.spotify.active, status.spotify.active_ok ? "ok" : "warn"],
    ["Autostart", status.spotify.enabled, status.spotify.enabled_ok ? "ok" : "warn"],
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

  els.systemGrid.innerHTML = "";
  const systemItems = [
    ["Hostname", system.hostname || "unknown"],
    ["IP", (system.ip_addresses || []).filter(ip => !ip.includes(":")).join(", ") || "unknown"],
    ["CPU temp", system.cpu_temperature_c === null ? "—" : `${system.cpu_temperature_c} °C`],
    ["Uptime", formatUptime(system.uptime)],
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

async function refreshMixer() {
  const payload = await api("/api/audio/mixer");
  const volume = payload.volume_percent;
  els.mixerVolume.value = volume === null ? state.config.volume.startup_volume_percent : volume;
  els.mixerState.textContent = `${payload.device} / ${payload.control} / ${volume === null ? "unknown" : `${volume}%`}`;
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
    Promise.allSettled([refreshStatus(), refreshMixer()]);
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

// ── Setup Wizard ─────────────────────────────────────────

const wizard = {
  step: 0,
  totalSteps: 4,
  data: { deviceName: "", audioDevice: null, bitrate: 320, normalisation: true },
  devices: [],
};

function openSetupWizard() {
  if (!state.config) return;
  wizard.data.deviceName = state.config.device.name;
  wizard.data.bitrate = state.config.quality.bitrate_kbps;
  wizard.data.normalisation = state.config.volume.normalisation_enabled;
  wizard.data.audioDevice = state.config.audio.device_selection === "manual" ? state.config.audio.device : null;
  wizard.step = 0;
  wizard.devices = [];
  document.querySelector("#setup-wizard").hidden = false;
  document.body.style.overflow = "hidden";
  renderWizardStep();
  api("/api/audio/devices").then(payload => {
    wizard.devices = payload.hardware || [];
    if (wizard.step === 1) renderWizardStep();
  }).catch(() => {});
}

function closeSetupWizard() {
  document.querySelector("#setup-wizard").hidden = true;
  document.body.style.overflow = "";
}

function renderWizardStep() {
  const progress = document.querySelector("#wizard-progress");
  const content = document.querySelector("#wizard-content");
  const prevBtn = document.querySelector("#wizard-prev");
  const nextBtn = document.querySelector("#wizard-next");

  progress.innerHTML = "";
  for (let i = 0; i < wizard.totalSteps; i++) {
    const dot = document.createElement("div");
    dot.className = `wizard-dot${i === wizard.step ? " active" : i < wizard.step ? " done" : ""}`;
    progress.append(dot);
  }

  prevBtn.hidden = wizard.step === 0;
  nextBtn.textContent = wizard.step === wizard.totalSteps - 1 ? "Save & Restart" : "Next →";
  content.innerHTML = "";
  [wizardStep0, wizardStep1, wizardStep2, wizardStep3][wizard.step](content);
}

function wizardStep0(el) {
  el.innerHTML = `
    <div class="wizard-step-icon">🎵</div>
    <h2 class="wizard-step-title">Device Name</h2>
    <p class="wizard-step-desc">What should your speaker be called in the Spotify app?</p>
    <div class="wizard-field">
      <label for="wiz-name">Speaker name</label>
      <input id="wiz-name" type="text" value="${escapeHtml(wizard.data.deviceName)}" placeholder="SpotPi" autocomplete="off">
    </div>
    <div class="wizard-tip">
      <strong>Tip:</strong> This is the name that appears in Spotify when choosing where to play.
      Keep it short and recognisable.
    </div>
  `;
  el.querySelector("#wiz-name").addEventListener("input", e => { wizard.data.deviceName = e.target.value; });
}

function wizardStep1(el) {
  const header = document.createElement("div");
  header.innerHTML = `
    <div class="wizard-step-icon">🔊</div>
    <h2 class="wizard-step-title">Audio Output</h2>
    <p class="wizard-step-desc">Which device should Spotify play audio through?</p>
  `;
  el.append(header);

  const list = document.createElement("div");
  list.className = "wizard-device-list";

  if (!wizard.devices.length) {
    list.innerHTML = `<div class="muted" style="padding:12px">Loading devices…</div>`;
  } else {
    for (const device of wizard.devices) {
      const isUSB = /usb/i.test(device.card_name) || device.id === "hw:1,0";
      const isSelected = wizard.data.audioDevice === device.id;
      const item = document.createElement("button");
      item.type = "button";
      item.className = `wizard-device-item${isSelected ? " selected" : ""}`;
      item.innerHTML = `
        <div class="device-check"></div>
        <div>
          <div class="wizard-device-name">${escapeHtml(device.card_name)} / ${escapeHtml(device.device_name)}</div>
          <div class="wizard-device-id">${escapeHtml(device.id)}</div>
        </div>
        ${isUSB ? '<span class="wizard-recommended">Recommended</span>' : ""}
      `;
      item.addEventListener("click", () => {
        wizard.data.audioDevice = device.id;
        list.querySelectorAll(".wizard-device-item").forEach(b => b.classList.remove("selected"));
        item.classList.add("selected");
      });
      list.append(item);
    }
  }
  el.append(list);

  const tip = document.createElement("div");
  tip.className = "wizard-tip";
  tip.innerHTML = "<strong>Tip:</strong> For a USB DAC or USB audio interface, select the <code>hw:X,Y</code> device. Use <em>Test Sound</em> in the Audio tab to verify your selection.";
  el.append(tip);
}

function wizardStep2(el) {
  const bitrateOptions = [
    { value: 96,  label: "96 kbps",  desc: "Low bandwidth" },
    { value: 160, label: "160 kbps", desc: "Standard" },
    { value: 320, label: "320 kbps", desc: "Best quality" },
  ];

  const header = document.createElement("div");
  header.innerHTML = `
    <div class="wizard-step-icon">🎚️</div>
    <h2 class="wizard-step-title">Audio Quality</h2>
    <p class="wizard-step-desc">Choose streaming bitrate and volume behaviour.</p>
    <div class="wizard-field"><label>Bitrate</label></div>
  `;
  el.append(header);

  const grid = document.createElement("div");
  grid.className = "wizard-quality-grid";
  for (const opt of bitrateOptions) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `quality-option${wizard.data.bitrate === opt.value ? " selected" : ""}`;
    btn.innerHTML = `<span class="quality-label">${opt.label}</span><span class="quality-desc">${opt.desc}</span>`;
    btn.addEventListener("click", () => {
      wizard.data.bitrate = opt.value;
      grid.querySelectorAll(".quality-option").forEach(b => b.classList.remove("selected"));
      btn.classList.add("selected");
    });
    grid.append(btn);
  }
  el.append(grid);

  const normRow = document.createElement("label");
  normRow.className = "wizard-toggle-row";
  normRow.style.cursor = "pointer";
  normRow.innerHTML = `
    <input type="checkbox" ${wizard.data.normalisation ? "checked" : ""}>
    <div class="wizard-toggle-label">
      Volume normalisation
      <small>Keeps all tracks at consistent volume — recommended</small>
    </div>
  `;
  normRow.querySelector("input").addEventListener("change", e => { wizard.data.normalisation = e.target.checked; });
  el.append(normRow);

  const tip = document.createElement("div");
  tip.className = "wizard-tip";
  tip.innerHTML = "<strong>Recommended:</strong> 320 kbps for best audio quality. Enable normalisation to avoid sudden volume jumps between songs.";
  el.append(tip);
}

function wizardStep3(el) {
  const deviceLabel = wizard.data.audioDevice
    ? (wizard.devices.find(d => d.id === wizard.data.audioDevice)?.card_name || wizard.data.audioDevice)
    : "Auto (default)";

  el.innerHTML = `
    <div class="wizard-step-icon">✅</div>
    <h2 class="wizard-step-title">All Set!</h2>
    <p class="wizard-step-desc">Review your settings and tap Save & Restart to apply.</p>
    <div class="wizard-summary">
      <div class="wizard-summary-row">
        <span class="wizard-summary-label">Device Name</span>
        <span class="wizard-summary-value">${escapeHtml(wizard.data.deviceName || "SpotPi")}</span>
      </div>
      <div class="wizard-summary-row">
        <span class="wizard-summary-label">Audio Output</span>
        <span class="wizard-summary-value">${escapeHtml(deviceLabel)}</span>
      </div>
      <div class="wizard-summary-row">
        <span class="wizard-summary-label">Bitrate</span>
        <span class="wizard-summary-value">${wizard.data.bitrate} kbps</span>
      </div>
      <div class="wizard-summary-row">
        <span class="wizard-summary-label">Normalisation</span>
        <span class="wizard-summary-value">${wizard.data.normalisation ? "Enabled" : "Disabled"}</span>
      </div>
    </div>
    <div class="wizard-tip" style="margin-top:16px">
      <strong>After saving:</strong> Open Spotify, tap the speaker icon, and select
      <strong>${escapeHtml(wizard.data.deviceName || "SpotPi")}</strong> to start playing.
    </div>
  `;
}

async function wizardFinish() {
  state.config.device.name = wizard.data.deviceName || state.config.device.name;
  state.config.quality.bitrate_kbps = wizard.data.bitrate;
  state.config.volume.normalisation_enabled = wizard.data.normalisation;
  if (wizard.data.audioDevice) {
    state.config.audio.device_selection = "manual";
    state.config.audio.device = wizard.data.audioDevice;
    state.config.audio.alsa_mixer_device = wizard.data.audioDevice.startsWith("hw:")
      ? wizard.data.audioDevice.replace(/,\d+$/, "")
      : wizard.data.audioDevice;
  }
  const nextBtn = document.querySelector("#wizard-next");
  setBusy(nextBtn, true);
  try {
    await saveSettings({ restart: true });
    closeSetupWizard();
    showNotice("Setup complete — Spotify Connect restarted");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setBusy(nextBtn, false);
  }
}

document.querySelector("#enter-setup").addEventListener("click", openSetupWizard);
document.querySelector("#wizard-close").addEventListener("click", closeSetupWizard);
document.querySelector("#setup-wizard").addEventListener("click", e => {
  if (e.target === e.currentTarget) closeSetupWizard();
});
document.querySelector("#wizard-prev").addEventListener("click", () => {
  if (wizard.step > 0) { wizard.step--; renderWizardStep(); }
});
document.querySelector("#wizard-next").addEventListener("click", async () => {
  if (wizard.step < wizard.totalSteps - 1) { wizard.step++; renderWizardStep(); }
  else await wizardFinish();
});

// ─────────────────────────────────────────────────────────

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

for (const button of document.querySelectorAll("[data-service-action]")) {
  button.addEventListener("click", () => serviceAction(button.dataset.serviceTarget, button.dataset.serviceAction).catch((error) => showNotice(error.message, true)));
}

init().catch((error) => showNotice(error.message, true));
