// K6 Monitor Dashboard — Frappe Page Controller
// Grafana-like real-time monitoring for Frappe / ERPNext

frappe.pages["k6-monitor"].on_load = function (wrapper) {
  frappe.ui.make_app_page({
    parent: wrapper,
    title: "K6 Performance Monitor",
    single_column: true,
  });

  const page = new K6MonitorPage(wrapper);
  wrapper.k6_page = page;
};

frappe.pages["k6-monitor"].on_show = function (wrapper) {
  if (wrapper.k6_page) wrapper.k6_page.on_show();
};

frappe.pages["k6-monitor"].on_hide = function (wrapper) {
  if (wrapper.k6_page) wrapper.k6_page.on_hide();
};

// ════════════════════════════════════════════════════════════════
class K6MonitorPage {
  constructor(wrapper) {
    this.wrapper = wrapper;
    this.$main = $(wrapper).find(".page-content");
    this.charts = {};
    this.sysHistory = { labels: [], cpu: [], mem: [], netSent: [], netRecv: [] };
    this.liveHistory = { labels: [], rps: [], avg: [] };
    this.activeRun = null;
    this.activeRunTargetServer = null;
    this.remoteServers = [];
    this.refreshInterval = 5000;
    this._timers = [];
    this._endpointCount = 0;

    this._injectStyles();
    this._render();
    this._bindEvents();
    this._fetchRemoteServers();
    this._startPolling();
    this._loadChartJs(() => this._initCharts());
  }

  on_show() { this._startPolling(); }
  on_hide() { this._stopPolling(); }

  // ── Lifecycle ───────────────────────────────────────────────
  _startPolling() {
    this._stopPolling();
    this._fetchSystemMetrics();
    this._fetchConfigs();
    this._fetchHistory();
    this._checkActiveRuns();

    const t1 = setInterval(() => this._fetchSystemMetrics(), this.refreshInterval);
    const t2 = setInterval(() => this._checkActiveRuns(), 3000);
    const t3 = setInterval(() => { this._fetchConfigs(); this._fetchHistory(); }, 15000);
    this._timers = [t1, t2, t3];
  }

  _stopPolling() {
    this._timers.forEach(clearInterval);
    this._timers = [];
  }

  // ── Render ──────────────────────────────────────────────────
  _render() {
    const $section = $(this.wrapper).find(".layout-main-section");
    if (!$section.length) {
      // fallback: append directly to wrapper
      $(this.wrapper).append(`<div class="layout-main-section">${this._getHTML()}</div>`);
    } else {
      $section.html(this._getHTML());
    }
    this._addEndpointRow();
  }

