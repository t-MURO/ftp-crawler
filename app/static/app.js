(() => {
  "use strict";

  const state = {
    q: "",
    extension: "",
    min_size: "",
    max_size: "",
    modified_from: "",
    modified_to: "",
    directory: "",
    status: "available",
    sort: "filename",
    order: "asc",
    page: 1,
    per_page: Number(document.body.dataset.defaultPerPage || 50),
    pages: 1,
    controller: null,
  };

  const csrfToken = document.body.dataset.csrfToken;
  const byId = (id) => document.getElementById(id);
  const resultsBody = byId("results-body");
  const queryInput = byId("query");
  const heroQuery = byId("hero-query");
  let searchInFlight = false;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function highlight(value) {
    const safe = escapeHtml(value);
    const tokens = state.q.match(/[\p{L}\p{N}_]+/gu) || [];
    if (!tokens.length) return safe;
    const expression = new RegExp(`(${tokens.map(escapeRegExp).join("|")})`, "giu");
    return safe.replace(expression, "<mark>$1</mark>");
  }

  function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value || 0));
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB", "PB"];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    const amount = bytes / 1024 ** index;
    return `${amount >= 100 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
  }

  function formatDate(value, includeTime = false) {
    if (!value) return "Unknown";
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) return "Unknown";
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      ...(includeTime ? { timeStyle: "short" } : {}),
    }).format(date);
  }

  function formatDuration(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    const value = Number(seconds);
    if (value < 60) return `${value}s`;
    if (value < 3600) return `${Math.floor(value / 60)}m ${value % 60}s`;
    return `${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m`;
  }

  async function api(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.method && options.method !== "GET") {
      headers["X-CSRF-Token"] = csrfToken;
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(path, { ...options, headers });
    if (response.status === 401) {
      window.location.href = "/login";
      throw new Error("Authentication required");
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg).join(", ")
        : payload.detail;
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return payload;
  }

  function toast(message, type = "") {
    const item = document.createElement("div");
    item.className = `toast ${type}`;
    item.textContent = message;
    byId("toast-region").appendChild(item);
    window.setTimeout(() => item.remove(), 3600);
  }

  async function copyText(value, label) {
    try {
      await navigator.clipboard.writeText(value);
      toast(`${label} copied`);
    } catch {
      const area = document.createElement("textarea");
      area.value = value;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      toast(`${label} copied`);
    }
  }

  function searchParams() {
    const params = new URLSearchParams();
    Object.entries(state).forEach(([key, value]) => {
      if (["pages", "controller"].includes(key)) return;
      if (value !== "" && value !== null && value !== undefined) {
        params.set(key, String(value));
      }
    });
    return params;
  }

  function renderResults(items) {
    if (!items.length) {
      resultsBody.innerHTML = `
        <tr class="empty-row">
          <td colspan="6">No indexed files match these filters.</td>
        </tr>`;
      return;
    }
    resultsBody.innerHTML = items.map((item) => {
      const icon = ["mp3", "wav", "flac", "aiff", "m4a", "ogg"].includes(item.extension) ? "♪" : "·";
      const status = item.available
        ? '<span class="availability">Available</span>'
        : '<span class="availability deleted">Unavailable</span>';
      const direct = item.direct_url
        ? `<a class="row-action" href="${escapeHtml(item.direct_url)}" aria-label="Open FTP link" title="Open FTP link">↗</a>`
        : "";
      return `
        <tr class="result-row">
          <td class="file-column">
            <div class="file-cell">
              <span class="file-icon" aria-hidden="true">${icon}</span>
              <div>
                <button class="file-name" type="button" data-detail="${item.id}" title="${escapeHtml(item.filename)}">${highlight(item.filename)}</button>
                <span class="extension-tag">${escapeHtml(item.extension || "file")}</span>
              </div>
            </div>
          </td>
          <td class="path-cell" title="${escapeHtml(item.remote_path)}">
            <span class="cell-label">Folder</span>
            <span class="path-value">${highlight(item.parent_directory)}</span>
          </td>
          <td class="size-cell">
            <span class="cell-label">Size</span>
            <span>${formatBytes(item.size)}</span>
          </td>
          <td class="modified-cell">
            <span class="cell-label">Modified</span>
            <span>${formatDate(item.modified_at)}</span>
          </td>
          <td class="status-cell">
            <span class="cell-label">Status</span>
            ${status}
          </td>
          <td class="actions-cell">
            <div class="row-actions">
              <button class="row-action" type="button" data-copy-name="${escapeHtml(item.filename)}" aria-label="Copy filename" title="Copy filename">N</button>
              <button class="row-action row-action-labeled" type="button" data-copy-path="${escapeHtml(item.remote_path)}" aria-label="Copy FTP path" title="Copy FTP path">
                <span aria-hidden="true">⌘</span>
                <span>Copy path</span>
              </button>
              ${direct}
            </div>
          </td>
        </tr>`;
    }).join("");
  }

  function renderPagination(page, pages) {
    state.page = page;
    state.pages = pages;
    byId("page-summary").textContent = `Page ${page} of ${pages}`;
    byId("page-prev").disabled = page <= 1;
    byId("page-next").disabled = page >= pages;
    const candidates = new Set([1, pages, page - 1, page, page + 1]);
    const values = [...candidates].filter((value) => value >= 1 && value <= pages).sort((a, b) => a - b);
    let previous = 0;
    const html = [];
    values.forEach((value) => {
      if (previous && value - previous > 1) {
        html.push('<span aria-hidden="true">…</span>');
      }
      html.push(`<button class="page-button ${value === page ? "active" : ""}" type="button" data-page="${value}">${value}</button>`);
      previous = value;
    });
    byId("page-buttons").innerHTML = html.join("");
  }

  async function runSearch({ scroll = false } = {}) {
    if (state.controller) state.controller.abort();
    const controller = new AbortController();
    const hasVisibleResults = Boolean(resultsBody.querySelector(".result-row"));
    state.controller = controller;
    searchInFlight = true;
    resultsBody.closest(".results-panel").classList.add("is-searching");
    resultsBody.setAttribute("aria-busy", "true");
    if (!hasVisibleResults) {
      resultsBody.innerHTML = '<tr class="loading-row"><td colspan="6"><span class="loader"></span> Searching the index…</td></tr>';
    }
    try {
      const result = await api(`/api/search?${searchParams()}`, { signal: controller.signal });
      renderResults(result.items);
      byId("result-total").textContent = formatNumber(result.total);
      renderPagination(result.page, result.pages);
      if (scroll) byId("results-title").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      if (error.name === "AbortError") return;
      if (hasVisibleResults) {
        toast(error.message, "error");
      } else {
        resultsBody.innerHTML = `<tr class="error-row"><td colspan="6">${escapeHtml(error.message)}</td></tr>`;
      }
    } finally {
      if (state.controller === controller) {
        searchInFlight = false;
        resultsBody.closest(".results-panel").classList.remove("is-searching");
        resultsBody.removeAttribute("aria-busy");
      }
    }
  }

  function syncFilterState() {
    const fields = ["extension", "directory", "min-size", "max-size", "modified-from", "modified-to", "file-status"];
    fields.forEach((id) => {
      const element = byId(id);
      const key = id.replaceAll("-", "_").replace("file_status", "status");
      state[key] = element.value.trim();
    });
    state.page = 1;
    const count = fields.filter((id) => {
      const value = byId(id).value.trim();
      return value && !(id === "file-status" && value === "available");
    }).length;
    byId("filter-count").textContent = count;
    byId("filter-count").classList.toggle("hidden", count === 0);
  }

  async function loadDashboard() {
    try {
      const data = await api("/api/dashboard");
      byId("stat-files").textContent = formatNumber(data.available_files);
      byId("stat-unavailable").textContent = data.unavailable_files
        ? `${formatNumber(data.unavailable_files)} unavailable · ${formatNumber(data.total_indexed_files)} total`
        : `${formatNumber(data.total_indexed_files)} total indexed`;
      byId("stat-directories").textContent = formatNumber(data.total_directories);
      byId("stat-size").textContent = formatBytes(data.total_size);
      byId("index-updated").textContent = data.last_successful_crawl
        ? `Updated ${formatDate(data.last_successful_crawl, true)}`
        : "No completed scan yet";
      renderScan(data.scan);
      renderExtensions(data.extensions);
    } catch (error) {
      byId("header-status").dataset.state = "error";
      byId("header-status").querySelector("span").textContent = "Index unavailable";
    }
  }

  async function loadScanStatus() {
    try {
      const data = await api("/api/scans/status");
      renderScan(data.scan);
    } catch {
      byId("header-status").dataset.state = "error";
      byId("header-status").querySelector("span").textContent = "Crawler unavailable";
    }
  }

  function pollIfIdle(loader) {
    if (!document.hidden && !searchInFlight) loader();
  }

  function renderScan(scan) {
    const status = scan?.status || "idle";
    const displayStatus = status.replace("_", " ");
    [byId("header-status"), byId("control-status")].forEach((element) => {
      element.dataset.state = status;
      element.querySelector("span").textContent = displayStatus;
    });
    byId("crawler-mini-status").textContent = displayStatus.toUpperCase();
    const active = ["queued", "running", "stopping"].includes(status);
    const resumable = ["stopped", "failed"].includes(status);
    byId("scan-incremental").disabled = active;
    byId("scan-full").disabled = active;
    byId("scan-stop").classList.toggle("hidden", !active);
    byId("scan-resume").classList.toggle("hidden", !resumable);
    byId("scan-location-label").textContent = resumable ? "SAVED CHECKPOINT" : "CURRENT FOLDER";
    byId("crawler-current").textContent = scan?.current_directory
      || (resumable ? "Progress saved — ready to continue" : active ? "Connecting…" : "Waiting for a scan");
    byId("scan-directory").textContent = scan?.current_directory
      || (resumable ? "Saved queue is ready" : "No scan in progress");
    byId("scan-note").textContent = resumable
      ? "Completed folders are preserved. Continue uses the saved queue and does not rescan them."
      : "Each completed folder is saved so an interrupted scan can continue without starting over.";
    byId("crawler-progress-copy").textContent = scan
      ? `${formatNumber(scan.directories_scanned)} / ${formatNumber(scan.directories_queued)} folders`
      : "Ready when you are";
    byId("crawler-progress-bar").style.width = `${scan?.progress_percent || 0}%`;
    byId("scan-duration").textContent = formatDuration(scan?.duration_seconds);
    byId("scan-folders").textContent = scan ? `${formatNumber(scan.directories_scanned)} / ${formatNumber(scan.directories_queued)}` : "—";
    byId("scan-failed").textContent = scan ? formatNumber(scan.failed) : "—";
    byId("server-pulse").style.background = status === "failed" ? "var(--red)" : "var(--green)";
  }

  function renderExtensions(items) {
    const container = byId("extension-chart");
    if (!items.length) {
      container.innerHTML = '<div class="chart-empty">Extension data appears after the first scan.</div>';
      return;
    }
    const max = Math.max(...items.map((item) => item.count), 1);
    container.innerHTML = items.slice(0, 10).map((item) => `
      <div class="extension-row">
        <span class="extension-name">${escapeHtml(item.extension)}</span>
        <span class="extension-bar"><span style="width: ${Math.max(1, (item.count / max) * 100)}%"></span></span>
        <span class="extension-count">${formatNumber(item.count)}</span>
      </div>
    `).join("");
  }

  async function scanAction(path, body) {
    try {
      const options = { method: "POST" };
      if (body) options.body = JSON.stringify(body);
      await api(path, options);
      toast("Crawler request accepted");
      await loadScanStatus();
      await loadLogs();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function loadLogs() {
    try {
      const level = byId("log-level").value;
      const data = await api(`/api/logs?limit=100${level ? `&level=${level}` : ""}`);
      const items = data.items;
      byId("log-list").innerHTML = items.length
        ? items.map((item) => `
          <div class="log-item">
            <span class="log-level ${escapeHtml(item.level)}">${escapeHtml(item.level)}</span>
            <time class="log-time">${formatDate(item.created_at, true)}</time>
            <span class="log-message">${escapeHtml(item.message)}${item.directory ? `<code>${escapeHtml(item.directory)}</code>` : ""}</span>
          </div>
        `).join("")
        : '<div class="chart-empty">No crawler events yet.</div>';
    } catch {
      byId("log-list").innerHTML = '<div class="chart-empty">Could not load crawler activity.</div>';
    }
  }

  async function loadSettings() {
    try {
      const values = await api("/api/settings");
      const form = byId("settings-form");
      [...form.elements].forEach((element) => {
        if (!element.name || !(element.name in values)) return;
        if (element.type === "checkbox") element.checked = Boolean(values[element.name]);
        else element.value = values[element.name] ?? "";
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function saveSettings(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const payload = {};
    ["ftp_host", "ftp_protocol", "ftp_username", "ftp_root_path", "file_extension_whitelist", "scan_schedule"].forEach((key) => {
      payload[key] = String(data.get(key) ?? "");
    });
    ["ftp_port", "ftp_timeout_seconds", "ftp_max_retries", "ftp_request_delay_ms", "default_results_per_page"].forEach((key) => {
      payload[key] = Number(data.get(key));
    });
    ["ftp_passive_mode", "music_filename_parsing", "enable_direct_ftp_links"].forEach((key) => {
      payload[key] = data.has(key);
    });
    try {
      await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
      const indicator = byId("settings-saved");
      indicator.textContent = "Settings saved";
      indicator.classList.add("saved");
      window.setTimeout(() => {
        indicator.textContent = "Environment password protected";
        indicator.classList.remove("saved");
      }, 3000);
      toast("Crawler settings saved");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function closeResetDialog() {
    const dialog = byId("reset-dialog");
    dialog.close();
    byId("reset-data-form").reset();
    byId("reset-data-confirm").disabled = true;
  }

  async function resetAllData(event) {
    event.preventDefault();
    const confirmation = byId("reset-confirmation").value;
    if (confirmation !== "DELETE") return;

    const button = byId("reset-data-confirm");
    button.disabled = true;
    button.textContent = "Removing…";
    try {
      const result = await api("/api/data/reset", {
        method: "POST",
        body: JSON.stringify({ confirmation }),
      });
      closeResetDialog();
      state.page = 1;
      await Promise.all([runSearch(), loadDashboard(), loadLogs()]);
      const removed = Object.values(result.deleted).reduce((total, value) => total + Number(value), 0);
      toast(`Started over with an empty index (${formatNumber(removed)} records removed)`);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.textContent = "Remove data and start over";
      button.disabled = byId("reset-confirmation").value !== "DELETE";
    }
  }

  async function openDetail(fileId) {
    try {
      const item = await api(`/api/files/${fileId}`);
      byId("dialog-filename").textContent = item.filename;
      const fields = [
        ["Remote path", item.remote_path, true],
        ["Size", formatBytes(item.size)],
        ["Modified", formatDate(item.modified_at, true)],
        ["First indexed", formatDate(item.first_seen_at, true)],
        ["Artist", item.artist],
        ["Track title", item.track_title],
        ["Version", item.version],
        ["Release year", item.release_year],
        ["Label", item.label],
        ["Catalog number", item.catalog_number],
      ].filter(([, value]) => value !== null && value !== undefined && value !== "");
      byId("dialog-content").innerHTML = `<div class="detail-grid">${fields.map(([label, value, wide]) => `
        <div class="detail-item ${wide ? "detail-wide" : ""}">
          <small>${escapeHtml(label)}</small>
          ${wide ? `<code>${escapeHtml(value)}</code>` : `<strong>${escapeHtml(value)}</strong>`}
        </div>`).join("")}</div>`;
      byId("file-dialog").showModal();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function bindEvents() {
    byId("hero-search").addEventListener("submit", (event) => {
      event.preventDefault();
      state.q = heroQuery.value.trim();
      queryInput.value = state.q;
      state.page = 1;
      runSearch({ scroll: true });
    });
    let debounceTimer;
    queryInput.addEventListener("input", () => {
      const nextQuery = queryInput.value.trim();
      heroQuery.value = nextQuery;
      if (nextQuery === state.q) return;
      state.q = nextQuery;
      state.page = 1;
      window.clearTimeout(debounceTimer);
      if (state.q.length === 1) return;
      debounceTimer = window.setTimeout(() => runSearch(), 500);
    });
    byId("search-form").addEventListener("submit", (event) => {
      event.preventDefault();
      state.q = queryInput.value.trim();
      state.page = 1;
      runSearch();
    });
    byId("per-page").value = String(state.per_page);
    byId("per-page").addEventListener("change", (event) => {
      state.per_page = Number(event.target.value);
      state.page = 1;
      runSearch();
    });
    byId("filters-toggle").addEventListener("click", () => {
      const panel = byId("filter-panel");
      panel.classList.toggle("hidden");
      byId("filters-toggle").setAttribute("aria-expanded", String(!panel.classList.contains("hidden")));
    });
    byId("filter-panel").addEventListener("submit", (event) => {
      event.preventDefault();
      syncFilterState();
      runSearch();
    });
    byId("clear-filters").addEventListener("click", () => {
      byId("filter-panel").reset();
      byId("file-status").value = "available";
      syncFilterState();
      runSearch();
    });
    document.querySelectorAll(".sort-button").forEach((button) => {
      button.addEventListener("click", () => {
        const sort = button.dataset.sort;
        state.order = state.sort === sort && state.order === "asc" ? "desc" : "asc";
        state.sort = sort;
        state.page = 1;
        document.querySelectorAll(".sort-button").forEach((item) => {
          const active = item.dataset.sort === sort;
          item.classList.toggle("active", active);
          item.querySelector("span").textContent = active ? (state.order === "asc" ? "↑" : "↓") : "↕";
        });
        runSearch();
      });
    });
    byId("page-prev").addEventListener("click", () => {
      if (state.page > 1) {
        state.page -= 1;
        runSearch({ scroll: true });
      }
    });
    byId("page-next").addEventListener("click", () => {
      if (state.page < state.pages) {
        state.page += 1;
        runSearch({ scroll: true });
      }
    });
    byId("page-buttons").addEventListener("click", (event) => {
      const button = event.target.closest("[data-page]");
      if (!button) return;
      state.page = Number(button.dataset.page);
      runSearch({ scroll: true });
    });
    resultsBody.addEventListener("click", (event) => {
      const copyPath = event.target.closest("[data-copy-path]");
      const copyName = event.target.closest("[data-copy-name]");
      const detail = event.target.closest("[data-detail]");
      if (copyPath) copyText(copyPath.dataset.copyPath, "FTP path");
      if (copyName) copyText(copyName.dataset.copyName, "Filename");
      if (detail) openDetail(detail.dataset.detail);
    });
    byId("scan-incremental").addEventListener("click", () => scanAction("/api/scans", { mode: "incremental" }));
    byId("scan-full").addEventListener("click", () => scanAction("/api/scans", { mode: "full" }));
    byId("scan-stop").addEventListener("click", () => scanAction("/api/scans/stop"));
    byId("scan-resume").addEventListener("click", () => scanAction("/api/scans/continue"));
    byId("log-level").addEventListener("change", loadLogs);
    byId("settings-form").addEventListener("submit", saveSettings);
    byId("reset-data-open").addEventListener("click", () => {
      byId("reset-data-form").reset();
      byId("reset-data-confirm").disabled = true;
      byId("reset-dialog").showModal();
      byId("reset-confirmation").focus();
    });
    byId("reset-confirmation").addEventListener("input", (event) => {
      byId("reset-data-confirm").disabled = event.target.value !== "DELETE";
    });
    byId("reset-data-form").addEventListener("submit", resetAllData);
    byId("reset-dialog-close").addEventListener("click", closeResetDialog);
    byId("reset-dialog-cancel").addEventListener("click", closeResetDialog);
    byId("reset-dialog").addEventListener("click", (event) => {
      if (event.target === byId("reset-dialog")) closeResetDialog();
    });
    byId("dialog-close").addEventListener("click", () => byId("file-dialog").close());
    byId("file-dialog").addEventListener("click", (event) => {
      if (event.target === byId("file-dialog")) byId("file-dialog").close();
    });
    const storedTheme = localStorage.getItem("ftp-indexer-theme");
    const preferredDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = storedTheme || (preferredDark ? "dark" : "light");
    byId("theme-toggle").addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("ftp-indexer-theme", next);
    });
    byId("mobile-menu").addEventListener("click", () => document.querySelector(".sidebar").classList.toggle("open"));
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.addEventListener("click", () => {
        document.querySelectorAll(".nav-item").forEach((nav) => nav.classList.remove("active"));
        item.classList.add("active");
        document.querySelector(".sidebar").classList.remove("open");
      });
    });
    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        heroQuery.focus();
      }
      if (event.key === "Escape") document.querySelector(".sidebar").classList.remove("open");
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) Promise.all([loadScanStatus(), loadLogs()]);
    });
  }

  bindEvents();
  Promise.all([runSearch(), loadDashboard(), loadLogs(), loadSettings()]);
  window.setInterval(() => pollIfIdle(loadScanStatus), 5000);
  window.setInterval(() => pollIfIdle(loadLogs), 30000);
  window.setInterval(() => pollIfIdle(loadDashboard), 60000);
})();
