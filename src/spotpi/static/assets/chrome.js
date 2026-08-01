/**
 * chrome.js — SpotPi new dashboard chrome
 *
 * Runs AFTER app.js. Wires up the new dashboard-specific UI elements:
 *   - Power toggle (calls /api/service/spotify/{enable-now|disable-now})
 *   - Output picker sheet (calls /api/audio/devices)
 *   - Dashboard ↔ Advanced view switching
 *   - Theme toggle (persists to localStorage)
 *   - Volume slider (live visual + auto-apply on release)
 *   - Idle help text (shows when device is online but nothing playing)
 *   - Sidebar stats (IP, temp, uptime from /api/system)
 *   - Quick action buttons wired to Advanced panel nav
 *
 * No modifications to app.js required.
 */

(function () {
  "use strict";

  /* ── tiny API helper (mirrors app.js api(), but self-contained) ── */
  async function apiFetch(path, options = {}, attempt = 0) {
    const pin = localStorage.getItem("spotpiPin");
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (pin) headers["X-SpotPi-Pin"] = pin;
    const res = await fetch(path, { ...options, headers });
    const data = await res.json();
    if (!res.ok) {
      if (res.status === 401 && attempt < 3) {
        const entered = window.prompt("PIN");
        if (entered) { localStorage.setItem("spotpiPin", entered); return apiFetch(path, options, attempt + 1); }
      }
      throw new Error(data.error || res.statusText);
    }
    return data;
  }

  function toast(msg, isError) {
    const el = document.querySelector("#notice");
    if (!el) return;
    el.textContent = msg;
    el.className = "notice" + (isError ? " error" : "");
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 4500);
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* ── view switching ──────────────────────────────────────────── */
  const dashView = document.querySelector("#dashboard-view");
  const advView  = document.querySelector("#advanced-view");

  function showView(name) {
    // Let app.js body[data-view] drive tab highlighting (it already does)
    if (dashView) dashView.hidden = name !== "dashboard";
    if (advView)  advView.hidden  = name !== "advanced";
  }

  // Override btn clicks AFTER app.js has attached its own listeners
  // (we add ours too — they both fire, harmless)
  document.querySelector("#btn-dashboard")?.addEventListener("click", () => showView("dashboard"));
  document.querySelector("#btn-advanced")?.addEventListener("click",  () => showView("advanced"));
  document.querySelector("#goto-advanced")?.addEventListener("click", () => {
    document.querySelector("#btn-advanced")?.click();
  });

  // Init correct view
  showView(document.body.dataset.view || "dashboard");

  /* ── quick action: doctor → go to advanced, select Doctor ── */
  document.querySelector("#dash-run-doctor")?.addEventListener("click", () => {
    document.querySelector("#btn-advanced")?.click();
    document.querySelector("#refresh-doctor")?.click();
  });
  /* ── quick action: logs ── */
  document.querySelector("#dash-view-logs")?.addEventListener("click", () => {
    document.querySelector("#btn-advanced")?.click();
    setTimeout(() => document.querySelector("#refresh-logs")?.click(), 300);
  });
  /* ── quick action: setup wizard ── */
  document.querySelector("#enter-setup-dash")?.addEventListener("click", () => {
    document.querySelector("#enter-setup")?.click();
  });

  /* ── theme toggle ────────────────────────────────────────────── */
  const themeBtn = document.querySelector("#theme-toggle");
  function getTheme() {
    return document.documentElement.dataset.theme ||
      (window.matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light");
  }
  function applyTheme(t) {
    document.documentElement.dataset.theme = t;
    if (themeBtn) themeBtn.textContent = t === "dark" ? "☀️" : "🌙";
    localStorage.setItem("spotpiTheme", t);
  }
  // Restore saved theme (app.js may later sync from config — that's fine)
  const savedTheme = localStorage.getItem("spotpiTheme");
  if (savedTheme) applyTheme(savedTheme);
  themeBtn?.addEventListener("click", () => applyTheme(getTheme() === "dark" ? "light" : "dark"));

  /* ── power toggle ────────────────────────────────────────────── */
  const powerBtn  = document.querySelector("#power-toggle");
  const powerLabel = document.querySelector("#power-label");
  const heroDot   = document.querySelector("#hero-dot");
  const heroPill  = document.querySelector("#hero-pill");

  function syncPowerUI(isOn) {
    if (!powerBtn) return;
    powerBtn.dataset.on = isOn ? "true" : "false";
    powerBtn.setAttribute("aria-checked", String(isOn));
    if (powerLabel) powerLabel.textContent = isOn ? "On" : "Off";
    if (heroPill)   heroPill.dataset.state = isOn ? "on" : "off";
    updateIdleHelp();
  }

  // Watch #hero-dot class changes (app.js sets hero-dot--on/off after API calls)
  if (heroDot) {
    new MutationObserver(() => {
      syncPowerUI(heroDot.classList.contains("hero-dot--on"));
    }).observe(heroDot, { attributes: true, attributeFilter: ["class"] });
  }

  powerBtn?.addEventListener("click", async () => {
    const isOn = powerBtn.dataset.on === "true";
    const action = isOn ? "disable-now" : "enable-now";
    powerBtn.disabled = true;
    try {
      await apiFetch(`/api/service/spotify/${action}`, { method: "POST", body: "{}" });
      toast(isOn ? "Spotify Connect stopped" : "Spotify Connect started");
      document.querySelector("#refresh-status")?.click();
    } catch (e) {
      toast(e.message, true);
    } finally {
      powerBtn.disabled = false;
    }
  });

  /* ── idle help ───────────────────────────────────────────────── */
  const idleHelp     = document.querySelector("#idle-help");
  const idleHelpName = document.querySelector("#idle-help-name");
  const nowCard      = document.querySelector("#nowplaying-card");
  const heroNameEl   = document.querySelector("#hero-name");

  function updateIdleHelp() {
    if (!idleHelp || !nowCard) return;
    const state = nowCard.dataset.state || "";
    const playing = ["playing", "changed", "started"].includes(state);
    const isOn = heroDot?.classList.contains("hero-dot--on");
    idleHelp.hidden = playing || !isOn;
  }

  if (nowCard) {
    new MutationObserver(updateIdleHelp)
      .observe(nowCard, { attributes: true, attributeFilter: ["data-state"] });
  }
  if (heroNameEl && idleHelpName) {
    new MutationObserver(() => { idleHelpName.textContent = heroNameEl.textContent; })
      .observe(heroNameEl, { childList: true, characterData: true, subtree: true });
  }

  /* ── volume slider ───────────────────────────────────────────── */
  const dashVol      = document.querySelector("#dash-volume");
  const dashVolLabel = document.querySelector("#dash-volume-label");
  const dashSetVol   = document.querySelector("#dash-set-volume");

  if (dashVol) {
    // Visual feedback while dragging
    dashVol.addEventListener("input", () => {
      if (dashVolLabel) dashVolLabel.textContent = dashVol.value + "%";
      dashVol.style.setProperty("--fill", dashVol.value + "%");
    });
    // Apply on release (calls hidden #dash-set-volume which app.js wires to API)
    dashVol.addEventListener("change", () => dashSetVol?.click());
  }

  /* ── mini player (mobile, fixed above the bottom nav) ─────────── */
  // Mirrors the full now-playing card so controls stay thumb-reachable
  // while scrolling the dashboard or the Advanced settings. Buttons just
  // re-dispatch clicks to the real player controls (wired by features.js).
  const miniPlayer     = document.querySelector("#mini-player");
  const miniArt        = document.querySelector("#mini-art");
  const miniTitle      = document.querySelector("#mini-title");
  const miniArtist     = document.querySelector("#mini-artist");
  const miniPlayPause  = document.querySelector("#mini-play-pause");
  const miniIconPlay   = document.querySelector("#mini-icon-play");
  const miniIconPause  = document.querySelector("#mini-icon-pause");
  const miniNext       = document.querySelector("#mini-next");

  function syncMiniPlayer() {
    if (!miniPlayer) return;
    const card   = document.querySelector("#nowplaying-card");
    const title  = document.querySelector("#nowplaying-title");
    const artist = document.querySelector("#nowplaying-artist");
    const art    = document.querySelector("#nowplaying-art");
    const play   = document.querySelector("#play-pause");
    const next   = document.querySelector("#skip-next");

    const state = (card && card.dataset.state) || "";
    const active = ["playing", "changed", "started", "paused"].includes(state);
    miniPlayer.hidden = !active;
    if (!active) return;

    if (miniTitle && title)  miniTitle.textContent = title.textContent;
    if (miniArtist && artist) miniArtist.textContent = artist.textContent;
    if (miniArt && art) {
      const bg = art.style.backgroundImage;
      if (bg) miniArt.style.backgroundImage = bg;
      else miniArt.style.backgroundImage = "";
    }
    if (miniPlayPause && play) {
      miniPlayPause.disabled = play.disabled;
      const isPlaying = document.querySelector("#icon-play")?.hidden === true;
      if (miniIconPlay)  miniIconPlay.hidden = isPlaying;
      if (miniIconPause) miniIconPause.hidden = !isPlaying;
    }
    if (miniNext && next) miniNext.disabled = next.disabled;
  }

  miniPlayPause?.addEventListener("click", () => document.querySelector("#play-pause")?.click());
  miniNext?.addEventListener("click", () => document.querySelector("#skip-next")?.click());
  syncMiniPlayer();
  setInterval(syncMiniPlayer, 1000);

  /* ── output picker ───────────────────────────────────────────── */
  const outputPickerBtn   = document.querySelector("#output-picker");
  const outputSheet       = document.querySelector("#output-sheet");
  const outputSheetClose  = document.querySelector("#output-sheet-close");
  const outputSheetList   = document.querySelector("#output-sheet-list");
  const outputNameEl      = document.querySelector("#output-name");

  let currentOutputId = null;

  function closeOutputSheet() { if (outputSheet) outputSheet.hidden = true; }

  function renderOutputSheetItems(payload) {
    if (!outputSheetList) return;
    const hw = payload.hardware || [];
    const logical = (payload.logical || []).map(name => ({
      id: name, card_name: name, device_name: "Logical", isLogical: true,
    }));
    const devices = [...hw, ...logical];

    if (!devices.length) {
      outputSheetList.innerHTML = "<p style='padding:16px;color:var(--text-3)'>No ALSA devices found.</p>";
      return;
    }

    outputSheetList.innerHTML = "";
    devices.forEach(dev => {
      const isActive = currentOutputId === dev.id;
      const isUSB = /usb/i.test(dev.card_name || "");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sheet-item" + (isActive ? " is-active" : "");
      btn.innerHTML = `
        <span class="sheet-item-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
            <rect x="6" y="3" width="12" height="18" rx="2"/><circle cx="12" cy="14" r="3"/>
          </svg>
        </span>
        <span class="sheet-item-meta">
          <span class="sheet-item-name">${esc(dev.card_name || dev.id)}</span>
          <span class="sheet-item-sub">${esc(dev.id)}${isUSB ? " · Recommended" : ""}</span>
        </span>
        ${isActive ? '<span class="sheet-item-check" aria-label="Selected">✓</span>' : ""}
      `;
      btn.addEventListener("click", () => {
        currentOutputId = dev.id;
        if (outputNameEl) outputNameEl.textContent = dev.card_name || dev.id;
        closeOutputSheet();
        // Trigger the existing audio-panel "Use" logic via a custom event
        // (app.js sets config.audio.device when the "Use" button in the audio panel is clicked)
        // Here we just update the display — the user can confirm in Advanced > Audio if needed
        toast(`Output display updated. Go to Advanced → Audio to apply & save.`);
      });
      outputSheetList.appendChild(btn);
    });
  }

  outputPickerBtn?.addEventListener("click", async () => {
    if (!outputSheet) return;
    outputSheet.hidden = false;
    if (outputSheetList) {
      outputSheetList.innerHTML = "<p style='padding:16px;color:var(--text-3)'>Loading…</p>";
    }
    try {
      const payload = await apiFetch("/api/audio/devices");
      renderOutputSheetItems(payload);
    } catch (e) {
      if (outputSheetList) outputSheetList.innerHTML = `<p style='padding:16px;color:var(--danger)'>${esc(e.message)}</p>`;
    }
  });

  outputSheetClose?.addEventListener("click", closeOutputSheet);
  outputSheet?.addEventListener("click", e => { if (e.target === outputSheet) closeOutputSheet(); });

  /* ── sidebar stats ───────────────────────────────────────────── */
  async function refreshSidebarStats() {
    try {
      const system = await apiFetch("/api/system");
      const set = (id, val) => {
        const el = document.querySelector(id);
        if (el) el.textContent = val;
      };
      const ips = (system.ip_addresses || []).filter(ip => !ip.includes(":"));
      set("#stat-ip", ips[0] || system.hostname || "—");
      const tempC = system.cpu_temperature_c;
      const tempEl = document.querySelector("#stat-temp");
      if (tempEl) {
        tempEl.textContent = tempC !== null && tempC !== undefined ? `${tempC}°C` : "—";
        tempEl.className = "stat-val" + (tempC > 70 ? " danger" : tempC > 58 ? " warn" : tempC > 0 ? " ok" : "");
      }
      const cpu = system.cpu_percent;
      const cpuEl = document.querySelector("#stat-cpu");
      if (cpuEl) {
        cpuEl.textContent = cpu !== null && cpu !== undefined ? `${cpu}%` : "—";
        cpuEl.className = "stat-val" + (cpu > 90 ? " danger" : cpu > 70 ? " warn" : cpu >= 0 ? " ok" : "");
      }
      const mem = system.memory || {};
      const ramEl = document.querySelector("#stat-ram");
      if (ramEl) {
        if (mem.used_percent !== undefined && mem.MemTotal) {
          const usedMb = Math.round((mem.MemTotal - (mem.MemAvailable || 0)) / 1024);
          ramEl.textContent = `${usedMb} MB · ${mem.used_percent}%`;
          ramEl.className = "stat-val" + (mem.used_percent > 90 ? " danger" : mem.used_percent > 75 ? " warn" : " ok");
        } else {
          ramEl.textContent = "—";
        }
      }
      const secs = parseFloat((system.uptime || "0").split(" ")[0]);
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      set("#stat-uptime", h > 0 ? `${h}h ${m}m` : `${m}m`);
    } catch (_) {
      // Non-critical; app.js handles the main status refresh
    }
  }

  /* ── init ────────────────────────────────────────────────────── */
  // Wait for app.js to finish its init() before syncing sidebar stats
  // app.js doesn't expose an init promise, so we poll the DOM for #hero-name
  // to be populated (set by renderStatusHero).
  let attempts = 0;
  const waitForInit = setInterval(() => {
    const heroLabel = document.querySelector("#hero-label");
    const name = document.querySelector("#hero-name");
    if ((heroLabel && heroLabel.textContent !== "Loading…") || ++attempts > 20) {
      clearInterval(waitForInit);
      refreshSidebarStats();
      if (idleHelpName && name) idleHelpName.textContent = name.textContent;
    }
  }, 300);

  // Sidebar stats auto-refresh every 30 s
  setInterval(refreshSidebarStats, 30_000);

})();

/* ── Spotify skip + queue (server-side PKCE — works on HTTP) ─────── */
(function () {
  "use strict";

  /* All Spotify API calls go through the Pi server so crypto.subtle
     (HTTPS-only) is never needed in the browser. */

  async function spApi(path, method = "GET") {
    const r = await fetch("/api/spotify" + path, { method, headers: { "Content-Type": "application/json" } });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.error || r.statusText);
    }
    return r.json().catch(() => ({}));
  }

  function setConnected(yes) {
    const hint = document.querySelector("#spotify-connect-hint");
    if (hint) hint.hidden = yes;
    const prev = document.querySelector("#skip-prev");
    const next = document.querySelector("#skip-next");
    if (yes) {
      prev?.removeAttribute("disabled");
      next?.removeAttribute("disabled");
    } else {
      prev?.setAttribute("disabled", "");
      next?.setAttribute("disabled", "");
    }
  }

  /* queue */
  const queueSheet = document.querySelector("#queue-sheet");
  const queueList  = document.querySelector("#queue-sheet-list");
  function msToTime(ms) { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

  async function openQueue() {
    if (!queueSheet) return;
    queueSheet.hidden = false;
    if (queueList) queueList.innerHTML = `<div style="padding:16px;color:var(--text-3)">Loading…</div>`;
    try {
      const data = await spApi("/queue");
      if (!queueList) return;
      if (!data.queue?.length) {
        queueList.innerHTML = `<div style="padding:16px;color:var(--text-3)">Queue is empty</div>`;
        return;
      }
      queueList.innerHTML = "";
      data.queue.slice(0, 30).forEach((track, i) => {
        const artists = (track.artists || []).map(a => a.name).join(", ");
        const art = track.album?.images?.[2]?.url || track.album?.images?.[0]?.url || "";
        const item = document.createElement("div");
        item.className = "queue-item";
        item.innerHTML = `
          <span class="queue-num">${i + 1}</span>
          ${art ? `<img class="queue-art" src="${esc(art)}" alt="" loading="lazy">` : `<div class="queue-art queue-art--empty"></div>`}
          <span class="queue-meta">
            <span class="queue-name">${esc(track.name)}</span>
            <span class="queue-artist">${esc(artists)}</span>
          </span>
          <span class="queue-dur">${msToTime(track.duration_ms)}</span>`;
        queueList.appendChild(item);
      });
    } catch (e) {
      if (queueList) queueList.innerHTML = `<div style="padding:16px;color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  document.querySelector("#show-queue")?.addEventListener("click", openQueue);
  document.querySelector("#queue-sheet-close")?.addEventListener("click", () => { if (queueSheet) queueSheet.hidden = true; });
  queueSheet?.addEventListener("click", e => { if (e.target === queueSheet) queueSheet.hidden = true; });

  document.querySelector("#skip-prev")?.addEventListener("click", async () => {
    try { await spApi("/previous", "POST"); setTimeout(() => document.querySelector("#refresh-status")?.click(), 800); }
    catch (e) { spToast(e.message, true); }
  });
  document.querySelector("#skip-next")?.addEventListener("click", async () => {
    try { await spApi("/next", "POST"); setTimeout(() => document.querySelector("#refresh-status")?.click(), 800); }
    catch (e) { spToast(e.message, true); }
  });

  // Note: the Connect button click is handled by app.js (startSpotifyConnect);
  // binding it here too would fire two auth-url requests whose PKCE states
  // overwrite each other.

  /* handle OAuth callback: Spotify redirects back with ?code=... */
  async function init() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    if (code) {
      history.replaceState({}, "", window.location.pathname);
      try {
        await fetch("/api/spotify/callback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code }),
        });
        spToast("Spotify connected! Skip and queue are now enabled.");
        setConnected(true);
        return;
      } catch (_) {
        spToast("Spotify connection failed — try again", true);
      }
    }
    // Check existing connection
    try {
      const d = await spApi("/status");
      setConnected(d.connected === true);
    } catch (_) {
      setConnected(false);
    }
  }
  init();

  function spToast(msg, isErr) {
    const el = document.querySelector("#notice");
    if (!el) return;
    el.textContent = msg;
    el.className = "notice" + (isErr ? " error" : "");
    el.hidden = false;
    clearTimeout(spToast._t);
    spToast._t = setTimeout(() => { el.hidden = true; }, 5000);
  }
})();