  _getHTML() {
    return `<div class="k6-monitor-wrap">
  <div class="k6-topbar">
    <div class="k6-brand">
      <span class="k6-logo">⚡</span>
      <span class="k6-title">K6 Performance Monitor</span>
      <span class="k6-badge" id="k6-live-badge">● LIVE</span>
    </div>
    <div class="k6-tabs">
      <button class="k6-tab active" data-tab="dashboard">📊 Dashboard</button>
      <button class="k6-tab" data-tab="loadtest">🚀 Load Tests</button>
      <button class="k6-tab" data-tab="builder">🔧 Test Builder</button>
      <button class="k6-tab" data-tab="history">📋 History</button>
    </div>
    <div class="k6-topbar-right">
      <span class="k6-refresh-info" id="k6-last-refresh">–</span>
      <button class="btn btn-xs btn-default" id="k6-refresh-btn" title="Refresh now">↺</button>
    </div>
  </div>

  <div class="k6-tab-content active" id="tab-dashboard">
    <div class="k6-section-label">🖥 Infrastructure Health</div>
    <div class="k6-cards-row" id="sys-cards">
      <div class="k6-card"><div class="k6-card-icon">⚙️</div><div class="k6-card-body"><div class="k6-card-label">CPU Usage</div><div class="k6-card-value" id="val-cpu">–</div><div class="k6-progress"><div class="k6-progress-bar" id="bar-cpu"></div></div></div></div>
      <div class="k6-card"><div class="k6-card-icon">🧠</div><div class="k6-card-body"><div class="k6-card-label">Memory</div><div class="k6-card-value" id="val-mem">–</div><div class="k6-card-sub" id="sub-mem">–</div><div class="k6-progress"><div class="k6-progress-bar" id="bar-mem"></div></div></div></div>
      <div class="k6-card"><div class="k6-card-icon">💾</div><div class="k6-card-body"><div class="k6-card-label">Disk</div><div class="k6-card-value" id="val-disk">–</div><div class="k6-card-sub" id="sub-disk">–</div><div class="k6-progress"><div class="k6-progress-bar" id="bar-disk"></div></div></div></div>
      <div class="k6-card"><div class="k6-card-icon">⚡</div><div class="k6-card-body"><div class="k6-card-label">Redis</div><div class="k6-card-value" id="val-redis">–</div><div class="k6-card-sub" id="sub-redis">–</div></div></div>
      <div class="k6-card"><div class="k6-card-icon">🗄️</div><div class="k6-card-body"><div class="k6-card-label">Database</div><div class="k6-card-value" id="val-db">–</div><div class="k6-card-sub" id="sub-db">–</div></div></div>
      <div class="k6-card"><div class="k6-card-icon">👷</div><div class="k6-card-body"><div class="k6-card-label">Workers</div><div class="k6-card-value" id="val-workers">–</div><div class="k6-card-sub" id="sub-workers">–</div></div></div>
    </div>
    <div class="k6-charts-row">
      <div class="k6-chart-panel"><div class="k6-chart-title">CPU &amp; Memory History</div><canvas id="chart-sysmetrics" height="90"></canvas></div>
      <div class="k6-chart-panel"><div class="k6-chart-title">Network I/O (MB)</div><canvas id="chart-network" height="90"></canvas></div>
    </div>
    <div id="k6-active-banner" class="k6-active-banner" style="display:none">
      <div class="k6-active-header">
        <div class="k6-section-label" style="margin:0">🔴 Active Load Test</div>
        <div id="k6-active-target-badge" style="display:none;margin-left:16px;font-size:12px;color:#f97316;font-weight:700"></div>
      </div>
      <div class="k6-live-cards">
        <div class="k6-live-card"><span class="k6-lv-label">RPS</span><span class="k6-lv-val" id="lv-rps">–</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">Avg ms</span><span class="k6-lv-val" id="lv-avg">–</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">P95 ms</span><span class="k6-lv-val" id="lv-p95">–</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">Requests</span><span class="k6-lv-val" id="lv-reqs">–</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">Errors</span><span class="k6-lv-val k6-err" id="lv-errs">–</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">VUs</span><span class="k6-lv-val" id="lv-vus">–</span></div>
      </div>
      <div id="k6-remote-server-panel" style="display:none;margin:10px 0;padding:10px 14px;background:#041228;border:1px solid #1e3a5f;border-radius:8px;">
        <div style="font-size:11px;font-weight:700;color:#3b82f6;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">🌐 Target Server — <span id="lv-srv-name">–</span></div>
        <div class="k6-live-cards" style="grid-template-columns:repeat(6,1fr)">
          <div class="k6-live-card" style="background:#041228;border-color:#1e3a5f"><span class="k6-lv-label">CPU %</span><span class="k6-lv-val" id="lv-srv-cpu" style="color:#f97316">–</span></div>
          <div class="k6-live-card" style="background:#041228;border-color:#1e3a5f"><span class="k6-lv-label">RAM %</span><span class="k6-lv-val" id="lv-srv-mem" style="color:#3b82f6">–</span></div>
          <div class="k6-live-card" style="background:#041228;border-color:#1e3a5f"><span class="k6-lv-label">Disk %</span><span class="k6-lv-val" id="lv-srv-disk" style="color:#8b5cf6">–</span></div>
          <div class="k6-live-card" style="background:#041228;border-color:#1e3a5f"><span class="k6-lv-label">RX KB/s</span><span class="k6-lv-val" id="lv-srv-rx" style="color:#22c55e">–</span></div>
          <div class="k6-live-card" style="background:#041228;border-color:#1e3a5f"><span class="k6-lv-label">TX KB/s</span><span class="k6-lv-val" id="lv-srv-tx" style="color:#a855f7">–</span></div>
          <div class="k6-live-card" style="background:#041228;border-color:#1e3a5f"><span class="k6-lv-label">Load 1m</span><span class="k6-lv-val" id="lv-srv-load" style="color:#eab308">–</span></div>
        </div>
        <div style="margin-top:8px;font-size:11px;color:#374151" id="lv-srv-grafana-link"></div>
      </div>
      <div class="k6-chart-panel" style="margin-top:10px"><div class="k6-chart-title">Live: Requests &amp; Response Time</div><canvas id="chart-live" height="80"></canvas></div>
      <div style="margin-top:8px;text-align:right"><button class="btn btn-sm btn-danger" id="btn-stop-active">⏹ Stop Test</button></div>
    </div>
  </div>

  <div class="k6-tab-content" id="tab-loadtest">
    <div class="k6-section-label">🚀 Saved Load Test Configs</div>
    <div style="margin-bottom:10px"><button class="btn btn-sm btn-primary" id="btn-goto-builder">+ New Test Config</button></div>
    <table class="table table-bordered k6-table">
      <thead><tr><th>Test Name</th><th>Scenario</th><th>VUs</th><th>Duration</th><th>Target</th><th>Status</th><th>Last Run</th><th>Actions</th></tr></thead>
      <tbody id="configs-tbody"><tr><td colspan="8" class="text-center text-muted">Loading...</td></tr></tbody>
    </table>
  </div>

  <div class="k6-tab-content" id="tab-builder">
    <div class="k6-section-label">🔧 Build New Load Test</div>
    <div class="k6-builder-form">
      <div class="k6-form-row">
        <div class="k6-form-group"><label>Test Name *</label><input type="text" class="form-control" id="b-test-name" placeholder="My API Load Test"></div>
        <div class="k6-form-group"><label>Scenario</label>
          <select class="form-control" id="b-scenario">
            <option value="smoke">Smoke – 2 VUs, 1 min</option>
            <option value="load" selected>Load – normal traffic</option>
            <option value="stress">Stress – find breaking point</option>
            <option value="spike">Spike – sudden burst</option>
            <option value="soak">Soak – long endurance</option>
          </select>
        </div>
      </div>
      <div class="k6-target-section">
        <div class="k6-section-label" style="margin-bottom:8px">🎯 Test Target</div>
        <div class="k6-form-row" style="margin-bottom:8px">
          <div class="k6-form-group k6-sm">
            <label>Target Type</label>
            <select class="form-control" id="b-target-type">
              <option value="Local Server">🏠 Local Server</option>
              <option value="Remote Server">🌐 Remote Server</option>
            </select>
          </div>
          <div class="k6-form-group" id="b-remote-server-wrap" style="display:none">
            <label>Remote Server</label>
            <select class="form-control" id="b-remote-server">
              <option value="">— select server —</option>
            </select>
          </div>
          <div class="k6-form-group k6-lg" id="b-base-url-wrap" style="display:none">
            <label>Target Base URL <span style="color:#64748b;font-weight:400">(auto-filled, override if needed)</span></label>
            <input type="text" class="form-control" id="b-target-url" placeholder="http://10.0.0.50:8000">
          </div>
        </div>
      </div>
      <div class="k6-form-row">
        <div class="k6-form-group k6-sm"><label>VUs</label><input type="number" class="form-control" id="b-vus" value="10" min="1"></div>
        <div class="k6-form-group k6-sm"><label>Duration</label><input type="text" class="form-control" id="b-duration" value="5m"></div>
        <div class="k6-form-group k6-sm"><label>Ramp Up</label><input type="text" class="form-control" id="b-ramp-up" value="1m"></div>
        <div class="k6-form-group k6-sm"><label>Ramp Down</label><input type="text" class="form-control" id="b-ramp-down" value="30s"></div>
        <div class="k6-form-group k6-sm"><label>Max VUs</label><input type="number" class="form-control" id="b-max-vus" value="100"></div>
        <div class="k6-form-group k6-sm"><label>Think Time (s)</label><input type="number" class="form-control" id="b-think" value="1" step="0.1"></div>
      </div>
      <div class="k6-section-label" style="margin-top:16px">API Endpoints</div>
      <div id="endpoints-list"></div>
      <button class="btn btn-sm btn-default" id="btn-add-endpoint" style="margin-bottom:16px">+ Add Endpoint</button>
      <div style="display:flex;gap:10px;margin-top:10px">
        <button class="btn btn-primary" id="btn-save-config">💾 Save Config</button>
        <button class="btn btn-success" id="btn-save-run">💾 Save &amp; Run Now</button>
        <button class="btn btn-default" id="btn-clear-builder">✕ Clear</button>
      </div>
      <div id="builder-msg" style="margin-top:10px"></div>
    </div>
  </div>

  <div class="k6-tab-content" id="tab-history">
    <div class="k6-section-label">📋 Test Run History</div>
    <table class="table table-bordered k6-table">
      <thead><tr><th>Run</th><th>Config</th><th>Scenario</th><th>Target</th><th>Status</th><th>Started</th><th>Requests</th><th>Errors</th><th>RPS</th><th>Avg ms</th><th>P95 ms</th></tr></thead>
      <tbody id="history-tbody"><tr><td colspan="11" class="text-center text-muted">Loading...</td></tr></tbody>
    </table>
  </div>
</div>`;
  }

