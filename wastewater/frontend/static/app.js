/* Wastewater Visit Planner — one trip, one weather card, one answer.
   Talks to frontend/server.py over /api. ?demo=1 renders static/sample-answer.json without the backend. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const api = async (path, opts = {}) => {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
    return data;
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pct = (v) => (v == null ? "n/a" : `${(v * 100).toFixed(1)}%`);
  const iso = (d) => d.toISOString().slice(0, 10);
  const DEMO = new URLSearchParams(location.search).get("demo") === "1";
  const ic = (name, cls = "") => `<i data-lucide="${name}" class="${cls}"></i>`;
  const icons = () => { try { if (window.lucide) lucide.createIcons(); } catch {} };

  /* ---------- places ---------- */
  const STATES = {
    al: "Alabama", ak: "Alaska", az: "Arizona", ar: "Arkansas", ca: "California", co: "Colorado", ct: "Connecticut", de: "Delaware",
    dc: "District of Columbia", fl: "Florida", ga: "Georgia", hi: "Hawaii", id: "Idaho", il: "Illinois", in: "Indiana", ia: "Iowa",
    ks: "Kansas", ky: "Kentucky", la: "Louisiana", me: "Maine", md: "Maryland", ma: "Massachusetts", mi: "Michigan", mn: "Minnesota",
    ms: "Mississippi", mo: "Missouri", mt: "Montana", ne: "Nebraska", nv: "Nevada", nh: "New Hampshire", nj: "New Jersey", nm: "New Mexico",
    ny: "New York", nc: "North Carolina", nd: "North Dakota", oh: "Ohio", ok: "Oklahoma", or: "Oregon", pa: "Pennsylvania", pr: "Puerto Rico",
    ri: "Rhode Island", sc: "South Carolina", sd: "South Dakota", tn: "Tennessee", tx: "Texas", ut: "Utah", vt: "Vermont", va: "Virginia",
    wa: "Washington", wv: "West Virginia", wi: "Wisconsin", wy: "Wyoming",
  };
  /* ---------- places: typed city -> county -> state (via /api/geocode) ---------- */
  const PLACE = {
    to: { name: "Richmond", county: "City of Richmond", state: "Virginia", stateCode: "va", lat: 37.55, lon: -77.46, label: "Richmond, VA" },
    from: { name: "Austin", county: "Travis County", state: "Texas", stateCode: "tx", lat: 30.27, lon: -97.74, label: "Austin, TX" },
  };
  // Instant matches while the remote lookup runs: the largest US cities, with county and state.
  const LOCAL_CITIES = [
    ["New York", null, "New York", "ny", 40.71, -74.01], ["Los Angeles", "Los Angeles County", "California", "ca", 34.05, -118.24],
    ["Chicago", "Cook County", "Illinois", "il", 41.88, -87.63], ["Houston", "Harris County", "Texas", "tx", 29.76, -95.37],
    ["Phoenix", "Maricopa County", "Arizona", "az", 33.45, -112.07], ["Philadelphia", "Philadelphia County", "Pennsylvania", "pa", 39.95, -75.17],
    ["San Antonio", "Bexar County", "Texas", "tx", 29.42, -98.49], ["San Diego", "San Diego County", "California", "ca", 32.72, -117.16],
    ["Dallas", "Dallas County", "Texas", "tx", 32.78, -96.8], ["Austin", "Travis County", "Texas", "tx", 30.27, -97.74],
    ["San Jose", "Santa Clara County", "California", "ca", 37.34, -121.89], ["Jacksonville", "Duval County", "Florida", "fl", 30.33, -81.66],
    ["Columbus", "Franklin County", "Ohio", "oh", 39.96, -83.0], ["Charlotte", "Mecklenburg County", "North Carolina", "nc", 35.23, -80.84],
    ["Indianapolis", "Marion County", "Indiana", "in", 39.77, -86.16], ["San Francisco", "San Francisco County", "California", "ca", 37.77, -122.42],
    ["Seattle", "King County", "Washington", "wa", 47.61, -122.33], ["Denver", "Denver County", "Colorado", "co", 39.74, -104.99],
    ["Washington", null, "District of Columbia", "dc", 38.91, -77.04], ["Boston", "Suffolk County", "Massachusetts", "ma", 42.36, -71.06],
    ["Nashville", "Davidson County", "Tennessee", "tn", 36.16, -86.78], ["Detroit", "Wayne County", "Michigan", "mi", 42.33, -83.05],
    ["Portland", "Multnomah County", "Oregon", "or", 45.52, -122.68], ["Las Vegas", "Clark County", "Nevada", "nv", 36.17, -115.14],
    ["Memphis", "Shelby County", "Tennessee", "tn", 35.15, -90.05], ["Louisville", "Jefferson County", "Kentucky", "ky", 38.25, -85.76],
    ["Baltimore", null, "Maryland", "md", 39.29, -76.61], ["Milwaukee", "Milwaukee County", "Wisconsin", "wi", 43.04, -87.91],
    ["Atlanta", "Fulton County", "Georgia", "ga", 33.75, -84.39], ["Miami", "Miami-Dade County", "Florida", "fl", 25.76, -80.19],
    ["Orlando", "Orange County", "Florida", "fl", 28.54, -81.38], ["Tampa", "Hillsborough County", "Florida", "fl", 27.95, -82.46],
    ["Minneapolis", "Hennepin County", "Minnesota", "mn", 44.98, -93.27], ["New Orleans", "Orleans Parish", "Louisiana", "la", 29.95, -90.07],
    ["Cleveland", "Cuyahoga County", "Ohio", "oh", 41.5, -81.69], ["Pittsburgh", "Allegheny County", "Pennsylvania", "pa", 40.44, -80.0],
    ["St. Louis", null, "Missouri", "mo", 38.63, -90.2], ["Raleigh", "Wake County", "North Carolina", "nc", 35.78, -78.64],
    ["Richmond", "City of Richmond", "Virginia", "va", 37.54, -77.44], ["Virginia Beach", null, "Virginia", "va", 36.85, -75.98],
    ["Salt Lake City", "Salt Lake County", "Utah", "ut", 40.76, -111.89], ["Sacramento", "Sacramento County", "California", "ca", 38.58, -121.49],
    ["Kansas City", "Jackson County", "Missouri", "mo", 39.1, -94.58], ["Honolulu", "Honolulu County", "Hawaii", "hi", 21.31, -157.86],
    ["Anchorage", null, "Alaska", "ak", 61.22, -149.9], ["Oklahoma City", "Oklahoma County", "Oklahoma", "ok", 35.47, -97.52],
  ].map(([name, county, state, stateCode, lat, lon]) => ({ name, county, state, stateCode, lat, lon, label: `${name}, ${stateCode.toUpperCase()}`, detail: [county, state].filter(Boolean).join(", ") }));
  const localMatches = (q) => { const k = q.toLowerCase(); return LOCAL_CITIES.filter((c) => c.name.toLowerCase().startsWith(k)).slice(0, 6); };
  const mergePlaces = (first, second) => { const seen = new Set(); return [...first, ...second].filter((p) => { const k = p.name + "|" + p.stateCode; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 6); };
  const REMOTE_CACHE = new Map();
  async function geocode(q) {
    if (!DEMO) return (await api(`/api/geocode?q=${encodeURIComponent(q)}`)).places;
    // demo: call the geocoder directly, same mapping as the server
    const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=20&language=en&format=json`);
    const rows = ((await r.json()).results || []).filter((x) => x.country_code === "US");
    const byName = Object.fromEntries(Object.entries(STATES).map(([c, n]) => [n.toLowerCase(), c]));
    const out = [], seen = new Set();
    for (const x of rows) {
      const code = byName[(x.admin1 || "").toLowerCase()]; if (!code || seen.has(x.name + code)) continue; seen.add(x.name + code);
      const county = x.admin2 ? (/county|parish|borough|city of|census area/i.test(x.admin2) ? x.admin2 : `${x.admin2} County`) : null;
      out.push({ name: x.name, county, state: x.admin1, stateCode: code, lat: x.latitude, lon: x.longitude, population: x.population || 0, label: `${x.name}, ${code.toUpperCase()}`, detail: [county, x.admin1].filter(Boolean).join(", ") });
    }
    const k = q.toLowerCase();
    out.sort((a, b) => { const ra = a.name.toLowerCase() === k ? 0 : a.name.toLowerCase().startsWith(k) ? 1 : 2, rb = b.name.toLowerCase() === k ? 0 : b.name.toLowerCase().startsWith(k) ? 1 : 2; return ra - rb || b.population - a.population; });
    return out.slice(0, 6);
  }
  function wirePlace(key) {
    const input = $(`trip-${key}`), list = $(`sug-${key}`);
    let timer = null, items = [], active = -1, seq = 0;
    input.value = PLACE[key].name;
    const close = () => { list.classList.add("hidden"); list.innerHTML = ""; items = []; active = -1; };
    const fit = () => { input.style.width = `${Math.max(7, input.value.length + 1.5)}ch`; };
    const choose = (p) => { PLACE[key] = p; input.value = p.name; fit(); close(); onTripChange(); };
    fit();
    let failed = null;
    const draw = () => {
      list.innerHTML = items.length
        ? items.map((p, i) => `<li class="${i === active ? "active" : ""}" data-i="${i}"><span>${esc(p.label)}</span><span class="d">${esc(p.detail || p.state)}</span></li>`).join("")
        : failed
          ? `<li class="empty">City lookup isn't available right now (${esc(failed)}). If you run the server yourself, restart it to pick up the latest code.</li>`
          : `<li class="empty">No US city found. Keep typing or try the nearest larger town.</li>`;
      list.classList.remove("hidden"); icons();
    };
    input.addEventListener("input", () => {
      fit();
      const q = input.value.trim();
      clearTimeout(timer);
      if (q.length < 2) { close(); return; }
      const my = ++seq;
      // show local matches at once, then merge the remote answer when it lands
      const local = localMatches(q);
      items = local; failed = null; active = -1;
      if (local.length) draw();
      const cached = REMOTE_CACHE.get(q.toLowerCase());
      if (cached) { items = mergePlaces(local, cached); draw(); return; }
      timer = setTimeout(async () => {
        try { const found = await geocode(q); if (my !== seq) return; REMOTE_CACHE.set(q.toLowerCase(), found); items = mergePlaces(local, found); failed = null; draw(); }
        catch (e) { if (my !== seq) return; failed = local.length ? null : (e.message || "network error"); if (!local.length) { items = []; draw(); } }
      }, 150);
    });
    input.addEventListener("keydown", (ev) => {
      if (list.classList.contains("hidden")) return;
      if (ev.key === "ArrowDown") { active = Math.min(items.length - 1, active + 1); draw(); ev.preventDefault(); }
      else if (ev.key === "ArrowUp") { active = Math.max(0, active - 1); draw(); ev.preventDefault(); }
      else if (ev.key === "Enter") { ev.preventDefault(); if (items[active >= 0 ? active : 0]) choose(items[active >= 0 ? active : 0]); }
      else if (ev.key === "Escape") { close(); input.value = PLACE[key].name; }
    });
    list.addEventListener("mousedown", (ev) => { const li = ev.target.closest("li[data-i]"); if (li) { ev.preventDefault(); choose(items[+li.dataset.i]); } });
    input.addEventListener("blur", () => setTimeout(() => { if (!list.classList.contains("hidden")) close(); if (input.value.trim() !== PLACE[key].name) { input.value = PLACE[key].name; fit(); } }, 150));
    input.addEventListener("focus", () => input.select());
  }
  wirePlace("to"); wirePlace("from");
  const now = new Date();
  $("trip-start").value = iso(new Date(now.getTime() + 14 * 864e5));
  $("trip-end").value = iso(new Date(now.getTime() + 21 * 864e5));

  /* ---------- trip state ---------- */
  // One answer per virus; `current` stays the COVID record for anything that needs a single one.
  const PATHOGENS = [
    { key: "sars-cov-2", name: "COVID-19", question: (st) => `is sars-cov-2 rising in ${st} over the last 2 weeks?`, sample: "sample-answer.json" },
    { key: "flu-a", name: "flu", question: (st) => `is flu rising in ${st} over the last 2 weeks?`, sample: "sample-answer-flu.json" },
  ];
  const answers = {};
  let current = null;
  const setGoogleLink = (rec) => { const a = $("cal-google"); if (a) a.href = googleCalendarUrl(rec); };
  function trip() {
    const to = PLACE.to, from = PLACE.from;
    let start = $("trip-start").value, end = $("trip-end").value;
    if (start && end && end < start) end = start;
    const adults = Math.max(1, parseInt($("trip-adults").value, 10) || 1);
    const children = Math.max(0, parseInt($("trip-children").value, 10) || 0);
    const elderly = $("who-elderly").getAttribute("aria-pressed") === "true";
    const kids = $("who-kids").getAttribute("aria-pressed") === "true";
    const with_ = [elderly ? "older adults" : null, kids ? "young children" : null].filter(Boolean).join(" and ");
    return { to, from, start, end, adults, children, elderly, kids, with_,
      stateName: to ? to.state || STATES[to.stateCode] || to.stateCode.toUpperCase() : "the United States",
      party: `${adults} ${adults === 1 ? "adult" : "adults"}${children ? ` and ${children} ${children === 1 ? "child" : "children"}` : ""}` };
  }
  const fmtDay = (s) => s ? new Date(s + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "";
  let map = null, marker = null;
  function drawMap(t) {
    if (typeof L === "undefined" || !t.to) return;
    const pos = [t.to.lat, t.to.lon];
    if (!map) {
      map = L.map("map", { scrollWheelZoom: false, zoomControl: false, attributionControl: true }).setView(pos, 9);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 14, attribution: "© OpenStreetMap" }).addTo(map);
    } else map.setView(pos, 9);
    if (marker) marker.remove();
    marker = L.circleMarker(pos, { radius: 11, color: "#19606a", fillColor: "#19606a", fillOpacity: .35, weight: 2 }).addTo(map);
    const lines = Object.values(answers).map((rec) => { const f = rec.facts; return `${rec.pathogenName || "SARS-CoV-2"}: ${pct(f.coverage === "empty" ? f.fallback_positive_share : f.positive_share)} of samples`; });
    marker.bindPopup(lines.length ? `<b>${esc(t.to.name)}</b><br>${lines.map(esc).join("<br>")}` : t.to.name);
    setTimeout(() => map.invalidateSize(), 60);
  }
  function onTripChange() {
    const t = trip();
    if ($("trip-end").value && $("trip-start").value && $("trip-end").value < $("trip-start").value) $("trip-end").value = $("trip-start").value;
    $("w-adults").textContent = t.adults === 1 ? "adult and" : "adults and";
    $("w-children").textContent = t.children === 1 ? "child," : "children,";
    $("hero-title").textContent = t.to ? `Visiting ${t.to.name}` : "Plan a visit";
    $("hero-dates").textContent = `${fmtDay(t.start)} – ${fmtDay(t.end)}`;
    $("hero-party").textContent = t.party.replace(" and ", ", ") + (t.with_ ? `, with ${t.with_}` : "");
    drawMap(t);
    if (current) { setGoogleLink(current); Object.values(answers).forEach((rec) => renderPoints(rec, t)); }
    loadWeather();
  }
  ["trip-start", "trip-end"].forEach((id) => $(id).addEventListener("change", onTripChange));
  document.querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => {
    const input = $(b.dataset.for), min = +input.min, max = +input.max;
    input.value = Math.min(max, Math.max(min, (parseInt(input.value, 10) || 0) + (+b.dataset.d)));
    document.querySelectorAll(`.step[data-for="${input.id}"]`).forEach((s) => { s.disabled = (+s.dataset.d < 0 && +input.value <= min) || (+s.dataset.d > 0 && +input.value >= max); });
    onTripChange();
  }));
  document.querySelectorAll(".tog").forEach((b) => b.addEventListener("click", () => { b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") === "true" ? "false" : "true"); onTripChange(); }));
  $("trip-form").addEventListener("submit", (ev) => ev.preventDefault());

  /* ---------- theme + tabs ---------- */
  const root = document.documentElement;
  try { const t = localStorage.getItem("theme"); if (t) root.dataset.theme = t; } catch {}
  $("theme").addEventListener("click", () => {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    const cur = root.dataset.theme || (dark ? "dark" : "light");
    root.dataset.theme = cur === "dark" ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch {}
  });
  function showTab(name) {
    document.querySelectorAll(".nav-btn[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === name));
    window.scrollTo({ top: 0 });
    if (name === "overview" && map) setTimeout(() => map.invalidateSize(), 50);
  }
  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", (ev) => { ev.preventDefault(); showTab(b.dataset.tab); }));

  /* ---------- status dots ---------- */
  async function loadStatus() {
    const rail = $("rail-status");
    if (!rail) return;  // the dashboard top bar has no status dots
    const set = (key, ok, title) => { const i = rail.querySelector(`[data-k="${key}"]`); if (i) { i.classList.toggle("ok", !!ok); i.classList.toggle("bad", !ok); i.title = title; } };
    try {
      const s = DEMO ? { zetaris: { ok: true, latestSample: "2026-10-13" }, nightshift: { ok: true, state: "online" } } : await api("/api/status");
      set("zetaris", s.zetaris.ok, s.zetaris.ok ? `Zetaris, data to ${s.zetaris.latestSample}` : `Zetaris down: ${s.zetaris.error || ""}`);
      set("nightshift", s.nightshift.ok, s.nightshift.ok ? "Nightshift online" : `Nightshift ${s.nightshift.state}`);
    } catch { set("zetaris", false, "status unavailable"); set("nightshift", false, "status unavailable"); }
  }

  /* ---------- check the water ---------- */
  /* The progress card follows the agent's own events (streamed as JSON lines from
     /api/ask with stream: true): each stage, and the model that handled each
     Nightshift call. Demo mode replays a recorded sequence. */
  const shortModel = (m) => (m ? String(m).replace(/^nvidia\//, "") : "");
  const modelHtml = (m) => `<span class="model" title="${esc(m)}">${esc(shortModel(m))}</span>`;
  const progress = {
    stageOf: null,  // the stage a route event belongs to ("plan" or "write")
    begin(title) {
      $("progress-title").textContent = title;
      $("progress-step").textContent = "Starting";
      $("progress-trail").innerHTML = "";
      $("answer-progress").classList.remove("hidden", "done");
      this.stageOf = null;
    },
    step(html) { $("progress-step").innerHTML = html; },
    trail(html, warn = false) { const li = document.createElement("li"); if (warn) li.className = "warn"; li.innerHTML = html; $("progress-trail").appendChild(li); },
    event(e) {
      const verb = this.stageOf === "write" ? "Writing" : "Planning";
      switch (`${e.stage}:${e.state}`) {
        case "plan:start": this.stageOf = "plan"; this.step("Planning the query"); break;
        case "route:start": this.step(`${verb} with ${modelHtml(e.model)}`); break;
        case "route:failed": this.trail(`${esc(shortModel(e.model))} failed, trying the next route`, true); break;
        case "route:done": break;  // the stage's own done event records the model
        case "plan:done":
          this.trail(e.model ? `Planned by ${modelHtml(e.model)}` : "Planned by rules (Nightshift unavailable)", !e.model);
          break;
        case "recall:done": this.trail(e.count ? `Recalled ${e.count} earlier finding${e.count === 1 ? "" : "s"}` : "No earlier findings to recall"); break;
        case "query:start": this.stageOf = null; this.step("Running SQL on Zetaris"); break;
        case "query:done": this.trail(`${e.statements} SQL statements on Zetaris, ${e.samples ?? 0} samples (${e.coverage} coverage)`); break;
        case "write:start": this.stageOf = "write"; this.step("Writing the answer"); break;
        case "write:done":
          this.trail(e.model ? `Written by ${modelHtml(e.model)}, figures checked${e.attempts > 1 ? ` (${e.attempts} attempts)` : ""}`
                             : "Written from templates (model output rejected)", !e.model);
          break;
        case "memory:done": this.trail("Finding stored in memory"); this.step("Done"); break;
      }
    },
    finish() { $("answer-progress").classList.add("done"); $("progress-step").textContent = "Done"; setTimeout(() => $("answer-progress").classList.add("hidden"), 6000); },
  };
  async function askStream(body, onEvent) {
    const res = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, stream: true }) });
    if (!res.ok || !(res.headers.get("content-type") || "").includes("ndjson")) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `${res.status} ${res.statusText}`);
    }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "", record = null;
    for (;;) {
      const { value, done } = await reader.read();
      buf += done ? dec.decode() : dec.decode(value, { stream: true });
      const lines = buf.split("\n"); buf = done ? "" : lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const e = JSON.parse(line);
        if (e.stage === "answer") record = e.record;
        else if (e.stage === "error") throw new Error(e.error);
        else onEvent(e);
      }
      if (done) break;
    }
    if (!record) throw new Error("the connection closed before the answer arrived");
    return record;
  }
  const block = (key) => $(`pb-${key}`);
  const part = (key, role) => block(key).querySelector(`[data-role="${role}"]`);
  async function check() {
    const t = trip();
    $("visit-submit").disabled = true;
    for (const p of PATHOGENS) {
      const question = p.question(t.stateName);
      progress.begin(`Checking ${p.name} in ${t.to ? t.to.name : t.stateName}`);
      part(p.key, "error").classList.add("hidden");
      try {
        const rec = DEMO ? await demoAnswer(p, question)
          : await askStream({ question, county: t.to ? t.to.county : null, pathogen: p.key }, (e) => progress.event(e));
        render(rec);
      } catch (e) {
        const err = part(p.key, "error");
        err.textContent = `The ${p.name} check didn't complete: ${e.message.split("\n")[0]}. Try again in a moment.`;
        err.classList.remove("hidden");
        block(p.key).classList.remove("hidden");
        $("plan-empty").classList.add("hidden");
      }
    }
    progress.finish();
    $("visit-submit").disabled = false;
    if (!DEMO) loadStatus();
  }
  $("visit-submit").addEventListener("click", check);
  async function demoAnswer(p, question) {
    const rec = await (await fetch(p.sample)).json();
    rec.question = question; rec.id = "ans_demo_" + Date.now().toString(36); rec.askedAt = new Date().toISOString();
    rec.pathogen = rec.pathogen || p.key;
    // Replay the stages with the models the stored receipts name.
    const model = (i) => (rec.receipts[i] || rec.receipts[0] || {}).routedModel || "nvidia/nemotron-3-ultra-550b-a55b";
    const f = rec.facts, pause = (ms) => new Promise((r) => setTimeout(r, ms));
    const script = [
      ["plan:start", {}], ["route:start", { model: "meterless/auto" }], ["plan:done", { model: model(0) }],
      ["recall:done", { count: rec.memoriesUsed.length }], ["query:start", {}],
      ["query:done", { statements: rec.statements.length, samples: f.samples, coverage: f.coverage }],
      ["write:start", {}], ["route:start", { model: "meterless/auto" }], ["write:done", { model: model(1), attempts: 1 }],
      ["memory:done", {}],
    ];
    for (const [k, extra] of script) { const [stage, state] = k.split(":"); progress.event({ stage, state, ...extra }); await pause(350); }
    return rec;
  }

  // The plan's points: the figures, who you'll be with, and when to check again.
  function renderPoints(rec, t) {
    const f = rec.facts;
    const share = f.coverage === "empty" ? f.fallback_positive_share : f.positive_share;
    const samples = f.coverage === "empty" ? f.fallback_samples : f.samples;
    const pts = [
      ["map-pin", `${rec.region}, ${f.window.start} to ${f.window.end}`],
      ["flask-conical", `${pct(share)} of ${samples ?? 0} samples had the virus${f.direction && f.direction !== "unknown" ? `, ${f.direction}` : ""}`],
      ["clock", `Latest data ${f.latest_sample_date || "unknown"}`],
    ];
    if (t.with_) pts.push(["users", `You'll be with ${t.with_}`]);
    pts.push(["calendar-check", f.direction === "rising" ? "Check again a few days before you go" : "Check again before you go"]);
    part(rec.pathogen || "sars-cov-2", "points").innerHTML = pts.map(([i, txt]) => `<li>${ic(i)}<span>${esc(txt)}</span></li>`).join("");
    icons();
  }
  function render(rec) {
    const key = rec.pathogen || "sars-cov-2";
    answers[key] = rec;
    if (key === "sars-cov-2" || !current) current = rec;
    const f = rec.facts, t = trip();
    const covText = { full: "Data covers the whole period", partial: "Data lags the end of the period", empty: "No data for this period yet" }[f.coverage] || f.coverage;
    const badge = part(key, "coverage"); badge.textContent = covText; badge.className = `badge ${f.coverage}`;
    part(key, "text").textContent = rec.text;
    renderPoints(rec, t);
    $("plan-empty").classList.add("hidden");
    block(key).classList.remove("hidden");
    setGoogleLink(current);
    drawMap(t);
    icons();
  }

  /* ---------- weather: destination for the dates, home for comparison ---------- */
  const WX_CODES = { 0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "drizzle", 53: "drizzle", 55: "drizzle",
    61: "rain", 63: "rain", 65: "heavy rain", 71: "snow", 73: "snow", 75: "heavy snow", 80: "showers", 81: "showers", 82: "heavy showers", 95: "thunder", 96: "thunder", 99: "thunder" };
  const WX_ICON = (c) => (c === 0 ? "sun" : c <= 2 ? "cloud-sun" : c === 3 ? "cloud" : c <= 48 ? "cloud-fog" : c <= 57 ? "cloud-drizzle" : c <= 67 ? "cloud-rain" : c <= 77 ? "cloud-snow" : c <= 82 ? "cloud-rain-wind" : c <= 86 ? "cloud-snow" : "cloud-lightning");
  const HORIZON_DAYS = 15;
  function clampRange(start, end) {
    const today = iso(new Date()), horizon = iso(new Date(Date.now() + HORIZON_DAYS * 864e5));
    let s = start && start > today ? start : today;
    let e = end && end < horizon ? end : horizon;
    if (s > horizon) s = today;
    if (e < s) e = iso(new Date(Date.parse(s) + 6 * 864e5));
    if (e > horizon) e = horizon;
    return { s, e, clipped: (start && start < today) || (end && end > horizon) || (start && start > horizon) };
  }
  async function fetchForecast(lat, lon, start, end) {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto&start_date=${start}&end_date=${end}`;
    const w = await (await fetch(url)).json();
    if (!w.daily || !w.daily.time || !w.daily.time.length) throw new Error("no forecast data");
    return w.daily;
  }
  let wxSeq = 0;
  async function loadWeather() {
    const t = trip();
    const seq = ++wxSeq;
    const { s, e, clipped } = clampRange(t.start, t.end);
    $("wx-where").textContent = `${fmtDay(s)} – ${fmtDay(e)}`;
    if (!t.to) { $("wx-to-temp").textContent = "—"; $("wx-to-sub").textContent = ""; $("wx-to-strip").innerHTML = ""; return; }
    $("wx-to-temp").textContent = "…"; $("wx-to-sub").textContent = t.to.name; $("wx-to-strip").innerHTML = "";
    $("wx-from-temp").textContent = "…"; $("wx-from-sub").textContent = t.from ? `Home, ${t.from.name}` : "Home";
    try {
      const [d, h] = await Promise.all([fetchForecast(t.to.lat, t.to.lon, s, e), t.from ? fetchForecast(t.from.lat, t.from.lon, s, e) : null]);
      if (seq !== wxSeq) return;
      const rain = (dd, i) => (dd.precipitation_probability_max && dd.precipitation_probability_max[i] != null ? dd.precipitation_probability_max[i] : null);
      $("wx-to-icon").innerHTML = ic(WX_ICON(d.weather_code[0]));
      $("wx-to-temp").textContent = `${Math.round(d.temperature_2m_max[0])}° / ${Math.round(d.temperature_2m_min[0])}°C`;
      $("wx-to-sub").textContent = `${t.to.name}, ${WX_CODES[d.weather_code[0]] || "—"}${rain(d, 0) != null ? `, ${rain(d, 0)}% rain` : ""}`;
      $("wx-to-strip").innerHTML = d.time.slice(0, 6).map((day, i) => `
        <div class="wx-day" title="${esc(day)}, ${esc(WX_CODES[d.weather_code[i]] || "")}">
          <span class="d">${new Date(day + "T12:00:00").toLocaleDateString("en", { weekday: "short" })}</span>
          <span class="i">${ic(WX_ICON(d.weather_code[i]))}</span>
          <span class="t">${Math.round(d.temperature_2m_max[i])}°</span>
        </div>`).join("");
      if (h) {
        const hiMax = Math.round(Math.max(...h.temperature_2m_max)), loMin = Math.round(Math.min(...h.temperature_2m_min));
        $("wx-from-icon").innerHTML = ic(WX_ICON(h.weather_code[0]));
        $("wx-from-temp").textContent = `${hiMax}° / ${loMin}°C`;
        $("wx-from-sub").textContent = `Home, ${t.from.name}, ${WX_CODES[h.weather_code[0]] || "—"}`;
      }
      icons();
    } catch {
      if (seq !== wxSeq) return;
      $("wx-to-temp").textContent = "—"; $("wx-to-sub").textContent = "Forecast unavailable"; $("wx-to-strip").innerHTML = "";
      $("wx-from-temp").textContent = "—"; $("wx-to-icon").innerHTML = ic("cloud-off"); icons();
    }
  }

  /* ---------- calendar ---------- */
  function eventFor(rec) {
    const t = trip();
    const endExclusive = new Date(Date.parse(t.end) + 864e5).toISOString().slice(0, 10);
    const title = `Visit to ${t.to ? t.to.name : t.stateName}`;
    const lines = [`${t.party}, travelling from ${t.from ? t.from.label : "home"} to ${t.to ? t.to.label : t.stateName}${t.with_ ? `, to be with ${t.with_}` : ""}.`];
    const recs = Object.values(answers);
    if (recs.length) {
      for (const r of recs) {
        const f = r.facts;
        const share = f.coverage === "empty" ? f.fallback_positive_share : f.positive_share;
        lines.push("", `${r.pathogenName || "SARS-CoV-2"} wastewater check for ${r.region}, ${f.window.start} to ${f.window.end}: ${pct(share)} of samples had the virus` + (f.direction ? `, ${f.direction}.` : "."), r.text);
      }
    } else lines.push("No wastewater check yet. Press \"Check the water\" on the planner before you go.");
    lines.push("", "Re-check before travelling: the data lags the calendar by about two weeks.", (rec && rec.disclaimer) || "Wastewater surveillance is a population-level signal, not medical or travel advice.");
    return { start: t.start, end: endExclusive, title, description: lines.join("\n"), location: t.to ? t.to.label : t.stateName };
  }
  function icsFor(rec) {
    const e = eventFor(rec);
    const d = (s) => s.replace(/-/g, "");
    const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
    const escape = (s) => String(s).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
    return ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//wastewater-agent//visit planner//EN", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
      `UID:${(rec && rec.id) || "trip"}-${Date.now()}@wastewater-agent`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${d(e.start)}`, `DTEND;VALUE=DATE:${d(e.end)}`,
      `SUMMARY:${escape(e.title)}`, `LOCATION:${escape(e.location)}`, `DESCRIPTION:${escape(e.description)}`,
      "BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${escape("Check the wastewater again for " + e.location)}`, "TRIGGER:-P2D", "END:VALARM",
      "END:VEVENT", "END:VCALENDAR", ""].join("\r\n");
  }
  function googleCalendarUrl(rec) {
    const e = eventFor(rec);
    const p = new URLSearchParams({ action: "TEMPLATE", text: e.title, dates: `${e.start.replace(/-/g, "")}/${e.end.replace(/-/g, "")}`, details: e.description, location: e.location });
    return `https://calendar.google.com/calendar/render?${p}`;
  }
  $("cal-ics").addEventListener("click", () => {
    const blob = new Blob([icsFor(current)], { type: "text/calendar;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${eventFor(current).title.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.ics`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  // The Google Calendar button is optional in the markup; skip it when absent.
  const gcal = $("cal-google");
  if (gcal) gcal.addEventListener("click", () => setGoogleLink(current));

  /* ---------- boot ---------- */
  icons();
  loadStatus();
  onTripChange();
  setGoogleLink(null);
  if (DEMO) check();
})();
