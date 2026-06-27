(()=>{var x=Object.defineProperty,y=Object.defineProperties;var _=Object.getOwnPropertyDescriptors;var u=Object.getOwnPropertySymbols;var w=Object.prototype.hasOwnProperty,C=Object.prototype.propertyIsEnumerable;var m=(r,t,a)=>t in r?x(r,t,{enumerable:!0,configurable:!0,writable:!0,value:a}):r[t]=a,c=(r,t)=>{for(var a in t||(t={}))w.call(t,a)&&m(r,a,t[a]);if(u)for(var a of u(t))C.call(t,a)&&m(r,a,t[a]);return r},h=(r,t)=>y(r,_(t));frappe.pages["k6-monitor"].on_load=function(r){frappe.ui.make_app_page({parent:r,title:"K6 Performance Monitor",single_column:!0});let t=new b(r);r.k6_page=t};frappe.pages["k6-monitor"].on_show=function(r){r.k6_page&&r.k6_page.on_show()};frappe.pages["k6-monitor"].on_hide=function(r){r.k6_page&&r.k6_page.on_hide()};var b=class{constructor(t){this.wrapper=t,this.$main=$(t).find(".page-content"),this.charts={},this.sysHistory={labels:[],cpu:[],mem:[],netSent:[],netRecv:[]},this.liveHistory={labels:[],rps:[],avg:[]},this.activeRun=null,this.refreshInterval=5e3,this._timers=[],this._endpointCount=0,this._injectStyles(),this._render(),this._bindEvents(),this._startPolling(),this._loadChartJs(()=>this._initCharts())}on_show(){this._startPolling()}on_hide(){this._stopPolling()}_startPolling(){this._stopPolling(),this._fetchSystemMetrics(),this._fetchConfigs(),this._fetchHistory(),this._checkActiveRuns();let t=setInterval(()=>this._fetchSystemMetrics(),this.refreshInterval),a=setInterval(()=>this._checkActiveRuns(),3e3),e=setInterval(()=>{this._fetchConfigs(),this._fetchHistory()},15e3);this._timers=[t,a,e]}_stopPolling(){this._timers.forEach(clearInterval),this._timers=[]}_render(){let t=$(this.wrapper).find(".layout-main-section");t.length?t.html(this._getHTML()):$(this.wrapper).append(`<div class="layout-main-section">${this._getHTML()}</div>`),this._addEndpointRow()}_getHTML(){return`<div class="k6-monitor-wrap">
  <div class="k6-topbar">
    <div class="k6-brand">
      <span class="k6-logo">\u26A1</span>
      <span class="k6-title">K6 Performance Monitor</span>
      <span class="k6-badge" id="k6-live-badge">\u25CF LIVE</span>
    </div>
    <div class="k6-tabs">
      <button class="k6-tab active" data-tab="dashboard">\u{1F4CA} Dashboard</button>
      <button class="k6-tab" data-tab="loadtest">\u{1F680} Load Tests</button>
      <button class="k6-tab" data-tab="builder">\u{1F527} Test Builder</button>
      <button class="k6-tab" data-tab="history">\u{1F4CB} History</button>
    </div>
    <div class="k6-topbar-right">
      <span class="k6-refresh-info" id="k6-last-refresh">\u2013</span>
      <button class="btn btn-xs btn-default" id="k6-refresh-btn" title="Refresh now">\u21BA</button>
    </div>
  </div>

  <div class="k6-tab-content active" id="tab-dashboard">
    <div class="k6-section-label">\u{1F5A5} Infrastructure Health</div>
    <div class="k6-cards-row" id="sys-cards">
      <div class="k6-card"><div class="k6-card-icon">\u2699\uFE0F</div><div class="k6-card-body"><div class="k6-card-label">CPU Usage</div><div class="k6-card-value" id="val-cpu">\u2013</div><div class="k6-progress"><div class="k6-progress-bar" id="bar-cpu"></div></div></div></div>
      <div class="k6-card"><div class="k6-card-icon">\u{1F9E0}</div><div class="k6-card-body"><div class="k6-card-label">Memory</div><div class="k6-card-value" id="val-mem">\u2013</div><div class="k6-card-sub" id="sub-mem">\u2013</div><div class="k6-progress"><div class="k6-progress-bar" id="bar-mem"></div></div></div></div>
      <div class="k6-card"><div class="k6-card-icon">\u{1F4BE}</div><div class="k6-card-body"><div class="k6-card-label">Disk</div><div class="k6-card-value" id="val-disk">\u2013</div><div class="k6-card-sub" id="sub-disk">\u2013</div><div class="k6-progress"><div class="k6-progress-bar" id="bar-disk"></div></div></div></div>
      <div class="k6-card"><div class="k6-card-icon">\u26A1</div><div class="k6-card-body"><div class="k6-card-label">Redis</div><div class="k6-card-value" id="val-redis">\u2013</div><div class="k6-card-sub" id="sub-redis">\u2013</div></div></div>
      <div class="k6-card"><div class="k6-card-icon">\u{1F5C4}\uFE0F</div><div class="k6-card-body"><div class="k6-card-label">Database</div><div class="k6-card-value" id="val-db">\u2013</div><div class="k6-card-sub" id="sub-db">\u2013</div></div></div>
      <div class="k6-card"><div class="k6-card-icon">\u{1F477}</div><div class="k6-card-body"><div class="k6-card-label">Workers</div><div class="k6-card-value" id="val-workers">\u2013</div><div class="k6-card-sub" id="sub-workers">\u2013</div></div></div>
    </div>
    <div class="k6-charts-row">
      <div class="k6-chart-panel"><div class="k6-chart-title">CPU &amp; Memory History</div><canvas id="chart-sysmetrics" height="90"></canvas></div>
      <div class="k6-chart-panel"><div class="k6-chart-title">Network I/O (MB)</div><canvas id="chart-network" height="90"></canvas></div>
    </div>
    <div id="k6-active-banner" class="k6-active-banner" style="display:none">
      <div class="k6-section-label">\u{1F534} Active Load Test</div>
      <div class="k6-live-cards">
        <div class="k6-live-card"><span class="k6-lv-label">RPS</span><span class="k6-lv-val" id="lv-rps">\u2013</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">Avg ms</span><span class="k6-lv-val" id="lv-avg">\u2013</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">P95 ms</span><span class="k6-lv-val" id="lv-p95">\u2013</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">Requests</span><span class="k6-lv-val" id="lv-reqs">\u2013</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">Errors</span><span class="k6-lv-val k6-err" id="lv-errs">\u2013</span></div>
        <div class="k6-live-card"><span class="k6-lv-label">VUs</span><span class="k6-lv-val" id="lv-vus">\u2013</span></div>
      </div>
      <div class="k6-chart-panel" style="margin-top:10px"><div class="k6-chart-title">Live: Requests &amp; Response Time</div><canvas id="chart-live" height="80"></canvas></div>
      <div style="margin-top:8px;text-align:right"><button class="btn btn-sm btn-danger" id="btn-stop-active">\u23F9 Stop Test</button></div>
    </div>
  </div>

  <div class="k6-tab-content" id="tab-loadtest">
    <div class="k6-section-label">\u{1F680} Saved Load Test Configs</div>
    <div style="margin-bottom:10px"><button class="btn btn-sm btn-primary" id="btn-goto-builder">+ New Test Config</button></div>
    <table class="table table-bordered k6-table">
      <thead><tr><th>Test Name</th><th>Scenario</th><th>VUs</th><th>Duration</th><th>Status</th><th>Last Run</th><th>Actions</th></tr></thead>
      <tbody id="configs-tbody"><tr><td colspan="7" class="text-center text-muted">Loading...</td></tr></tbody>
    </table>
  </div>

  <div class="k6-tab-content" id="tab-builder">
    <div class="k6-section-label">\u{1F527} Build New Load Test</div>
    <div class="k6-builder-form">
      <div class="k6-form-row">
        <div class="k6-form-group"><label>Test Name *</label><input type="text" class="form-control" id="b-test-name" placeholder="My API Load Test"></div>
        <div class="k6-form-group"><label>Scenario</label>
          <select class="form-control" id="b-scenario">
            <option value="smoke">Smoke \u2013 2 VUs, 1 min</option>
            <option value="load" selected>Load \u2013 normal traffic</option>
            <option value="stress">Stress \u2013 find breaking point</option>
            <option value="spike">Spike \u2013 sudden burst</option>
            <option value="soak">Soak \u2013 long endurance</option>
          </select>
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
        <button class="btn btn-primary" id="btn-save-config">\u{1F4BE} Save Config</button>
        <button class="btn btn-success" id="btn-save-run">\u{1F4BE} Save &amp; Run Now</button>
        <button class="btn btn-default" id="btn-clear-builder">\u2715 Clear</button>
      </div>
      <div id="builder-msg" style="margin-top:10px"></div>
    </div>
  </div>

  <div class="k6-tab-content" id="tab-history">
    <div class="k6-section-label">\u{1F4CB} Test Run History</div>
    <table class="table table-bordered k6-table">
      <thead><tr><th>Run</th><th>Config</th><th>Scenario</th><th>Status</th><th>Started</th><th>Requests</th><th>Errors</th><th>RPS</th><th>Avg ms</th><th>P95 ms</th></tr></thead>
      <tbody id="history-tbody"><tr><td colspan="10" class="text-center text-muted">Loading...</td></tr></tbody>
    </table>
  </div>
</div>`}_initCharts(){if(!window.Chart)return;let t={responsive:!0,animation:!1,plugins:{legend:{display:!0,labels:{color:"#aaa",font:{size:11}}}},scales:{x:{ticks:{color:"#aaa",maxTicksLimit:8},grid:{color:"#2a2a2a"}},y:{ticks:{color:"#aaa"},grid:{color:"#2a2a2a"}}}},a=document.getElementById("chart-sysmetrics");a&&(this.charts.sys=new Chart(a,{type:"line",data:{labels:[],datasets:[{label:"CPU %",data:[],borderColor:"#f97316",backgroundColor:"rgba(249,115,22,0.12)",tension:.3,fill:!0},{label:"Memory %",data:[],borderColor:"#3b82f6",backgroundColor:"rgba(59,130,246,0.12)",tension:.3,fill:!0}]},options:c({},t)}));let e=document.getElementById("chart-network");e&&(this.charts.net=new Chart(e,{type:"line",data:{labels:[],datasets:[{label:"Sent MB",data:[],borderColor:"#10b981",backgroundColor:"rgba(16,185,129,0.12)",tension:.3},{label:"Recv MB",data:[],borderColor:"#a855f7",backgroundColor:"rgba(168,85,247,0.12)",tension:.3}]},options:c({},t)}));let s=document.getElementById("chart-live");s&&(this.charts.live=new Chart(s,{type:"line",data:{labels:[],datasets:[{label:"RPS",data:[],borderColor:"#22d3ee",yAxisID:"y",tension:.3},{label:"Avg ms",data:[],borderColor:"#fb923c",yAxisID:"y1",tension:.3}]},options:h(c({},t),{scales:{x:{ticks:{color:"#aaa",maxTicksLimit:10},grid:{color:"#2a2a2a"}},y:{ticks:{color:"#22d3ee"},grid:{color:"#2a2a2a"},position:"left"},y1:{ticks:{color:"#fb923c"},grid:{drawOnChartArea:!1},position:"right"}}})}))}_fetchSystemMetrics(){frappe.call({method:"frappe_k6.api.system_metrics.get_all_metrics",callback:t=>{t.message&&this._renderSystemMetrics(t.message),$("#k6-last-refresh").text("Last: "+new Date().toLocaleTimeString())}})}_renderSystemMetrics(t){let a=new Date().toLocaleTimeString(),s=(t.cpu||{}).percent||0;this._setCard("val-cpu",s.toFixed(1)+"%",s>85?"danger":s>60?"warn":"ok"),this._setBar("bar-cpu",s,s>85?"#ef4444":s>60?"#f59e0b":"#22c55e");let l=t.memory||{},i=l.percent||0;this._setCard("val-mem",i.toFixed(1)+"%"),$("#sub-mem").text(`${l.used_gb||0} / ${l.total_gb||0} GB`),this._setBar("bar-mem",i,i>85?"#ef4444":"#3b82f6");let d=t.disk||{};this._setCard("val-disk",(d.percent||0).toFixed(1)+"%"),$("#sub-disk").text(`${d.used_gb||0} / ${d.total_gb||0} GB`),this._setBar("bar-disk",d.percent||0,"#8b5cf6");let o=t.redis||{};o.status==="connected"?(this._setCard("val-redis",`${o.memory_mb||0} MB`,"ok"),$("#sub-redis").text(`Hit: ${o.hit_ratio||0}%  Clients: ${o.connected_clients||0}`)):(this._setCard("val-redis","Error","danger"),$("#sub-redis").text(o.message||"disconnected"));let n=t.database||{};n.status==="connected"?(this._setCard("val-db",`${n.connections||0} conn`),$("#sub-db").text(`Slow: ${n.slow_queries||0}  Max: ${n.max_connections||"?"}`)):this._setCard("val-db","Error","danger");let k=t.gunicorn||{},f=t.workers||{},p=t.queues||{};this._setCard("val-workers",`${k.count||0} web / ${f.count||0} bg`),$("#sub-workers").text(`Q: ${p.default||0} / ${p.long||0} / ${p.short||0}`),this.sysHistory.labels.push(a),this.sysHistory.cpu.push(s),this.sysHistory.mem.push(i),this.sysHistory.labels.length>30&&["labels","cpu","mem"].forEach(g=>this.sysHistory[g].shift()),this.charts.sys&&(this.charts.sys.data.labels=[...this.sysHistory.labels],this.charts.sys.data.datasets[0].data=[...this.sysHistory.cpu],this.charts.sys.data.datasets[1].data=[...this.sysHistory.mem],this.charts.sys.update("none"));let v=t.network||{};this.sysHistory.netSent.push(v.bytes_sent_mb||0),this.sysHistory.netRecv.push(v.bytes_recv_mb||0),this.sysHistory.netSent.length>30&&(this.sysHistory.netSent.shift(),this.sysHistory.netRecv.shift()),this.charts.net&&(this.charts.net.data.labels=[...this.sysHistory.labels],this.charts.net.data.datasets[0].data=[...this.sysHistory.netSent],this.charts.net.data.datasets[1].data=[...this.sysHistory.netRecv],this.charts.net.update("none"))}_checkActiveRuns(){frappe.call({method:"frappe_k6.api.load_test.get_active_runs",callback:t=>{let a=t.message||[];a.length>0?(this.activeRun=a[0].name,$("#k6-active-banner").show(),this._fetchLiveMetrics(this.activeRun)):(this.activeRun=null,$("#k6-active-banner").hide())}})}_fetchLiveMetrics(t){frappe.call({method:"frappe_k6.api.load_test.get_test_status",args:{run_name:t},callback:a=>{if(!a.message)return;let e=a.message.metrics||{},s=e.http_req_duration||{},l=e.http_reqs||{},i=e.http_req_failed||{},d=e.vus||{};$("#lv-rps").text(e.rps||0),$("#lv-avg").text(s.avg||0),$("#lv-p95").text(s.p95||0),$("#lv-reqs").text(l.count||0),$("#lv-errs").text((i.count||0)+" ("+(e.error_rate||0)+"%)"),$("#lv-vus").text(d.current||0);let o=e.timeline||[];o.length&&this.charts.live&&(this.charts.live.data.labels=o.map(n=>n.time.slice(11,19)),this.charts.live.data.datasets[0].data=o.map(n=>n.rps),this.charts.live.data.datasets[1].data=o.map(n=>n.avg_ms),this.charts.live.update("none"))}})}_fetchConfigs(){frappe.call({method:"frappe_k6.api.load_test.get_configs",callback:t=>{let a=t.message||[],e=$("#configs-tbody");if(!a.length){e.html('<tr><td colspan="7" class="text-center text-muted">No configs yet. Create one in the Test Builder tab.</td></tr>');return}e.html(a.map(s=>`
          <tr>
            <td><b>${s.test_name||s.name}</b></td>
            <td><span class="k6-badge-scenario k6-scenario-${s.scenario_type}">${s.scenario_type}</span></td>
            <td>${s.virtual_users}</td>
            <td>${s.duration}</td>
            <td><span class="k6-status k6-status-${(s.status||"").toLowerCase()}">${s.status||"Draft"}</span></td>
            <td>${s.last_run?`<a href="/app/load-test-run/${s.last_run}">${s.last_run}</a>`:"\u2013"}</td>
            <td>
              <button class="btn btn-xs btn-success btn-run-config" data-name="${s.name}" ${s.status==="Running"?"disabled":""}>\u25B6 Run</button>
              <button class="btn btn-xs btn-default btn-edit-config" data-name="${s.name}">\u270F</button>
              <a href="/app/load-test-config/${s.name}" class="btn btn-xs btn-default" target="_blank">\u2197</a>
            </td>
          </tr>`).join(""))}})}_fetchHistory(){frappe.call({method:"frappe_k6.api.load_test.get_run_history",args:{limit:20},callback:t=>{let a=t.message||[],e=$("#history-tbody");if(!a.length){e.html('<tr><td colspan="10" class="text-center text-muted">No runs yet.</td></tr>');return}e.html(a.map(s=>`
          <tr>
            <td><a href="/app/load-test-run/${s.name}" target="_blank">${s.name}</a></td>
            <td>${s.config}</td>
            <td><span class="k6-badge-scenario k6-scenario-${s.scenario_type}">${s.scenario_type||"\u2013"}</span></td>
            <td><span class="k6-status k6-status-${(s.status||"").toLowerCase()}">${s.status}</span></td>
            <td>${s.started_at?s.started_at.slice(0,16):"\u2013"}</td>
            <td>${s.total_requests||0}</td>
            <td class="${s.failed_requests>0?"text-danger":""}">${s.failed_requests||0}</td>
            <td>${s.requests_per_sec||0}</td>
            <td>${s.avg_duration_ms||0}</td>
            <td>${s.p95_duration_ms||0}</td>
          </tr>`).join(""))}})}_bindEvents(){let t=$(this.wrapper);t.on("click",".k6-tab",a=>{let e=$(a.currentTarget).data("tab");t.find(".k6-tab").removeClass("active"),$(a.currentTarget).addClass("active"),t.find(".k6-tab-content").removeClass("active"),t.find(`#tab-${e}`).addClass("active"),e==="loadtest"&&this._fetchConfigs(),e==="history"&&this._fetchHistory()}),t.on("click","#k6-refresh-btn",()=>{this._fetchSystemMetrics(),this._checkActiveRuns()}),t.on("click","#btn-add-endpoint",()=>this._addEndpointRow()),t.on("click",".btn-remove-ep",a=>{$(a.currentTarget).closest(".k6-ep-row").remove()}),t.on("click","#btn-save-config",()=>this._saveConfig(!1)),t.on("click","#btn-save-run",()=>this._saveConfig(!0)),t.on("click","#btn-clear-builder",()=>{t.find("#b-test-name").val(""),t.find("#endpoints-list").empty(),this._addEndpointRow(),$("#builder-msg").html("")}),t.on("click","#btn-goto-builder",()=>{t.find(".k6-tab[data-tab='builder']").click()}),t.on("click",".btn-run-config",a=>{let e=$(a.currentTarget).data("name");this._runConfig(e)}),t.on("click","#btn-stop-active",()=>{!this.activeRun||frappe.confirm(`Stop test ${this.activeRun}?`,()=>{frappe.call({method:"frappe_k6.api.load_test.stop_load_test",args:{run_name:this.activeRun},callback:()=>{frappe.show_alert({message:"Test stopped.",indicator:"orange"}),this.activeRun=null,$("#k6-active-banner").hide(),this._fetchConfigs()}})})})}_addEndpointRow(){let t=++this._endpointCount,a=`
      <div class="k6-ep-row" data-ep="${t}">
        <div class="k6-ep-header">
          <b>Endpoint #${t}</b>
          <button class="btn btn-xs btn-danger btn-remove-ep">\u2715 Remove</button>
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
      </div>`;$("#endpoints-list").append(a)}_saveConfig(t){let a=$(this.wrapper),e=a.find("#b-test-name").val().trim();if(!e){$("#builder-msg").html('<div class="alert alert-danger">Test Name is required.</div>');return}let s=[];if(a.find(".k6-ep-row").each(function(){let i=$(this),d=i.find(".ep-name").val().trim(),o=i.find(".ep-url").val().trim();!d||!o||s.push({api_name:d,http_method:i.find(".ep-method").val(),endpoint_url:o,expected_status:parseInt(i.find(".ep-status").val())||200,auth_type:i.find(".ep-auth-type").val(),auth_value:i.find(".ep-auth-val").val(),headers:i.find(".ep-headers").val(),query_params:i.find(".ep-params").val(),payload:i.find(".ep-payload").val(),weight:parseInt(i.find(".ep-weight").val())||100})}),!s.length){$("#builder-msg").html('<div class="alert alert-danger">Add at least one endpoint.</div>');return}let l={doctype:"Load Test Config",test_name:e,scenario_type:a.find("#b-scenario").val(),virtual_users:parseInt(a.find("#b-vus").val()),duration:a.find("#b-duration").val(),ramp_up_time:a.find("#b-ramp-up").val(),ramp_down_time:a.find("#b-ramp-down").val(),max_vus:parseInt(a.find("#b-max-vus").val()),think_time:parseFloat(a.find("#b-think").val()),endpoints:s};$("#builder-msg").html('<div class="alert alert-info">Saving...</div>'),frappe.call({method:"frappe.client.insert",args:{doc:l},callback:i=>{i.message&&($("#builder-msg").html(`<div class="alert alert-success">\u2705 Saved: <b>${i.message.name}</b></div>`),t&&setTimeout(()=>this._runConfig(i.message.name),500),this._fetchConfigs())}})}_runConfig(t){frappe.show_alert({message:`Starting test: ${t}\u2026`,indicator:"blue"}),frappe.call({method:"frappe_k6.api.load_test.start_load_test",args:{config_name:t},callback:a=>{a.message&&(frappe.show_alert({message:`\u2705 Test started! Run: ${a.message.run_name}`,indicator:"green"}),this.activeRun=a.message.run_name,$("#k6-active-banner").show(),$(".k6-tab[data-tab='dashboard']").click(),this._fetchConfigs())}})}_setCard(t,a,e){let s=$("#"+t);s.text(a),s.removeClass("k6-ok k6-warn k6-danger"),e&&s.addClass("k6-"+e)}_setBar(t,a,e){let s=Math.min(100,Math.max(0,a));$(`#${t}`).css({width:s+"%",background:e})}_loadChartJs(t){if(window.Chart){t();return}let a=document.createElement("script");a.src="/assets/frappe_k6/js/chart.umd.min.js",a.onload=t,a.onerror=()=>{console.warn("frappe_k6: Chart.js could not load.")},document.head.appendChild(a)}_injectStyles(){if(document.getElementById("k6-monitor-styles"))return;let t=document.createElement("style");t.id="k6-monitor-styles",t.textContent=`
/* \u2500\u2500 K6 Monitor Styles \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 */
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
`,document.head.appendChild(t)}};})();
//# sourceMappingURL=k6-monitor.bundle.4GU6M25K.js.map