  _initCharts() {
    if (!window.Chart) return;
    const commonOpts = {
      responsive: true,
      animation: false,
      plugins: { legend: { display: true, labels: { color: "#aaa", font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: "#aaa", maxTicksLimit: 8 }, grid: { color: "#2a2a2a" } },
        y: { ticks: { color: "#aaa" }, grid: { color: "#2a2a2a" } },
      },
    };

    const sysCtx = document.getElementById("chart-sysmetrics");
    if (sysCtx) {
      this.charts.sys = new Chart(sysCtx, {
        type: "line",
        data: {
          labels: [],
          datasets: [
            { label: "CPU %",    data: [], borderColor: "#f97316", backgroundColor: "rgba(249,115,22,0.12)", tension: 0.3, fill: true },
            { label: "Memory %", data: [], borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,0.12)", tension: 0.3, fill: true },
          ],
        },
        options: { ...commonOpts },
      });
    }

    const netCtx = document.getElementById("chart-network");
    if (netCtx) {
      this.charts.net = new Chart(netCtx, {
        type: "line",
        data: {
          labels: [],
          datasets: [
            { label: "Sent MB",    data: [], borderColor: "#10b981", backgroundColor: "rgba(16,185,129,0.12)", tension: 0.3 },
            { label: "Recv MB",    data: [], borderColor: "#a855f7", backgroundColor: "rgba(168,85,247,0.12)", tension: 0.3 },
          ],
        },
        options: { ...commonOpts },
      });
    }

    const liveCtx = document.getElementById("chart-live");
    if (liveCtx) {
      this.charts.live = new Chart(liveCtx, {
        type: "line",
        data: {
          labels: [],
          datasets: [
            { label: "RPS",     data: [], borderColor: "#22d3ee", yAxisID: "y", tension: 0.3 },
            { label: "Avg ms",  data: [], borderColor: "#fb923c", yAxisID: "y1", tension: 0.3 },
          ],
        },
        options: {
          ...commonOpts,
          scales: {
            x:  { ticks: { color: "#aaa", maxTicksLimit: 10 }, grid: { color: "#2a2a2a" } },
            y:  { ticks: { color: "#22d3ee" }, grid: { color: "#2a2a2a" }, position: "left" },
            y1: { ticks: { color: "#fb923c" }, grid: { drawOnChartArea: false }, position: "right" },
          },
        },
      });
    }
  }

  // ── System Metrics ──────────────────────────────────────────
  _fetchSystemMetrics() {
    frappe.call({
      method: "frappe_k6.api.system_metrics.get_all_metrics",
      callback: (r) => {
        if (r.message) this._renderSystemMetrics(r.message);
        $("#k6-last-refresh").text("Last: " + new Date().toLocaleTimeString());
      },
    });
  }

