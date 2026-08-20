// ==UserScript==
// @name         Bilibili yt-dlp Downloader
// @namespace    https://github.com/panxue/bilibili-download
// @version      1.3.1
// @description  Bilibili video download: a floating panel that submits jobs to a local FastAPI+yt-dlp backend, with realtime progress and interrupted-download resume
// @match        https://www.bilibili.com/*
// @run-at       document-idle
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_xmlhttpRequest
// @grant        GM_cookie
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
  "use strict";

  console.log("[bili-dl] script loaded @ " + location.host);

  var CFG_KEY = "biliDlCfg_v1";

  // ------------------------------------------------------------ config ----------
  function getCfg() {
    return GM_getValue(CFG_KEY, {}) || {};
  }
  function setCfg(patch) {
    var next = Object.assign({}, getCfg(), patch);
    GM_setValue(CFG_KEY, next);
    return next;
  }
  function backendHost() {
    return (getCfg().backendUrl || "http://127.0.0.1:8000").replace(/\/+$/, "");
  }

  // ------------------------------------------------------ page metadata ----------
  // the userscript sandbox cannot read the page JS globals; access the page context via unsafeWindow
  function initialState() {
    return unsafeWindow.__INITIAL_STATE__ || null;
  }

  function pageMeta() {
    var st = initialState();
    if (st) {
      var vd = st.videoData || st.videoInfo;
      if (vd) {
        var pages = (vd.pages || []).map(function (p, i) {
          return {
            page: p.page || i + 1,
            cid: p.cid || 0,
            title: p.part || vd.title || ("P" + (i + 1)),
          };
        });
        return {
          bvid: vd.bvid || "",
          title: vd.title || "",
          uploader: (vd.owner && vd.owner.name) || "",
          pages: pages,
        };
      }
    }
    return bangumiMeta();
  }

  // Modern bangumi pages (play-v2 / laputa SSR) no longer expose __INITIAL_STATE__; the
  // currently-playing episode lives in playurlSSRData and the season name in <meta og:title>.
  function bangumiMeta() {
    var path = location.pathname;
    var m = path.match(/\/bangumi\/play\/(ss|ep)([0-9]+)$/);
    if (!m) return null;
    var kind = m[1], id = m[2];
    var arc = null, epInfo = null, seasonTitle = "";
    var d = unsafeWindow.playurlSSRData;
    if (d && d.data && d.data.result) {
      arc = d.data.result.arc || null;
      epInfo = (d.data.result.supplement && d.data.result.supplement.ogv_episode_info) || null;
    }
    var og = document.querySelector('meta[property="og:title"]');
    if (og && og.content) seasonTitle = og.content.trim();
    var title = seasonTitle || document.title.split("-")[0].trim() || ("Pgc " + id);
    if (kind === "ep") {
      return {
        bvid: (arc && arc.bvid) || ("ep" + id),
        title: title,
        uploader: "",
        pages: [{ page: 1, cid: (arc && arc.cid) || 0, title: epTitleLabel(epInfo) }],
      };
    }
    // season page: the episode list is resolved by the backend probe, not present in the DOM
    return { bvid: "ss" + id, title: title, uploader: "", pages: [], season: true, currentEp: epNumber(epInfo) };
  }

  function epNumber(epInfo) {
    var n = parseInt(epInfo && epInfo.index_title, 10);
    return (n >= 1 ? n : 1);
  }

  function epTitleLabel(epInfo) {
    if (!epInfo) return "";
    var n = epInfo.index_title || "";
    var t = epInfo.long_title || "";
    return [n, t].filter(Boolean).join(" · ");
  }

  function currentPage() {
    var m = location.search.match(/[?&]p=(\d+)/);
    return m ? parseInt(m[1], 10) : 1;
  }

  // only take the three keys to build the Cookie string; returns "" when not logged in
  // SESSDATA is HttpOnly, document.cookie can't read it; must go through GM_cookie
  function docCookies(want) {
    var got = [];
    document.cookie.split(";").forEach(function (part) {
      var kv = part.trim().match(/^([^=]+)=(.*)$/);
      if (kv && want.indexOf(kv[1]) >= 0) got.push(kv[1] + "=" + kv[2]);
    });
    return got.join("; ");
  }
  var cookieFound = {};
  function loginCookie() {
    var want = ["SESSDATA", "DedeUserID", "bili_jct"];
    return new Promise(function (resolve) {
      function finish(list) {
        cookieFound = {};
        var got = [];
        want.forEach(function (n) {
          var hit = null;
          (list || []).forEach(function (c) {
            if (c.name === n && c.value) hit = hit || c;
          });
          if (hit) { cookieFound[n] = true; got.push(n + "=" + hit.value); }
        });
        console.log("[bili-dl] GM_cookie hits:", cookieFound, "of", (list || []).length, "total");
        resolve(got.join("; "));
      }
      if (typeof GM_cookie === "undefined") { resolve(docCookies(want)); return; }
      try {
        GM_cookie.list({ url: location.href }, function (cookies, error) {
          console.log("[bili-dl] GM_cookie error:", error);
          if (error || !cookies) { resolve(docCookies(want)); return; }
          finish(cookies);
        });
      } catch (e) {
        console.log("[bili-dl] GM_cookie call error:", e);
        resolve(docCookies(want));
      }
    });
  }

  // ------------------------------------------------------------ utilities ----------
  function $(sel, root) {
    return (root || document).querySelector(sel);
  }
  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) {
      if (k === "class") n.className = attrs[k];
      else if (k === "html") n.innerHTML = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // --------------------------------------------------- backend HTTP wrapper ----------
  function api(path, opts) {
    opts = opts || {};
    return new Promise(function (resolve, reject) {
      var headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
      var token = (getCfg().authToken || "").trim();
      if (token) headers["X-Auth-Token"] = token;
      GM_xmlhttpRequest({
        method: opts.method || "GET",
        url: backendHost() + path,
        headers: headers,
        data: opts.data !== undefined ? JSON.stringify(opts.data) : undefined,
        timeout: opts.timeout || 30000,
        onload: function (res) {
          var j = null;
          try {
            j = JSON.parse(res.responseText);
          } catch (e) {
            j = { code: -99, msg: "response is not JSON" };
          }
          resolve(j);
        },
        onerror: function () { reject(new Error("backend unreachable")); },
        ontimeout: function () { reject(new Error("request timeout")); },
      });
    });
  }

  function fetchInfo(url, cookies) {
    return api("/api/info", { method: "POST", data: { url: url, cookies: cookies } });
  }
  function postDownload(payload) {
    return api("/api/download", { method: "POST", data: payload });
  }
  function listJobs() {
    return api("/api/jobs?limit=50&status=all");
  }
  function getJob(id) {
    return api("/api/jobs/" + id);
  }
  function jobOp(id, op, cookies) {
    return api("/api/jobs/" + id + "/" + op, {
      method: "POST",
      data: op === "resume_after_interrupt" ? { cookies: cookies || "" } : {},
    });
  }
  function deleteJob(id) {
    return api("/api/jobs/" + id, { method: "DELETE" });
  }
  function fetchConfig() {
    return api("/api/config");
  }

  // ------------------------------------------------------ floating panel shell ----------
  var shadow = null;
  var hostEl = null;
  var currentTab = "new";
  var jobsCache = {};
  var watchers = [];
  var expandedJobs = {};

  function ensureUI() {
    if (hostEl) return;
    hostEl = el("div", { "class": "bdlp-root" });
    shadow = hostEl.attachShadow({ mode: "open" });
    shadow.innerHTML =
      "<style>" + CSS + "</style>" +
      '<div class="bdlp-float">' +
      '  <div class="bdlp-panel">' +
      '    <div class="bdlp-tabs">' +
      '      <div class="bdlp-tab on" data-tab="build">New Download</div>' +
      '      <div class="bdlp-tab" data-tab="tasks">Tasks</div>' +
      '      <div class="bdlp-tab" data-tab="set">Settings</div>' +
      "    </div>" +
      '    <div class="bdlp-body"><div class="bdlp-empty">Loading…</div></div>' +
      "  </div>" +
      '  <div class="bdlp-pill"><span class="bdlp-dot"></span><span>Download</span></div>' +
      "</div>";
    document.documentElement.appendChild(hostEl);

    $(".bdlp-pill", shadow).addEventListener("click", function () {
      var panel = $(".bdlp-panel", shadow);
      var open = panel.classList.toggle("open");
      if (open) renderTab("build");
    });
    shadow.addEventListener("click", onShadowClick);
  }

  var CSS =
    ":host{all:initial}" +
    ".bdlp-float{position:fixed;right:18px;bottom:18px;z-index:2147483647;" +
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif}" +
    ".bdlp-pill{display:flex;align-items:center;gap:8px;background:#1c2333;color:#fff;padding:9px 14px;" +
    "border-radius:999px;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.35);font-size:13px;" +
    "user-select:none;border:1px solid rgba(255,255,255,.12)}" +
    ".bdlp-dot{width:8px;height:8px;border-radius:50%;background:#f0a94c}" +
    ".bdlp-dot.ok{background:#3fb950}.bdlp-dot.bad{background:#f85149}" +
    ".bdlp-panel{position:fixed;right:18px;bottom:56px;width:320px;max-height:620px;display:none;" +
    "flex-direction:column;background:#141926;color:#e6e9ef;border:1px solid #2a3245;border-radius:12px;" +
    "box-shadow:0 12px 40px rgba(0,0,0,.5);overflow:hidden}" +
    ".bdlp-panel.open{display:flex}" +
    ".bdlp-tabs{display:flex;border-bottom:1px solid #232b3e;background:#11141d}" +
    ".bdlp-tab{flex:1;padding:10px 0;text-align:center;font-size:13px;color:#98a2b5;cursor:pointer}" +
    ".bdlp-tab.on{color:#fff;border-bottom:2px solid #4c9fff}" +
    ".bdlp-body{flex:1;overflow-y:auto;padding:12px;font-size:13px}" +
    ".bdlp-warn{background:#1d2434;border:1px solid #3a4a6a;color:#e6c07a;border-radius:8px;" +
    "font-size:11px;padding:8px 10px;margin-bottom:10px}" +
    ".bdlp-warn.err{border-color:#5a2a2a;color:#f85149}" +
    ".bdlp-meta{font-size:12px;color:#9aa6bd;margin-bottom:8px;word-break:break-all}" +
    ".bdlp-meta b{color:#eef1f6;font-size:13px;display:block;margin-bottom:2px}" +
    ".bdlp-lbl{font-size:11px;color:#8a93a6;display:block;margin:10px 0 4px}" +
    ".bdlp-badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px}" +
    "select,input[type=url],input[type=password],input[type=text]{box-sizing:border-box;width:100%;" +
    "background:#0f1420;border:1px solid #2c3647;color:#e6e9ef;border-radius:8px;padding:8px;font-size:13px}" +
    ".bdlp-check{display:flex;gap:6px;align-items:center;font-size:12px;color:#c3cad6;margin:5px 0;cursor:pointer}" +
    ".bdlp-check input{margin:0}" +
    ".bdlp-page-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}" +
    ".bdlp-btn{box-sizing:border-box;width:100%;margin-top:12px;padding:10px;background:#3f9cff;border:0;" +
    "color:#fff;border-radius:10px;font-size:14px;cursor:pointer}" +
    ".bdlp-btn:disabled{background:#3a4258;color:#8b94a8;cursor:not-allowed}" +
    ".bdlp-opt{display:block;background:#0f1420;border:1px solid #2c3647;color:#c3cad6;border-radius:8px;" +
    "padding:6px 10px;font-size:12px;cursor:pointer}" +
    ".bdlp-opt.sel{background:#1d2c44;border-color:#4c9fff;color:#fff}" +
    ".bdlp-opt:disabled{opacity:.4;cursor:not-allowed}" +
    ".bdlp-job{background:#151d2d;border:1px solid #263148;border-radius:10px;padding:10px;margin-bottom:8px}" +
    ".bdlp-head{display:flex;align-items:flex-start;gap:6px;cursor:pointer}" +
    ".bdlp-head h4{margin:0;flex:1;min-width:0}" +
    ".bdlp-job h4{font-size:12px;font-weight:600;color:#d9dee8;overflow:hidden;" +
    "text-overflow:ellipsis;white-space:nowrap}" +
    ".bdlp-exp{background:none;border:0;padding:0;color:#7c8797;font-size:11px;cursor:pointer;" +
    "flex-shrink:0;white-space:nowrap}" +
    ".bdlp-exp:hover{color:#d9dee8}" +
    ".bdlp-out{font-size:11px;color:#7c8797;word-break:break-all;margin-top:4px}" +
    ".bdlp-bar{height:6px;background:#1c2536;border-radius:3px;overflow:hidden;margin:6px 0}" +
    ".bdlp-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#2f7bff,#7fd0ff)}" +
    ".bdlp-sub{font-size:11px;color:#7c8797;display:flex;justify-content:space-between;gap:8px}" +
    ".bdlp-ops{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}" +
    ".bdlp-ops button{background:#1f2839;border:1px solid #333d52;color:#c8d0dc;border-radius:6px;" +
    "padding:4px 10px;font-size:12px;cursor:pointer}" +
    ".bdlp-ops button:hover{background:#2a3650}" +
    ".bdlp-empty{color:#6b7590;font-size:12px;text-align:center;padding:26px 0}" +
    ".bdlp-kv{font-size:12px;color:#9aa6bd;margin:5px 0;word-break:break-all}" +
    ".bdlp-kv b{color:#e6e9ef;display:inline-block;min-width:70px}" +
    ".bdlp-sep{border-top:1px solid #232c40;margin:12px 0}";

  // -------------------------------------------------------- render dispatch ----------
  function renderTab(name) {
    currentTab = name;
    var body = $(".bdlp-body", shadow);
    var tabs = shadow.querySelectorAll(".bdlp-tab");
    Array.prototype.forEach.call(tabs, function (t) {
      t.classList.toggle("on", t.getAttribute("data-tab") === name);
    });
    if (name === "build") renderBuild(body);
    else if (name === "tasks") renderTasks(body);
    else renderSet(body);
    checkHealth();
  }

  function setDot(cls) {
    var dot = $(".bdlp-dot", shadow);
    if (dot) dot.className = "bdlp-dot" + (cls ? " " + cls : "");
  }

  function checkHealth() {
    api("/api/health")
      .then(function (j) {
        setDot(j && j.code === 0 && j.data && j.data.ok ? "ok" : "bad");
      })
      .catch(function () { setDot("bad"); });
  }

  function showTip(container, msg, isErr) {
    var w = container.querySelector(".bdlp-warn");
    if (!w) {
      w = el("div", { "class": "bdlp-warn" });
      container.insertBefore(w, container.firstChild);
    }
    w.className = "bdlp-warn" + (isErr ? " err" : "");
    w.textContent = msg;
  }
  function warnHtml(msg, isErr) {
    return '<div class="bdlp-warn' + (isErr ? " err" : "") + '">' + esc(msg) + "</div>";
  }

  // -------------------------------------------------- Tab1 · New Download ------
  function renderBuild(body) {
    var meta = pageMeta();
    if (!meta) {
      body.innerHTML = warnHtml("Not a bilibili video page, or video info could not be parsed from the page.", true);
      return;
    }
    var sel = currentPage();
    var info = null;
    var pfx = meta.season ? "EP" : "P";
    body.innerHTML =
      warnHtml("Parsing video info…", false) +
      '<div class="bdlp-meta"><b>' + esc(meta.title) + "</b>" +
      esc(meta.uploader ? meta.uploader + " · " : "") +
      meta.bvid + " · " + '<span class="bdlp-login">Checking…</span>' + "</div>" +
      (meta.season
        ? '<span class="bdlp-lbl">Episodes</span>'
        : '<span class="bdlp-lbl">Parts (current P' + sel + ")</span>") +
      '<div class="bdlp-pages"></div>' +
      '<span class="bdlp-lbl">Quality</span>' +
      '<div class="bdlp-quality"></div>' +
      '<label class="bdlp-check"><input type="checkbox" class="bdlp-audio"> Audio only</label>' +
      '<button class="bdlp-btn">Start download</button>';

    renderPages(body, meta.pages, sel, pfx);

    var qbox = body.querySelector(".bdlp-quality");
    var audio = body.querySelector(".bdlp-audio");
    audio.addEventListener("change", function () {
      Array.prototype.forEach.call(qbox.querySelectorAll(".bdlp-opt"), function (o) {
        if (audio.checked) {
          o.classList.toggle("sel", o.dataset.quality === "audio");
        }
      });
      // the selected "Audio only" button stays clickable; graying out the rest is handled by applyQualities after validation
    });

    body.querySelector(".bdlp-btn").addEventListener("click", function () {
      startDownloadClicked(body, meta, qbox, audio, info);
    });

    loginCookie().then(function (ck) {
      var span = body.querySelector(".bdlp-login");
      if (span) {
        if (ck.indexOf("SESSDATA=") >= 0) span.textContent = "Logged in";
        else if (cookieFound["DedeUserID"] && !cookieFound["SESSDATA"])
          span.textContent = "Not logged in (cannot read HttpOnly cookie, see console)";
        else span.textContent = "Not logged in";
      }
      return fetchInfo(window.location.href, ck);
    })
      .then(function (j) {
        if (!j) return;
        var w = body.querySelector(".bdlp-warn");
        if (j.code === 0 && j.data) {
          if (w) w.remove();
          info = j.data;
          if (meta.season && j.data.pages && j.data.pages.length) {
            renderPages(body, j.data.pages, currentEpisodeFromSheet(j.data.pages, meta.currentEp || 1), pfx);
          }
          applyQualities(qbox, j.data);
        } else if (w) {
          w.textContent = "Parse failed: " + ((j.msg) || "unknown error");
          w.classList.add("err");
        }
      })
      .catch(function () {
        var w = body.querySelector(".bdlp-warn");
        if (w) w.textContent = "Backend unreachable, quality not verified.";
        checkHealth();
      });
  }

  function renderPages(body, pages, sel, pfx) {
    var box = body.querySelector(".bdlp-pages");
    if (!box) return;
    box.innerHTML = "";
    pages.forEach(function (p) {
      var label = el("label", { "class": "bdlp-check" });
      var cb = el("input", { type: "checkbox", "class": "bdlp-page", value: String(p.page) });
      if (p.page === sel) cb.checked = true;
      if (pages.length === 1) cb.checked = true;
      label.appendChild(cb);
      label.appendChild(el("span", { "class": "bdlp-page-title" }, (pfx || "P") + p.page + " · " + (p.title || "")));
      box.appendChild(label);
    });
    var allLink = el("a", { href: "#", "class": "bdlp-check" }, "Select all / none");
    allLink.addEventListener("click", function (e) {
      e.preventDefault();
      var cbs = box.querySelectorAll(".bdlp-page");
      var next = Array.prototype.some.call(cbs, function (c) { return !c.checked; });
      Array.prototype.forEach.call(cbs, function (c) { c.checked = next; });
    });
    box.appendChild(allLink);
  }

  // pick the currently playing episode from the season sheet, else the first page
    function currentEpisodeFromSheet(pages, currentEp) {
      for (var i = 0; i < pages.length; i++) {
        if (pages[i].page === currentEp) return currentEp;
      }
      return (pages[0] && pages[0].page) || 1;
    }

  function applyQualities(qbox, info) {
    var items = [];
    items.push({ v: "auto", label: info.auto_resolution ? "Auto (" + info.auto_resolution + ")" : "Auto" });
    (info.available_qualities || []).forEach(function (q) {
      items.push({ v: q.label, label: q.label });
    });
    qbox.innerHTML = "";
    items.forEach(function (q) {
      var btn = el("button", { type: "button", "class": "bdlp-opt" }, q.label);
      btn.dataset.quality = q.v;
      if (q.v === defaultQuality()) btn.classList.add("sel");
      qbox.appendChild(btn);
    });
  }

  function defaultQuality() {
    return getCfg().defaultQuality || "auto";
  }

  function startDownloadClicked(body, meta, qbox, audio, info) {
    var checks = body.querySelectorAll(".bdlp-page:checked");
    var pages = Array.prototype.map.call(checks, function (c) { return parseInt(c.value, 10); });
    if (!pages.length) { showTip(body, "Select at least one part", true); return; }

    var urls = [];
    if (meta.season && info && info.pages) {
      pages.forEach(function (pg) {
        var hit = null;
        for (var i = 0; i < info.pages.length; i++) {
          if (info.pages[i].page === pg) { hit = info.pages[i]; break; }
        }
        urls.push((hit && hit.url) || "");
      });
    }

    var sel = qbox.querySelector(".bdlp-opt.sel");
    var quality = sel ? sel.dataset.quality : "auto";
    var audioOnly = audio.checked;

    var btn = body.querySelector(".bdlp-btn");
    btn.disabled = true;
    btn.textContent = "Submitting…";

    var submit = loginCookie().then(function (ck) {
      return postDownload({
        url: window.location.href,
        pages: pages,
        urls: urls,
        quality: audioOnly ? "audio" : quality,
        audio_only: audioOnly,
        cookies: ck,
        codec: getCfg().codecPref || "auto",
        overwrite: false,
        title: meta.title || "",
      });
    });
    submit.then(function (j) {
        btn.disabled = false;
        btn.textContent = "Start download";
        if (j && j.code === 0 && j.data && j.data.jobs) {
          showTip(body, "Created " + j.data.jobs.length + " job(s)", false);
          setTimeout(function () { renderTab("tasks"); }, 400);
        } else if (j && j.code === -401) {
          showTip(body, "Auth failed: enter the correct token in Settings", true);
        } else {
          showTip(body, (j && j.msg) || "Failed to create job", true);
        }
      })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = "Start download";
        showTip(body, "Backend unreachable: " + err.message, true);
        checkHealth();
      });
  }

  // -------------------------------------------------- Tab2 · Tasks ------
  function renderTasks(body) {
    closeAllWatchers();
    body.innerHTML = '<div class="bdlp-empty">Loading…</div>';
    listJobs()
      .then(function (j) {
        if (j && j.code === -401) {
          body.innerHTML = warnHtml("Auth failed: set auth_token in Settings.", true);
          return;
        }
        if (!j || j.code !== 0 || !j.data) {
          body.innerHTML = warnHtml("Load failed: " + ((j && j.msg) || "backend unreachable"), true);
          return;
        }
        var jobs = j.data.jobs || [];
        jobsCache = {};
        jobs.forEach(function (job) { jobsCache[job.id] = job; });
        paintJobs(body);
      })
      .catch(function () {
        body.innerHTML = warnHtml("Backend unreachable, task list unavailable.", true);
        checkHealth();
      });
  }

  function paintJobs(body) {
    var ids = Object.keys(jobsCache);
    if (!ids.length) {
      body.innerHTML = '<div class="bdlp-empty">No jobs yet. Start one on the New Download tab.</div>';
      return;
    }
    var done = ids.filter(function (id) { return jobsCache[id].status === "done"; }).length;
    var head = '<div class="bdlp-sub" style="margin-bottom:8px">' +
      "<span></span><span>" + done + "/" + ids.length + " done</span></div>";
    body.innerHTML = head + ids.map(function (id) { return jobCard(jobsCache[id]); }).join("");
    watchAll();
  }

  function jobCard(j) {
    var st = statusStyle(j.status);
    var p = j.progress || {};
    var pct = Number(p.percent) || 0;
    if (j.status === "done" && pct <= 0) pct = 100;
    var acts = actsFor(j);
    var exp = !!expandedJobs[j.id];
    var h =
      '<div class="bdlp-job' + (exp ? " bdlp-full" : "") + '" data-jid="' + esc(j.id) + '">' +
      '<div class="bdlp-head" data-expand="1" title="' + (exp ? "Collapse details" : "Expand details") + '">' +
      '<h4><span class="bdlp-badge" style="color:' + st.color + ';background:' + st.color + "22" + '">' +
      esc(st.label) + "</span> " + esc(j.title || "Job") + "</h4>" +
      '<button type="button" class="bdlp-exp">' +
      (exp ? "Collapse" : "Expand") + "</button></div>" +
      '<div class="bdlp-bar"><i style="width:' + pct.toFixed(1) + '%"></i></div>' +
      '<div class="bdlp-sub"><span>' + pct.toFixed(1) + "% · " + esc(String(p.speed || "")) +
      (p.phase ? " · " + esc(p.phase) : "") + '</span><span>ETA ' + esc(String(p.eta || "")) + "</span></div>";
    if (exp) {
      if (j.error) h += '<div class="bdlp-sub" style="color:#f85149;margin-top:4px">' + esc(j.error) + "</div>";
      if (j.out_path && j.status === "done") h += '<div class="bdlp-out">' + esc(j.out_path) + "</div>";
    }
    if (acts.length) h += '<div class="bdlp-ops">' + acts.map(function (a) {
      return '<button data-action="' + a.op + '">' + a.label + "</button>";
    }).join("") + "</div>";
    return h + "</div>";
  }

  function statusStyle(s) {
    var map = {
      queued: ["Queue", "#8792a5"], downloading: ["Downloading", "#4c9fff"], merging: ["Merging", "#b57edc"],
      paused: ["Paused", "#f0a94c"], interrupted: ["Interrupted", "#f85149"], failed: ["Failed", "#f85149"],
      done: ["Done", "#3fb950"], canceled: ["Canceled", "#8792a5"],
    };
    var hit = map[s] || [s, "#8792a5"];
    return { label: hit[0], color: hit[1] };
  }

  function actsFor(j) {
    switch (j.status) {
      case "downloading":
      case "merging":
        return [{ op: "pause", label: "Pause" }, { op: "cancel", label: "Cancel" }];
      case "paused":
        return [{ op: "resume", label: "Resume" }, { op: "cancel", label: "Cancel" }];
      case "interrupted":
      case "failed":
      case "canceled":
        return [{ op: "resume_after_interrupt", label: "Resume" }, { op: "delete", label: "Delete" }];
      case "done":
        return [{ op: "delete", label: "Delete" }];
      case "queued":
        return [{ op: "cancel", label: "Cancel" }];
      default:
        return [];
    }
  }

  // ------------------------ Live job refresh (single global SSE + full polling fallback) ----------
  // A single SSE broadcasts all jobs (events carry job_id), avoiding Chrome's per-host concurrent
  // connection limit (HTTP/1.1 cap of 6) leaving only the first few cards updated; on SSE drop it
  // falls back to a full listJobs poll (which also uses only 1 connection).
  function watchAll() {
    if (watchers.length) return;
    var es = new EventSource(backendHost() + "/api/jobs/stream");
    var pollTimer = null;

    function startPoll() {
      if (pollTimer) return;
      pollTimer = setInterval(function () {
        listJobs().then(function (j) {
          if (!j || j.code !== 0 || !j.data) return;
          var seen = {};
          (j.data.jobs || []).forEach(function (job) {
            seen[job.id] = true;
            updateCard(job);
          });
          var goners = Object.keys(jobsCache).filter(function (id) { return !seen[id]; });
          goners.forEach(function (id) { delete jobsCache[id]; });
          if (goners.length) paintJobs($(".bdlp-body", shadow));
        }).catch(noop);
      }, 2000);
    }
    function stopPoll() {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }
    function onSSE(ev) {
      try { updateCard(JSON.parse(ev.data)); } catch (e) {}
    }

    es.addEventListener("progress", onSSE);
    es.addEventListener("status", onSSE);
    es.addEventListener("open", function () { stopPoll(); });
    es.addEventListener("error", function () { startPoll(); });
    watchers.push({ link: es, stop: function () { es.close(); stopPoll(); } });
  }

  function closeAllWatchers() {
    watchers.forEach(function (w) { w.stop(); });
    watchers = [];
  }

  function updateCard(j) {
    if (!j || !j.id) return;
    var old = jobsCache[j.id] || {};
    jobsCache[j.id] = Object.assign({}, old, j);
    if (currentTab !== "tasks") return;
    var body = $(".bdlp-body", shadow);
    if (!body) return;
    var card = body.querySelector('.bdlp-job[data-jid="' + j.id + '"]');
    if (card) card.outerHTML = jobCard(jobsCache[j.id]);
    else paintJobs(body);
    // refresh aggregate counts after terminal state
    var done = Object.keys(jobsCache).filter(function (id) {
      return jobsCache[id].status === "done";
    }).length;
    var sum = body.querySelector(".bdlp-sub");
    if (sum) sum.innerHTML = "<span></span><span>" + done + "/" + Object.keys(jobsCache).length + " done</span>";
  }

  function noop() {}

  // -------------------------------------------------- Tab3 · Settings ------
  function renderSet(body) {
    var c = getCfg();

    function save() {
      var url = body.querySelector(".bdlp-set-url").value.trim();
      var token = body.querySelector(".bdlp-set-token").value.trim();
      var quality = body.querySelector(".bdlp-set-qual").value;
      var codec = body.querySelector(".bdlp-set-codec").value;
      setCfg({ backendUrl: url, authToken: token, defaultQuality: quality, codecPref: codec });
      showTip(body, "Saved", false);
      checkHealth();
    }

    function codecOptionHtml(v, label) {
      return '<option value="' + v + '">' + label + "</option>";
    }

    function codecSelectHtml(extraClass) {
      return '<span class="bdlp-lbl">Codec preference</span>' +
        '<select class="bdlp-set-codec' + (extraClass || "") + '">' +
        codecOptionHtml("auto", "Auto (hvc>av01>avc)") +
        codecOptionHtml("hvc,av01,avc", "HEVC > AV1 > H.264") +
        codecOptionHtml("av01,hvc,avc", "AV1 > HEVC > H.264") +
        codecOptionHtml("avc,hvc,av01", "H.264 first") +
        codecOptionHtml("hvc", "HEVC only") +
        codecOptionHtml("avc", "H.264 only") +
        "</select>";
    }

    function codecSelected(select) {
      var v = getCfg().codecPref || "auto";
      select.value = v;
      if (!select.value) select.value = "auto";
    }

    fetchConfig()
      .then(function (j) {
        var info = (j && j.code === 0 && j.data) ? j.data : null;
        body.innerHTML =
          '<span class="bdlp-lbl">Backend URL</span>' +
          '<input class="bdlp-set-url" type="url" value="' + esc(c.backendUrl || "http://127.0.0.1:8000") + '">' +
          '<span class="bdlp-lbl">auth_token (leave empty to omit)</span>' +
          '<input class="bdlp-set-token" type="password" value="' + esc(c.authToken || "") + '">' +
'<span class="bdlp-lbl">Default quality</span>' +
  '<select class="bdlp-set-qual">' +
  '<option value="auto">Auto</option><option value="8K">8K</option>' +
  '<option value="4K">4K</option><option value="2K">2K</option>' +
  '<option value="1080P60">1080P60</option><option value="1080P">1080P</option>' +
  '<option value="720P60">720P60</option><option value="720P">720P</option>' +
  '<option value="480P">480P</option><option value="360P">360P</option>' +
  '<option value="audio">Audio only</option></select>' +
          codecSelectHtml() +
  '<button class="bdlp-btn">Save settings</button>' +
  '<div class="bdlp-sep"></div>' +
          (info ? backendInfoHtml(info) : warnHtml("Backend not running, cannot read backend config.", true));
        body.querySelector(".bdlp-set-qual").value = c.defaultQuality || "auto";
        if (!body.querySelector(".bdlp-set-qual").value) body.querySelector(".bdlp-set-qual").value = "auto";
        if (body.querySelector(".bdlp-set-codec")) codecSelected(body.querySelector(".bdlp-set-codec"));
        body.querySelector(".bdlp-btn").addEventListener("click", save);
      })
      .catch(function () {
        body.innerHTML =
          '<span class="bdlp-lbl">Backend URL</span>' +
          '<input class="bdlp-set-url" type="url" value="' + esc(c.backendUrl || "http://127.0.0.1:8000") + '">' +
          '<span class="bdlp-lbl">auth_token</span>' +
          '<input class="bdlp-set-token" type="password" value="' + esc(c.authToken || "") + '">' +
'<span class="bdlp-lbl">Default quality</span>' +
  '<select class="bdlp-set-qual"><option value="auto">Auto</option>' +
  '<option value="8K">8K</option><option value="4K">4K</option>' +
  '<option value="2K">2K</option><option value="1080P60">1080P60</option>' +
  '<option value="1080P">1080P</option>' +
  '<option value="720P60">720P60</option><option value="720P">720P</option>' +
  '<option value="480P">480P</option><option value="360P">360P</option>' +
  '<option value="audio">Audio only</option></select>' +
          codecSelectHtml() +
          '<button class="bdlp-btn">Save settings</button>' +
          warnHtml("Backend unreachable, cannot read backend config.", true);
        body.querySelector(".bdlp-set-qual").value = c.defaultQuality || "auto";
        if (!body.querySelector(".bdlp-set-qual").value) body.querySelector(".bdlp-set-qual").value = "auto";
        if (body.querySelector(".bdlp-set-codec")) codecSelected(body.querySelector(".bdlp-set-codec"));
        body.querySelector(".bdlp-btn").addEventListener("click", save);
      });
  }

  function backendInfoHtml(info) {
    return '<div class="bdlp-kv"><b>Download dir</b>' + esc(info.download_dir) + "</div>" +
      '<div class="bdlp-kv"><b>Concurrency</b>' + esc(String(info.max_concurrent)) + "</div>" +
      '<div class="bdlp-kv"><b>yt-dlp</b>' + esc(info.yt_dlp_version || info.yt_dlp_path || "") + "</div>" +
      '<div class="bdlp-kv"><b>File template</b>' + esc(info.file_template) + "</div>";
  }

  // ----------------------------------------------------------- events ---- -----
  function onShadowClick(e) {
    var tab = e.target.closest(".bdlp-tab");
    if (tab) {
      renderTab(tab.getAttribute("data-tab"));
      return;
    }
    var optBtn = e.target.closest(".bdlp-opt");
    if (optBtn && !optBtn.disabled) {
      var qbox = optBtn.closest(".bdlp-quality");
      if (qbox) {
        Array.prototype.forEach.call(qbox.querySelectorAll(".bdlp-opt"), function (o) {
          if (!o.disabled) o.classList.remove("sel");
        });
        optBtn.classList.add("sel");
      }
      return;
    }
    var exp = e.target.closest("[data-expand]");
    if (exp) {
      var card = exp.closest(".bdlp-job");
      if (!card) return;
      var jid = card.getAttribute("data-jid");
      if (expandedJobs[jid]) delete expandedJobs[jid];
      else expandedJobs[jid] = true;
      card.outerHTML = jobCard(jobsCache[jid] || { id: jid });
      return;
    }
    var act = e.target.closest("[data-action]");
    if (act) {
      var card = act.closest(".bdlp-job");
      if (card) doJobOp(card.getAttribute("data-jid"), act.getAttribute("data-action"));
    }
  }

  function doJobOp(id, op) {
    var cookiesP = op === "resume_after_interrupt" ? loginCookie() : Promise.resolve("");
    cookiesP.then(function (ck) {
        if (op === "delete") return deleteJob(id);
        return jobOp(id, op, ck);
      })
      .then(function (j) {
        if (j && j.code === -401) { renderTab("set"); return; }
        if (!j || j.code !== 0) {
          showTip($(".bdlp-body", shadow), (j && j.msg) || "Operation failed", true);
          return;
        }
        renderTasks($(".bdlp-body", shadow));
      })
      .catch(function () {
        showTip($(".bdlp-body", shadow), "Backend unreachable", true);
        checkHealth();
      });
  }

  // ------------------------------------------------------------ boot --------
  function boot() {
    try {
      ensureUI();
      console.log("[bili-dl] panel mounted, pill=" + !!$(".bdlp-pill", shadow));
    } catch (e) {
      console.error("[bili-dl] boot failed:", e);
      return;
    }
    GM_registerMenuCommand("Set backend URL", function () {
      var v = prompt("Backend URL (leave empty for default)", backendHost());
      if (v === null) return;
      setCfg({ backendUrl: v.trim().replace(/\/+$/, "") || "http://127.0.0.1:8000" });
      checkHealth();
    });
    setTimeout(function () {
      checkHealth();
      setInterval(checkHealth, 20000);
    }, 500);
  }

  boot();
})();