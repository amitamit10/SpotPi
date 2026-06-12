/**
 * features.js — dashboard extras layered on top of app.js + chrome.js
 *
 * Runs LAST. Reuses globals declared by app.js (classic-script top-level
 * bindings): api(), state, showNotice(), escapeHtml(), refreshLogs(),
 * renderSettings(), refreshStatus(), refreshBackups(), refreshPreview().
 *
 * Wires up:
 *   - Play/pause, shuffle and repeat buttons + live progress bar
 *     (Spotify Web API via the server-side proxy)
 *   - Recently-played history sheet (/api/history)
 *   - Sleep timer sheet (/api/sleep-timer) with live countdown
 *   - Log line-count selector + log download
 *   - Config export / import buttons in the Backups panel
 *   - Keyboard shortcuts: Space = play/pause, ←/→ = previous/next
 */

(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

  /* Raw fetch helper for the Spotify proxy: a 401 here means "not
     connected", which must NOT trigger app.js's PIN prompt loop. */
  async function spotifyApi(path, options = {}) {
    const pin = localStorage.getItem("spotpiPin");
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (pin) headers["X-SpotPi-Pin"] = pin;
    const res = await fetch("/api/spotify" + path, { ...options, headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || res.statusText);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  /* ────────────────────────────── player controls + progress ── */
  const playPauseBtn = $("#play-pause");
  const iconPlay = $("#icon-play");
  const iconPause = $("#icon-pause");
  const shuffleBtn = $("#shuffle-btn");
  const repeatBtn = $("#repeat-btn");
  const repeatBadge = $("#repeat-badge");
  const progressWrap = $("#progress-wrap");
  const progressFill = $("#progress-fill");
  const progressCurrent = $("#progress-current");
  const progressTotal = $("#progress-total");

  const player = {
    connected: false,
    isPlaying: false,
    shuffle: false,
    repeat: "off",
    progressMs: 0,
    durationMs: 0,
    lastSync: 0, // performance.now() at the last server sync
  };

  function fmtTime(ms) {
    const s = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  function currentProgressMs() {
    if (!player.isPlaying) return player.progressMs;
    return Math.min(player.durationMs, player.progressMs + (performance.now() - player.lastSync));
  }

  function setControlsEnabled(yes) {
    for (const btn of [playPauseBtn, shuffleBtn, repeatBtn]) {
      if (!btn) continue;
      if (yes) btn.removeAttribute("disabled");
      else btn.setAttribute("disabled", "");
    }
  }

  function renderProgress() {
    if (!progressWrap) return;
    const show = player.connected && player.durationMs > 0;
    progressWrap.hidden = !show;
    if (!show) return;
    const cur = currentProgressMs();
    progressFill.style.width = `${Math.min(100, (cur / player.durationMs) * 100)}%`;
    progressCurrent.textContent = fmtTime(cur);
    progressTotal.textContent = fmtTime(player.durationMs);
  }

  function renderPlayer() {
    if (iconPlay) iconPlay.hidden = player.isPlaying;
    if (iconPause) iconPause.hidden = !player.isPlaying;
    shuffleBtn?.classList.toggle("is-on", player.shuffle);
    repeatBtn?.classList.toggle("is-on", player.repeat !== "off");
    if (repeatBadge) repeatBadge.hidden = player.repeat !== "track";
    renderProgress();
  }

  async function pollPlayer() {
    try {
      const data = await spotifyApi("/player");
      player.connected = true;
      if (data.active) {
        player.isPlaying = !!data.is_playing;
        player.shuffle = !!data.shuffle;
        player.repeat = data.repeat || "off";
        player.progressMs = data.progress_ms || 0;
        player.durationMs = data.duration_ms || 0;
        player.lastSync = performance.now();
      } else {
        player.isPlaying = false;
        player.durationMs = 0;
      }
      setControlsEnabled(true);
    } catch (_) {
      player.connected = false;
      player.isPlaying = false;
      player.durationMs = 0;
      setControlsEnabled(false);
    }
    renderPlayer();
  }

  playPauseBtn?.addEventListener("click", async () => {
    const path = player.isPlaying ? "/pause" : "/play";
    // Optimistic flip so the button feels instant
    player.progressMs = currentProgressMs();
    player.isPlaying = !player.isPlaying;
    player.lastSync = performance.now();
    renderPlayer();
    try {
      await spotifyApi(path, { method: "POST", body: "{}" });
    } catch (e) {
      player.isPlaying = !player.isPlaying;
      renderPlayer();
      showNotice(e.message, true);
    }
    setTimeout(pollPlayer, 1200);
  });

  shuffleBtn?.addEventListener("click", async () => {
    try {
      await spotifyApi("/shuffle", { method: "POST", body: JSON.stringify({ state: !player.shuffle }) });
      player.shuffle = !player.shuffle;
      renderPlayer();
      showNotice(player.shuffle ? "Shuffle on" : "Shuffle off");
    } catch (e) {
      showNotice(e.message, true);
    }
  });

  repeatBtn?.addEventListener("click", async () => {
    const next = player.repeat === "off" ? "context" : player.repeat === "context" ? "track" : "off";
    try {
      await spotifyApi("/repeat", { method: "POST", body: JSON.stringify({ state: next }) });
      player.repeat = next;
      renderPlayer();
      showNotice(next === "off" ? "Repeat off" : next === "context" ? "Repeat all" : "Repeat one");
    } catch (e) {
      showNotice(e.message, true);
    }
  });

  setInterval(pollPlayer, 5000);
  setInterval(renderProgress, 1000);
  pollPlayer();

  /* ────────────────────────────── recently played ── */
  const historySheet = $("#history-sheet");
  const historyList = $("#history-sheet-list");

  function relTime(iso) {
    if (!iso) return "";
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (!Number.isFinite(diff) || diff < 0) return "";
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
    return `${Math.floor(diff / 86400)} d ago`;
  }

  async function openHistory() {
    if (!historySheet || !historyList) return;
    historySheet.hidden = false;
    historyList.innerHTML = `<div style="padding:16px;color:var(--text-3)">Loading…</div>`;
    try {
      const data = await api("/api/history");
      const tracks = data.tracks || [];
      if (!tracks.length) {
        historyList.innerHTML = `<div style="padding:16px;color:var(--text-3)">Nothing played yet</div>`;
        return;
      }
      historyList.innerHTML = "";
      for (const track of tracks) {
        const item = document.createElement("div");
        item.className = "queue-item history-item";
        item.innerHTML = `
          ${track.cover_url
            ? `<img class="queue-art" src="${escapeHtml(track.cover_url)}" alt="" loading="lazy">`
            : `<div class="queue-art queue-art--empty"></div>`}
          <span class="queue-meta">
            <span class="queue-name">${escapeHtml(track.name || "Unknown")}</span>
            <span class="queue-artist">${escapeHtml(track.artists || "")}</span>
          </span>
          <span class="queue-dur">${relTime(track.played_at)}</span>`;
        historyList.appendChild(item);
      }
    } catch (e) {
      historyList.innerHTML = `<div style="padding:16px;color:var(--danger)">${escapeHtml(e.message)}</div>`;
    }
  }

  $("#show-history")?.addEventListener("click", openHistory);
  $("#history-sheet-close")?.addEventListener("click", () => { historySheet.hidden = true; });
  historySheet?.addEventListener("click", (e) => { if (e.target === historySheet) historySheet.hidden = true; });
  $("#history-clear")?.addEventListener("click", async () => {
    if (!window.confirm("Clear the playback history?")) return;
    try {
      await api("/api/history", { method: "DELETE" });
      openHistory();
      showNotice("History cleared");
    } catch (e) {
      showNotice(e.message, true);
    }
  });

  /* ────────────────────────────── sleep timer ── */
  const sleepSheet = $("#sleep-sheet");
  const sleepBtn = $("#sleep-btn");
  const sleepBtnLabel = $("#sleep-btn-label");
  let sleepEndsAt = null; // unix epoch seconds, null when inactive

  function fmtRemaining(secs) {
    secs = Math.max(0, Math.round(secs));
    const m = Math.floor(secs / 60);
    if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
    if (m > 0) return `${m}m ${String(secs % 60).padStart(2, "0")}s`;
    return `${secs}s`;
  }

  function updateSleepCountdown() {
    const remaining = sleepEndsAt === null ? null : sleepEndsAt - Date.now() / 1000;
    if (remaining !== null && remaining <= 0) {
      sleepEndsAt = null;
      pollSleep();
    }
    const remainingEl = $("#sleep-remaining");
    if (remainingEl && remaining !== null) remainingEl.textContent = fmtRemaining(remaining);
    if (sleepBtnLabel) sleepBtnLabel.textContent = remaining !== null ? fmtRemaining(remaining) : "Sleep";
    sleepBtn?.classList.toggle("is-on", remaining !== null);
  }

  function renderSleepUI(status) {
    sleepEndsAt = status.active ? status.ends_at : null;
    const activeBox = $("#sleep-active");
    const presetsBox = $("#sleep-presets");
    if (activeBox) activeBox.hidden = !status.active;
    if (presetsBox) presetsBox.hidden = !!status.active;
    const desc = $("#sleep-active-desc");
    if (desc && status.active) {
      desc.textContent = status.action === "stop"
        ? "until Spotify Connect stops"
        : "until playback pauses";
    }
    updateSleepCountdown();
  }

  async function pollSleep() {
    try {
      renderSleepUI(await api("/api/sleep-timer"));
    } catch (_) {
      /* non-critical */
    }
  }

  sleepBtn?.addEventListener("click", () => {
    if (!sleepSheet) return;
    sleepSheet.hidden = false;
    pollSleep();
  });
  $("#sleep-sheet-close")?.addEventListener("click", () => { sleepSheet.hidden = true; });
  sleepSheet?.addEventListener("click", (e) => { if (e.target === sleepSheet) sleepSheet.hidden = true; });

  for (const preset of document.querySelectorAll(".sleep-preset")) {
    preset.addEventListener("click", async () => {
      const minutes = Number(preset.dataset.minutes);
      const action = $("#sleep-action")?.value || "pause";
      try {
        renderSleepUI(await api("/api/sleep-timer", {
          method: "POST",
          body: JSON.stringify({ minutes, action }),
        }));
        sleepSheet.hidden = true;
        showNotice(`Sleep timer set — ${preset.textContent.trim()}`);
      } catch (e) {
        showNotice(e.message, true);
      }
    });
  }

  $("#sleep-cancel")?.addEventListener("click", async () => {
    try {
      renderSleepUI(await api("/api/sleep-timer", { method: "DELETE" }));
      showNotice("Sleep timer cancelled");
    } catch (e) {
      showNotice(e.message, true);
    }
  });

  setInterval(updateSleepCountdown, 1000);
  setInterval(pollSleep, 30000);
  pollSleep();

  /* ────────────────────────────── log tools ── */
  $("#log-lines")?.addEventListener("change", () => refreshLogs().catch((e) => showNotice(e.message, true)));

  $("#download-logs")?.addEventListener("click", () => {
    const target = $("#log-target")?.value || "spotify";
    const text = $("#logs")?.textContent || "";
    if (!text.trim()) {
      showNotice("Nothing to download — refresh logs first", true);
      return;
    }
    const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
    const blob = new Blob([text], { type: "text/plain" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `spotpi-${target}-${stamp}.log`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 2000);
  });

  /* ────────────────────────────── config export / import ── */
  $("#export-config")?.addEventListener("click", async () => {
    try {
      const pin = localStorage.getItem("spotpiPin");
      const res = await fetch("/api/settings/export", { headers: pin ? { "X-SpotPi-Pin": pin } : {} });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") || "";
      const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] || "spotpi-config.toml";
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 2000);
      showNotice("Config exported");
    } catch (e) {
      showNotice(e.message, true);
    }
  });

  const importInput = $("#import-config-file");
  $("#import-config")?.addEventListener("click", () => importInput?.click());
  importInput?.addEventListener("change", async () => {
    const file = importInput.files && importInput.files[0];
    importInput.value = "";
    if (!file) return;
    if (!window.confirm(`Replace the current settings with "${file.name}"? The current config is backed up automatically first.`)) return;
    try {
      const toml = await file.text();
      const payload = await api("/api/settings/import", { method: "POST", body: JSON.stringify({ toml }) });
      state.config = payload.config;
      renderSettings();
      await Promise.allSettled([refreshStatus(), refreshBackups(), refreshPreview()]);
      showNotice("Config imported — use Save & Restart to apply to playback");
    } catch (e) {
      showNotice(e.message, true);
    }
  });

  /* ────────────────────────────── keyboard shortcuts ── */
  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    const target = e.target;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" || target.isContentEditable)) return;
    if (e.code === "Space") {
      if (playPauseBtn && !playPauseBtn.disabled) {
        e.preventDefault();
        playPauseBtn.click();
      }
    } else if (e.key === "ArrowRight") {
      const next = $("#skip-next");
      if (next && !next.disabled) {
        e.preventDefault();
        next.click();
      }
    } else if (e.key === "ArrowLeft") {
      const prev = $("#skip-prev");
      if (prev && !prev.disabled) {
        e.preventDefault();
        prev.click();
      }
    }
  });
})();