  _renderSystemMetrics(d) {
    const ts = new Date().toLocaleTimeString();

    // CPU
    const cpu = d.cpu || {};
    const cpuPct = cpu.percent || 0;
    this._setCard("val-cpu", cpuPct.toFixed(1) + "%", cpuPct > 85 ? "danger" : cpuPct > 60 ? "warn" : "ok");
    this._setBar("bar-cpu", cpuPct, cpuPct > 85 ? "#ef4444" : cpuPct > 60 ? "#f59e0b" : "#22c55e");

    // Memory
    const mem = d.memory || {};
    const memPct = mem.percent || 0;
    this._setCard("val-mem", memPct.toFixed(1) + "%");
    $("#sub-mem").text(`${mem.used_gb || 0} / ${mem.total_gb || 0} GB`);
    this._setBar("bar-mem", memPct, memPct > 85 ? "#ef4444" : "#3b82f6");

    // Disk
    const disk = d.disk || {};
    this._setCard("val-disk", (disk.percent || 0).toFixed(1) + "%");
    $("#sub-disk").text(`${disk.used_gb || 0} / ${disk.total_gb || 0} GB`);
    this._setBar("bar-disk", disk.percent || 0, "#8b5cf6");

    // Redis
    const redis = d.redis || {};
    if (redis.status === "connected") {
      this._setCard("val-redis", `${redis.memory_mb || 0} MB`, "ok");
      $("#sub-redis").text(`Hit: ${redis.hit_ratio || 0}%  Clients: ${redis.connected_clients || 0}`);
    } else {
      this._setCard("val-redis", "Error", "danger");
      $("#sub-redis").text(redis.message || "disconnected");
    }

    // DB
    const db = d.database || {};
    if (db.status === "connected") {
      this._setCard("val-db", `${db.connections || 0} conn`);
      $("#sub-db").text(`Slow: ${db.slow_queries || 0}  Max: ${db.max_connections || "?"}`);
    } else {
      this._setCard("val-db", "Error", "danger");
    }

    // Workers + Queues
    const gw = d.gunicorn || {};
    const bg = d.workers  || {};
    const q  = d.queues   || {};
    this._setCard("val-workers", `${gw.count || 0} web / ${bg.count || 0} bg`);
    $("#sub-workers").text(`Q: ${q.default || 0} / ${q.long || 0} / ${q.short || 0}`);

    // Update sys chart
    this.sysHistory.labels.push(ts);
    this.sysHistory.cpu.push(cpuPct);
    this.sysHistory.mem.push(memPct);
    if (this.sysHistory.labels.length > 30) {
      ["labels", "cpu", "mem"].forEach(k => this.sysHistory[k].shift());
    }
    if (this.charts.sys) {
      this.charts.sys.data.labels = [...this.sysHistory.labels];
      this.charts.sys.data.datasets[0].data = [...this.sysHistory.cpu];
      this.charts.sys.data.datasets[1].data = [...this.sysHistory.mem];
      this.charts.sys.update("none");
    }

    // Update net chart
    const net = d.network || {};
    this.sysHistory.netSent.push(net.bytes_sent_mb || 0);
    this.sysHistory.netRecv.push(net.bytes_recv_mb || 0);
    if (this.sysHistory.netSent.length > 30) {
      this.sysHistory.netSent.shift();
      this.sysHistory.netRecv.shift();
    }
    if (this.charts.net) {
      this.charts.net.data.labels = [...this.sysHistory.labels];
      this.charts.net.data.datasets[0].data = [...this.sysHistory.netSent];
      this.charts.net.data.datasets[1].data = [...this.sysHistory.netRecv];
      this.charts.net.update("none");
    }
  }

  // ── Active Runs ─────────────────────────────────────────────
  _checkActiveRuns() {
    frappe.call({
      method: "frappe_k6.api.load_test.get_active_runs",
      callback: (r) => {
        const runs = r.message || [];
        if (runs.length > 0) {
          const run = runs[0];
          this.activeRun = run.name;
          $("#k6-active-banner").show();
          this._fetchLiveMetrics(this.activeRun);
        } else {
          this.activeRun = null;
          this.activeRunTargetServer = null;
          $("#k6-active-banner").hide();
          $("#k6-remote-server-panel").hide();
          $("#k6-active-target-badge").hide();
        }
      },
    });
  }

  _fetchLiveMetrics(runName) {
    frappe.call({
      method: "frappe_k6.api.load_test.get_test_status",
      args: { run_name: runName },
      callback: (r) => {
        if (!r.message) return;
        const m   = r.message.metrics || {};
        const dur = m.http_req_duration || {};
        const reqs = m.http_reqs || {};
        const errs = m.http_req_failed || {};
        const vus  = m.vus || {};

        $("#lv-rps").text(m.rps || 0);
        $("#lv-avg").text(dur.avg || 0);
        $("#lv-p95").text(dur.p95 || 0);
        $("#lv-reqs").text(reqs.count || 0);
        $("#lv-errs").text((errs.count || 0) + " (" + (m.error_rate || 0) + "%)");
        $("#lv-vus").text(vus.current || 0);

        // Show remote server panel if target is a remote server
        const target = r.message.target_server_name;
        if (target && target !== "local") {
          this.activeRunTargetServer = target;
          $("#k6-active-target-badge").text("\uD83C\uDF10 Target: " + target).show();
          $("#k6-remote-server-panel").show();
          $("#lv-srv-name").text(target);
          this._fetchRemoteServerMetrics(target);
          // Grafana deep-dive link
          const cfg = window._k6Cfg || {};
          if (cfg.grafana) {
            $("#lv-srv-grafana-link").html(
              `<a href="${cfg.grafana}/d/frappe-k6-remote?var-server=${encodeURIComponent(target)}" target="_blank" style="color:#3b82f6">\uD83D\uDCCA Open Remote Server Dashboard in Grafana \u2192</a>`
            );
          }
        } else {
          this.activeRunTargetServer = null;
          $("#k6-remote-server-panel").hide();
          $("#k6-active-target-badge").hide();
        }

        // Update live chart
        const timeline = m.timeline || [];
        if (timeline.length && this.charts.live) {
          this.charts.live.data.labels = timeline.map(b => b.time.slice(11, 19));
          this.charts.live.data.datasets[0].data = timeline.map(b => b.rps);
          this.charts.live.data.datasets[1].data = timeline.map(b => b.avg_ms);
          this.charts.live.update("none");
        }
      },
    });
  }

  _fetchRemoteServerMetrics(serverName) {
    frappe.call({
      method: "frappe_k6.api.load_test.get_remote_server_live_metrics",
      args: { server_name: serverName },
      callback: (r) => {
        const d = r.message || {};
        const fmt = (v) => v !== null && v !== undefined ? parseFloat(v).toFixed(1) : "–";
        const fmtInt = (v) => v !== null && v !== undefined ? Math.round(v) : "–";
        $("#lv-srv-cpu").text(fmt(d.cpu_percent) + (d.cpu_percent !== null ? "%" : ""));
        $("#lv-srv-mem").text(fmt(d.memory_percent) + (d.memory_percent !== null ? "%" : ""));
        $("#lv-srv-disk").text(fmt(d.disk_percent) + (d.disk_percent !== null ? "%" : ""));
        $("#lv-srv-rx").text(fmtInt(d.network_rx_kbps));
        $("#lv-srv-tx").text(fmtInt(d.network_tx_kbps));
        $("#lv-srv-load").text(fmt(d.load_avg_1m));
      },
    });
  }

  _fetchRemoteServers() {
    frappe.call({
      method: "frappe_k6.api.load_test.get_remote_servers",
      callback: (r) => {
        this.remoteServers = r.message || [];
        this._populateRemoteServers();
      },
    });
  }

  _populateRemoteServers() {
    const $sel = $("#b-remote-server");
    $sel.html('<option value="">— select server —</option>');
    this.remoteServers.forEach(s => {
      const label = `${s.server_name} (${s.environment || ""}) — ${s.host}`;
      $sel.append(`<option value="${s.name}" data-url="${s.frappe_url || ''}" data-sname="${s.server_name}">${label}</option>`);
    });
    if (!this.remoteServers.length) {
      $sel.append('<option value="" disabled>No remote servers configured</option>');
    }
  }

  // ── Configs Table ────────────────────────────────────────────
  _fetchConfigs() {
    frappe.call({
      method: "frappe_k6.api.load_test.get_configs",
      callback: (r) => {
        const rows = r.message || [];
        const tbody = $("#configs-tbody");
        if (!rows.length) {
          tbody.html('<tr><td colspan="8" class="text-center text-muted">No configs yet. Create one in the Test Builder tab.</td></tr>');
          return;
        }
        tbody.html(rows.map(c => {
          const tgt = c.target_type === "Remote Server"
            ? `<span style="color:#f97316;font-size:11px">🌐 ${c.remote_server || "remote"}</span>`
            : `<span style="color:#64748b;font-size:11px">🏠 local</span>`;
          return `<tr>
            <td><b>${c.test_name || c.name}</b></td>
            <td><span class="k6-badge-scenario k6-scenario-${c.scenario_type}">${c.scenario_type}</span></td>
            <td>${c.virtual_users}</td>
            <td>${c.duration}</td>
            <td>${tgt}</td>
            <td><span class="k6-status k6-status-${(c.status || "").toLowerCase()}">${c.status || "Draft"}</span></td>
            <td>${c.last_run ? `<a href="/app/load-test-run/${c.last_run}">${c.last_run}</a>` : "–"}</td>
            <td>
              <button class="btn btn-xs btn-success btn-run-config" data-name="${c.name}" ${c.status === "Running" ? "disabled" : ""}>▶ Run</button>
              <button class="btn btn-xs btn-default btn-edit-config" data-name="${c.name}">✏</button>
              <a href="/app/load-test-config/${c.name}" class="btn btn-xs btn-default" target="_blank">↗</a>
            </td>
          </tr>`;
        }).join(""));
      },
    });
  }

  // ── History Table ────────────────────────────────────────────
  _fetchHistory() {
    frappe.call({
      method: "frappe_k6.api.load_test.get_run_history",
      args: { limit: 20 },
      callback: (r) => {
        const rows = r.message || [];
        const tbody = $("#history-tbody");
        if (!rows.length) {
          tbody.html('<tr><td colspan="11" class="text-center text-muted">No runs yet.</td></tr>');
          return;
        }
        tbody.html(rows.map(row => {
          const target = row.target_server_name && row.target_server_name !== "local"
            ? `<span style="color:#f97316;font-size:11px">🌐 ${row.target_server_name}</span>`
            : `<span style="color:#64748b;font-size:11px">🏠 local</span>`;
          return `<tr>
            <td><a href="/app/load-test-run/${row.name}" target="_blank">${row.name}</a></td>
            <td>${row.config}</td>
            <td><span class="k6-badge-scenario k6-scenario-${row.scenario_type}">${row.scenario_type || "–"}</span></td>
            <td>${target}</td>
            <td><span class="k6-status k6-status-${(row.status || "").toLowerCase()}">${row.status}</span></td>
            <td>${row.started_at ? row.started_at.slice(0, 16) : "–"}</td>
            <td>${row.total_requests || 0}</td>
            <td class="${row.failed_requests > 0 ? "text-danger" : ""}">${row.failed_requests || 0}</td>
            <td>${row.requests_per_sec || 0}</td>
            <td>${row.avg_duration_ms || 0}</td>
            <td>${row.p95_duration_ms || 0}</td>
          </tr>`;
        }).join(""));
      },
    });
  }

  // ── Bind Events ──────────────────────────────────────────────
  _bindEvents() {
    const $wrap = $(this.wrapper);

    // Tab switching
    $wrap.on("click", ".k6-tab", (e) => {
      const tab = $(e.currentTarget).data("tab");
      $wrap.find(".k6-tab").removeClass("active");
      $(e.currentTarget).addClass("active");
      $wrap.find(".k6-tab-content").removeClass("active");
      $wrap.find(`#tab-${tab}`).addClass("active");
      if (tab === "loadtest") this._fetchConfigs();
      if (tab === "history")  this._fetchHistory();
    });

    // Manual refresh
    $wrap.on("click", "#k6-refresh-btn", () => {
      this._fetchSystemMetrics();
      this._checkActiveRuns();
    });

    // Add endpoint row
    $wrap.on("click", "#btn-add-endpoint", () => this._addEndpointRow());

    // Remove endpoint row
    $wrap.on("click", ".btn-remove-ep", (e) => {
      $(e.currentTarget).closest(".k6-ep-row").remove();
    });

    // Target type toggle
    $wrap.on("change", "#b-target-type", (e) => {
      const isRemote = $(e.currentTarget).val() === "Remote Server";
      $("#b-remote-server-wrap").toggle(isRemote);
      $("#b-base-url-wrap").toggle(isRemote);
      if (isRemote && !this.remoteServers.length) this._fetchRemoteServers();
    });

    // Remote server selection → auto-fill base URL
    $wrap.on("change", "#b-remote-server", (e) => {
      const $opt = $(e.currentTarget).find(":selected");
      const url  = $opt.data("url") || "";
      $("#b-target-url").val(url);
    });

    // Save config
    $wrap.on("click", "#btn-save-config", () => this._saveConfig(false));

    // Save & Run
    $wrap.on("click", "#btn-save-run", () => this._saveConfig(true));

    // Clear builder
    $wrap.on("click", "#btn-clear-builder", () => {
      $wrap.find("#b-test-name").val("");
      $wrap.find("#endpoints-list").empty();
      this._addEndpointRow();
      $("#builder-msg").html("");
    });

    // Go to builder
    $wrap.on("click", "#btn-goto-builder", () => {
      $wrap.find(".k6-tab[data-tab='builder']").click();
    });

    // Run config from table
    $wrap.on("click", ".btn-run-config", (e) => {
      const name = $(e.currentTarget).data("name");
      this._runConfig(name);
    });

    // Edit config — load into builder
    $wrap.on("click", ".btn-edit-config", (e) => {
      const name = $(e.currentTarget).data("name");
      this._loadConfigIntoBuilder(name);
    });

    // Stop active test
    $wrap.on("click", "#btn-stop-active", () => {
      if (!this.activeRun) return;
      frappe.confirm(`Stop test ${this.activeRun}?`, () => {
        frappe.call({
          method: "frappe_k6.api.load_test.stop_load_test",
          args: { run_name: this.activeRun },
          callback: () => {
            frappe.show_alert({ message: "Stop requested; k6 is shutting down.", indicator: "orange" });
            this.activeRun = null;
            $("#k6-active-banner").hide();
            this._fetchConfigs();
          },
        });
      });
    });
  }

  // ── Test Builder ─────────────────────────────────────────────
  _loadConfigIntoBuilder(configName) {
    frappe.call({
      method: "frappe_k6.api.load_test.get_config",
      args: { config_name: configName },
      callback: (r) => {
        if (!r.message) return;
        const c = r.message;
        const $wrap = $(this.wrapper);

        $wrap.find("#b-test-name").val(c.test_name);
        $wrap.find("#b-scenario").val(c.scenario_type);
        $wrap.find("#b-vus").val(c.virtual_users);
        $wrap.find("#b-duration").val(c.duration);
        $wrap.find("#b-ramp-up").val(c.ramp_up_time);
        $wrap.find("#b-ramp-down").val(c.ramp_down_time);
        $wrap.find("#b-max-vus").val(c.max_vus);
        $wrap.find("#b-think").val(c.think_time);

        // Restore target
        const targetType = c.target_type || "Local Server";
        $wrap.find("#b-target-type").val(targetType);
        if (targetType === "Remote Server") {
          $("#b-remote-server-wrap").show();
          $("#b-base-url-wrap").show();
          if (c.remote_server) $wrap.find("#b-remote-server").val(c.remote_server);
          if (c.target_base_url) $wrap.find("#b-target-url").val(c.target_base_url);
        } else {
          $("#b-remote-server-wrap").hide();
          $("#b-base-url-wrap").hide();
        }

        // Restore endpoints
        $("#endpoints-list").empty();
        (c.endpoints || []).forEach(ep => {
          this._addEndpointRow();
          const $row = $("#endpoints-list .k6-ep-row").last();
          $row.find(".ep-name").val(ep.api_name);
          $row.find(".ep-method").val(ep.http_method);
          $row.find(".ep-url").val(ep.endpoint_url);
          $row.find(".ep-status").val(ep.expected_status);
          $row.find(".ep-auth-type").val(ep.auth_type);
          $row.find(".ep-auth-val").val(ep.auth_value);
          $row.find(".ep-headers").val(ep.headers);
          $row.find(".ep-params").val(ep.query_params);
          $row.find(".ep-payload").val(ep.payload);
          $row.find(".ep-weight").val(ep.weight);
        });

        // Switch to builder tab
        $wrap.find(".k6-tab[data-tab='builder']").click();
        $("#builder-msg").html(`<div class="alert alert-info">Loaded config <b>${c.test_name}</b> for editing. Saving will create a new config.</div>`);
      },
    });
  }

  _addEndpointRow() {
    const i = ++this._endpointCount;
    const row = `
      <div class="k6-ep-row" data-ep="${i}">
        <div class="k6-ep-header">
          <b>Endpoint #${i}</b>
          <button class="btn btn-xs btn-danger btn-remove-ep">✕ Remove</button>
        </div>
        <div class="k6-ep-fields">
          <div class="k6-form-group">
            <label>API Name *</label>
            <input type="text" class="form-control ep-name" placeholder="Get Students">
          </div>
          <div class="k6-form-group k6-sm">
            <label>Method</label>
            <select class="form-control ep-method">
              <option>GET</option><option>POST</option><option>PUT</option>
              <option>PATCH</option><option>DELETE</option>
            </select>
          </div>
          <div class="k6-form-group k6-lg">
            <label>Endpoint URL *</label>
            <input type="text" class="form-control ep-url" placeholder="/api/resource/Student">
          </div>
          <div class="k6-form-group k6-sm">
            <label>Expected Status</label>
            <input type="number" class="form-control ep-status" value="200">
          </div>
        </div>
        <div class="k6-ep-fields">
          <div class="k6-form-group">
            <label>Auth Type</label>
            <select class="form-control ep-auth-type">
              <option>Session (Frappe Login)</option>
              <option>Bearer Token</option>
              <option>Basic Auth</option>
              <option>API Key</option>
              <option>None</option>
            </select>
          </div>
          <div class="k6-form-group k6-lg">
            <label>Auth Value / Credentials</label>
            <input type="text" class="form-control ep-auth-val" placeholder="user:password  or  Bearer token  or  key:secret">
          </div>
          <div class="k6-form-group k6-sm">
            <label>Weight %</label>
            <input type="number" class="form-control ep-weight" value="100">
          </div>
        </div>
        <div class="k6-ep-fields k6-ep-advanced">
          <div class="k6-form-group">
            <label>Headers (JSON)</label>
            <textarea class="form-control ep-headers" rows="2" placeholder='{"X-Custom": "val"}'></textarea>
          </div>
          <div class="k6-form-group">
            <label>Query Params (JSON)</label>
            <textarea class="form-control ep-params" rows="2" placeholder='{"limit": 10}'></textarea>
          </div>
          <div class="k6-form-group">
            <label>Request Body (JSON)</label>
            <textarea class="form-control ep-payload" rows="2" placeholder='{"key": "value"}'></textarea>
          </div>
        </div>
      </div>`;
    $("#endpoints-list").append(row);
  }

  _saveConfig(runAfter) {
    const $wrap = $(this.wrapper);
    const name  = $wrap.find("#b-test-name").val().trim();
    if (!name) { $("#builder-msg").html('<div class="alert alert-danger">Test Name is required.</div>'); return; }

    const endpoints = [];
    $wrap.find(".k6-ep-row").each(function () {
      const $r = $(this);
      const epName = $r.find(".ep-name").val().trim();
      const url    = $r.find(".ep-url").val().trim();
      if (!epName || !url) return;
      endpoints.push({
        api_name:       epName,
        http_method:    $r.find(".ep-method").val(),
        endpoint_url:   url,
        expected_status: parseInt($r.find(".ep-status").val()) || 200,
        auth_type:      $r.find(".ep-auth-type").val(),
        auth_value:     $r.find(".ep-auth-val").val(),
        headers:        $r.find(".ep-headers").val(),
        query_params:   $r.find(".ep-params").val(),
        payload:        $r.find(".ep-payload").val(),
        weight:         parseInt($r.find(".ep-weight").val()) || 100,
      });
    });

    if (!endpoints.length) { $("#builder-msg").html('<div class="alert alert-danger">Add at least one endpoint.</div>'); return; }

    const targetType   = $wrap.find("#b-target-type").val() || "Local Server";
    const remoteServer = targetType === "Remote Server" ? ($wrap.find("#b-remote-server").val() || null) : null;
    const targetUrl    = $wrap.find("#b-target-url").val().trim() || null;

    const doc = {
      doctype:         "Load Test Config",
      test_name:       name,
      scenario_type:   $wrap.find("#b-scenario").val(),
      virtual_users:   parseInt($wrap.find("#b-vus").val()),
      duration:        $wrap.find("#b-duration").val(),
      target_type:     targetType,
      remote_server:   remoteServer,
      target_base_url: targetUrl,
      ramp_up_time:  $wrap.find("#b-ramp-up").val(),
      ramp_down_time: $wrap.find("#b-ramp-down").val(),
      max_vus:       parseInt($wrap.find("#b-max-vus").val()),
      think_time:    parseFloat($wrap.find("#b-think").val()),
      endpoints:     endpoints,
    };

    $("#builder-msg").html('<div class="alert alert-info">Saving...</div>');

    frappe.call({
      method: "frappe.client.insert",
      args: { doc },
      callback: (r) => {
        if (r.message) {
          $("#builder-msg").html(`<div class="alert alert-success">✅ Saved: <b>${r.message.name}</b></div>`);
          if (runAfter) {
            setTimeout(() => this._runConfig(r.message.name), 500);
          }
          this._fetchConfigs();
        }
      },
    });
  }

  _runConfig(configName) {
    frappe.show_alert({ message: `Starting test: ${configName}…`, indicator: "blue" });
    frappe.call({
      method: "frappe_k6.api.load_test.start_load_test",
      args:   { config_name: configName },
      callback: (r) => {
        if (r.message) {
          frappe.show_alert({ message: `✅ Test started! Run: ${r.message.run_name}`, indicator: "green" });
          this.activeRun = r.message.run_name;
          $("#k6-active-banner").show();
          $(".k6-tab[data-tab='dashboard']").click();
          this._fetchConfigs();
        }
      },
    });
  }

  // ── Helpers ──────────────────────────────────────────────────
  _setCard(id, val, state) {
    const el = $("#" + id);
    el.text(val);
    el.removeClass("k6-ok k6-warn k6-danger");
    if (state) el.addClass("k6-" + state);
  }

  _setBar(id, pct, color) {
    const w = Math.min(100, Math.max(0, pct));
    $(`#${id}`).css({ width: w + "%", background: color });
  }

  // ── Chart.js loader ──────────────────────────────────────────
  _loadChartJs(cb) {
    if (window.Chart) { cb(); return; }
    const s = document.createElement("script");
    s.src = "/assets/frappe_k6/js/chart.umd.min.js";
    s.onload = cb;
    s.onerror = () => {
      // silent fail — charts just won't render, rest of dashboard works
      console.warn("frappe_k6: Chart.js could not load.");
    };
    document.head.appendChild(s);
  }

  // ── CSS injection ────────────────────────────────────────────
  _injectStyles() {
    if (document.getElementById("k6-monitor-styles")) return;
    const style = document.createElement("style");
    style.id = "k6-monitor-styles";
    style.textContent = `
/* ── K6 Monitor Styles ──────────────────────────────────── */
.k6-monitor-wrap { background: #0f1117; min-height: 100vh; color: #e2e8f0; font-family: 'Inter', system-ui, sans-serif; padding: 0; }
.k6-topbar { display:flex; align-items:center; justify-content:space-between; background:#161b27; padding:10px 20px; border-bottom:1px solid #2d3748; flex-wrap:wrap; gap:8px; }
.k6-brand { display:flex; align-items:center; gap:10px; }
.k6-logo { font-size:22px; }
.k6-title { font-size:16px; font-weight:700; color:#fff; }
.k6-badge { font-size:11px; padding:2px 8px; border-radius:12px; background:#22c55e22; color:#22c55e; border:1px solid #22c55e44; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
.k6-tabs { display:flex; gap:4px; }
.k6-tab { border:1px solid #374151; background:transparent; color:#9ca3af; padding:6px 14px; border-radius:6px; cursor:pointer; font-size:13px; transition:all 0.2s; }
.k6-tab:hover { background:#1e293b; color:#fff; }
.k6-tab.active { background:#3b82f6; color:#fff; border-color:#3b82f6; }
.k6-topbar-right { display:flex; align-items:center; gap:8px; font-size:12px; color:#6b7280; }
.k6-tab-content { display:none; padding:16px 20px; }
.k6-tab-content.active { display:block; }
.k6-section-label { font-size:12px; font-weight:600; color:#6b7280; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:10px; }

/* Cards */
.k6-cards-row { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; margin-bottom:20px; }
.k6-card { background:#161b27; border:1px solid #1e293b; border-radius:10px; padding:14px; display:flex; gap:10px; align-items:flex-start; }
.k6-card-icon { font-size:22px; }
.k6-card-body { flex:1; min-width:0; }
.k6-card-label { font-size:11px; color:#6b7280; text-transform:uppercase; letter-spacing:0.05em; }
.k6-card-value { font-size:22px; font-weight:700; color:#f1f5f9; margin:2px 0; }
.k6-card-value.k6-ok { color:#22c55e; }
.k6-card-value.k6-warn { color:#f59e0b; }
.k6-card-value.k6-danger { color:#ef4444; }
.k6-card-sub { font-size:11px; color:#64748b; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.k6-progress { height:4px; background:#1e293b; border-radius:2px; margin-top:6px; overflow:hidden; }
.k6-progress-bar { height:100%; border-radius:2px; transition:width 0.5s ease; }

/* Charts */
.k6-charts-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px; }
@media(max-width:768px){ .k6-charts-row{grid-template-columns:1fr;} }
.k6-chart-panel { background:#161b27; border:1px solid #1e293b; border-radius:10px; padding:14px; }
.k6-chart-title { font-size:12px; color:#6b7280; font-weight:600; margin-bottom:10px; }

/* Active test banner */
.k6-active-banner { background:#1a0a0a; border:1px solid #ef444444; border-radius:10px; padding:16px; margin-bottom:20px; }
.k6-active-header { display:flex; align-items:center; margin-bottom:10px; }

/* Target section in builder */
.k6-target-section { background:#0d1117; border:1px solid #1e293b; border-radius:8px; padding:12px 14px; margin-bottom:12px; }
.k6-live-cards { display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin:10px 0; }
@media(max-width:768px){ .k6-live-cards{grid-template-columns:repeat(3,1fr);} }
.k6-live-card { background:#1e0d0d; border:1px solid #2d1b1b; border-radius:8px; padding:10px; text-align:center; }
.k6-lv-label { display:block; font-size:10px; color:#6b7280; text-transform:uppercase; }
.k6-lv-val { display:block; font-size:20px; font-weight:700; color:#22d3ee; margin-top:4px; }
.k6-lv-val.k6-err { color:#ef4444; }

/* Tables */
.k6-table { color:#e2e8f0; border-color:#1e293b !important; }
.k6-table thead th { background:#161b27; color:#6b7280; font-size:11px; text-transform:uppercase; border-color:#1e293b !important; }
.k6-table tbody tr:hover { background:#161b27; }
.k6-table td, .k6-table th { border-color:#1e293b !important; }

/* Status badges */
.k6-status { padding:2px 8px; border-radius:10px; font-size:11px; font-weight:600; }
.k6-status-running { background:#064e3b; color:#34d399; }
.k6-status-completed { background:#1e3a5f; color:#60a5fa; }
.k6-status-failed { background:#450a0a; color:#f87171; }
.k6-status-stopped { background:#292524; color:#a8a29e; }
.k6-status-draft { background:#1c1917; color:#78716c; }
.k6-status-ready { background:#14532d; color:#86efac; }
.k6-badge-scenario { padding:2px 8px; border-radius:10px; font-size:11px; }
.k6-scenario-smoke  { background:#064e3b22; color:#34d399; border:1px solid #34d39944; }
.k6-scenario-load   { background:#1e3a5f22; color:#60a5fa; border:1px solid #60a5fa44; }
.k6-scenario-stress { background:#7c2d1222; color:#fb923c; border:1px solid #fb923c44; }
.k6-scenario-spike  { background:#4c1d9522; color:#c084fc; border:1px solid #c084fc44; }
.k6-scenario-soak   { background:#14532d22; color:#86efac; border:1px solid #86efac44; }

/* Builder */
.k6-builder-form { max-width:100%; }
.k6-form-row { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:12px; }
.k6-form-group { display:flex; flex-direction:column; gap:4px; flex:1; min-width:140px; }
.k6-form-group.k6-sm { flex:0 0 100px; }
.k6-form-group.k6-lg { flex:2; }
.k6-form-group label { font-size:11px; color:#6b7280; font-weight:600; }
.k6-form-group .form-control { background:#161b27; border:1px solid #374151; color:#e2e8f0; border-radius:6px; }
.k6-form-group .form-control:focus { border-color:#3b82f6; outline:none; box-shadow:0 0 0 2px rgba(59,130,246,0.2); }
.k6-form-group textarea.form-control { font-size:12px; font-family:monospace; resize:vertical; }
.k6-ep-row { background:#161b27; border:1px solid #1e293b; border-radius:10px; padding:14px; margin-bottom:12px; }
.k6-ep-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
.k6-ep-fields { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:8px; }
.k6-ep-advanced { }
`;
    document.head.appendChild(style);
  }
}
