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
  /* ---------- the plan: one request, four agents, one composer ---------- */
  let currentPlan = null;
  const setGoogleLink = () => { const a = $("cal-google"); if (a) a.href = googleCalendarUrl(); };
  const LEVEL_WORD = { low: "low", moderate: "moderate", high: "high", unknown: "no data" };
  const SECTION_ICON = { covid: "biohazard", flu: "thermometer", pertussis: "baby", weather: "cloud-sun", guidance: "book-open" };
  function tripBody() {
    const t = trip();
    if (!t.to) throw new Error("Pick a destination city first");
    return { toCity: t.to.name, toState: t.to.stateCode, toCounty: t.to.county || null,
      fromCity: t.from ? t.from.name : "", fromState: t.from ? t.from.stateCode : t.to.stateCode,
      start: t.start, end: t.end, adults: t.adults, children: t.children, with: t.groups };
  }
  function trip() {
    const to = PLACE.to, from = PLACE.from;
    let start = $("trip-start").value, end = $("trip-end").value;
    if (start && end && end < start) end = start;
    const adults = Math.max(1, parseInt($("trip-adults").value, 10) || 1);
    const children = Math.max(0, parseInt($("trip-children").value, 10) || 0);
    const groups = [...document.querySelectorAll(".tog[aria-pressed=\"true\"]")].map((b) => b.dataset.group);
    const WORDS = { older_adult: "older adults", young_child: "young children", newborn: "a newborn", pregnant: "someone pregnant" };
    const with_ = groups.map((g) => WORDS[g]).join(", ").replace(/, ([^,]*)$/, " and $1");
    return { to, from, start, end, adults, children, groups, with_,
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
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--teal").trim() || "#1e56b3";
    marker = L.circleMarker(pos, { radius: 11, color: accent, fillColor: accent, fillOpacity: .35, weight: 2 }).addTo(map);
    const lines = currentPlan ? currentPlan.sections.filter((s) => ["covid", "flu", "weather"].includes(s.source) && s.status === "ok").map((s) => `${s.title}: ${LEVEL_WORD[s.level] || s.level}`) : [];
    marker.bindPopup(lines.length ? `<b>${esc(t.to.name)}</b><br>${lines.map(esc).join("<br>")}` : t.to.name);
    setTimeout(() => map.invalidateSize(), 60);
  }
  // Any edit to the trip makes the shown verdict out of date: the header goes back to its normal colour.
  /* The tagline speaks the verdict: red "Don't go" keeps the header shaking, amber "Think again..."
     ripples like a wave, green "Safe travel!" keeps confetti flying. Any trip edit restores the default. */
  const TAGLINE = { none: "Decide before you go", high: "Don't go", moderate: "Think again...", low: "Safe travel!" };
  const reduceMotion = () => !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  function setTagline(text, wave) {
    const el = document.querySelector(".tagline");
    el.setAttribute("aria-label", text);
    el.innerHTML = wave
      ? [...text].map((ch, i) => `<span class="wl" aria-hidden="true" style="--i:${i}">${ch === " " ? "&nbsp;" : esc(ch)}</span>`).join("")
      : esc(text);
  }
  function confetti(el) {
    const colours = ["#ffffff", "#ffd166", "#9ad1ff", "#ff9ec7", "#c6f5b5"];
    for (let i = 0; i < 30; i++) {
      const b = document.createElement("span"); b.className = "confetti-bit"; b.setAttribute("aria-hidden", "true");
      const a = Math.random() * Math.PI * 2, d = 24 + Math.random() * 46;
      b.style.setProperty("--dx", `${(Math.cos(a) * d * 1.8).toFixed(1)}px`);
      b.style.setProperty("--dy", `${(Math.sin(a) * d).toFixed(1)}px`);
      b.style.setProperty("--rot", `${Math.round(Math.random() * 720 - 360)}deg`);
      b.style.setProperty("--c", colours[i % colours.length]);
      b.style.animationDelay = `${Math.round(Math.random() * 1600)}ms`;  // staggered loops: a steady sprinkle
      el.appendChild(b);
    }
    // The pieces loop until the tagline is reset, which replaces them.
  }
  function setHeaderVerdict(level, effects = true) {
    document.querySelector(".topbar").className = `topbar verdict-${level}`;
    setTagline(TAGLINE[level] || TAGLINE.none, level === "moderate");
    // The wave, shake and confetti are states, not one-off effects: they also run for a restored plan.
    if (reduceMotion()) return;
    if (level === "low") confetti(document.querySelector(".tagline"));
  }
  const resetHeader = () => {
    const tb = document.querySelector(".topbar");
    if (tb.className === "topbar") return;  // already the default: keep typing cheap
    tb.className = "topbar"; setTagline(TAGLINE.none, false);
  };
  $("trip-form").addEventListener("input", resetHeader);
  function onTripChange() {
    resetHeader();
    const t = trip();
    if ($("trip-end").value && $("trip-start").value && $("trip-end").value < $("trip-start").value) $("trip-end").value = $("trip-start").value;
    $("w-adults").textContent = t.adults === 1 ? "adult" : "adults";
    $("w-children").textContent = t.children === 1 ? "child" : "children";
    $("hero-title").textContent = t.to ? `Visiting ${t.to.name}` : "Plan a visit";
    $("hero-dates").textContent = `${fmtDay(t.start)} – ${fmtDay(t.end)}`;
    $("hero-party").textContent = t.party.replace(" and ", ", ") + (t.with_ ? `, with ${t.with_}` : "");
    drawMap(t);
    if (currentPlan) setGoogleLink();
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
  // The page has one view; the top bar carries only the brand and the theme toggle.

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
  // "nvidia/nemotron-3-ultra-550b-a55b" -> "nemotron-3-ultra"; the full name stays in the tooltip.
  const shortModel = (m) => (m ? String(m).replace(/^nvidia\//, "").replace(/-\d+b(-a\d+b)?$/, "") : "");
  const modelHtml = (m) => `<span class="model" title="${esc(m)}">${esc(shortModel(m))}</span>`;
  const progress = {
    stageOf: null,  // the stage a route event belongs to ("plan" or "write")
    begin(title) {
      $("progress-title").textContent = title;
      $("progress-step").textContent = "Starting";
      $("progress-trail").innerHTML = "";
      $("answer-progress").classList.remove("open"); $("progress-toggle").setAttribute("aria-expanded", "false");  // folded by default
      $("answer-progress").classList.remove("hidden", "done");
      this.stageOf = null;
    },
    step(html) { $("progress-step").innerHTML = html; },
    trail(html, warn = false, seconds = null) {
      const li = document.createElement("li"); if (warn) li.className = "warn";
      li.innerHTML = `<span class="txt">${html}</span>` + (seconds != null ? `<span class="t">${Number(seconds).toFixed(1)} s</span>` : "");
      $("progress-trail").appendChild(li);
    },
    event(e) {
      const AGENT = { covid: "COVID-19 wastewater", flu: "Flu wastewater", pertussis: "Whooping cough", weather: "Weather", guidance: "CDC guidance" };
      const name = AGENT[e.stage] || e.stage;
      if (e.state === "route") {
        if (e.route_state === "start") this.step(`${name}: trying ${modelHtml(e.model)}`);
        else if (e.route_state === "failed") this.trail(`${name}: ${esc(shortModel(e.model))} failed, trying the next route`, true);
        return;
      }
      if (e.stage === "location") {
        if (e.state === "start") this.step(`Locating ${esc(e.city)} through Zetaris`);
        else if (e.state === "done") this.trail(`Location: ${esc(e.place)}${e.county ? `, ${esc(e.county)}` : ""} via Zetaris`, false, e.seconds);
        else this.trail(`Location: Zetaris lookup unavailable, using the page's county`, true);
        return;
      }
      if (e.stage === "evaluator" && e.state === "findings") {
        const reqs = e.requests || [];
        const what = (r) => `${AGENT[r.source] || r.source}${r.action === "state_level" ? " at state level" : ""}`;
        if (!reqs.length) this.trail("Evaluator: findings complete, nothing to ask again");
        else { this.trail(`Evaluator sent the planner back: ${reqs.map(what).join(", ")}`, true); this.step("Planner asking again"); }
        return;
      }
      if (e.retry) {
        const how = e.action === "state_level" ? "asked again at state level" : "asked again";
        if (e.state === "start") this.step(`${name}: ${how}`);
        else this.trail(`${name} (${how}): ${esc(LEVEL_WORD[e.level] || e.level || "not available")}, ${e.kept === "new" ? "new answer used" : "first answer kept"}`, e.kept !== "new", e.seconds);
        return;
      }
      if (e.stage === "evaluator") {
        if (e.state === "start") this.step(`Evaluator reviewing draft ${e.round}`);
        else this.trail(`Evaluator, draft ${e.round}: ${e.verdict === "pass" ? "pass" : `revise, ${e.issues} issue${e.issues === 1 ? "" : "s"}`}${e.model ? ` via ${modelHtml(e.model)}` : " (rules only)"}`, e.verdict !== "pass");
        return;
      }
      if (e.stage === "composer") {
        if (e.state === "start") this.step(`Composing the plan with ${modelHtml(e.model)}`);
        else if (e.state === "revise") this.step(`Composer revising, draft ${e.round}`);
        else { this.trail(`Plan composed by ${modelHtml(e.model)}`); this.step("Done"); }
        return;
      }
      if (e.state === "start") this.step(`${name}: running`);
      else if (e.state === "done") this.trail(`${name}: ${esc(LEVEL_WORD[e.level] || e.level)}${e.model ? ` via ${modelHtml(e.model)}` : ""}`, false, e.seconds);
      else if (e.state === "failed") this.trail(`${name}: not available (${esc(String(e.error || "").slice(0, 80))})`, true, e.seconds);
    },
    finish() {
      $("answer-progress").classList.add("done"); $("progress-step").textContent = "Done";
      // Close itself after a while, unless someone opened the details to read them.
      setTimeout(() => { if (!$("answer-progress").classList.contains("open")) $("answer-progress").classList.add("hidden"); }, 6000);
    },
  };
  $("progress-toggle").addEventListener("click", () => {
    const open = $("answer-progress").classList.toggle("open");
    $("progress-toggle").setAttribute("aria-expanded", open ? "true" : "false");
  });
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
  async function planStream(body, onEvent) {
    const res = await fetch("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, stream: true }) });
    if (!res.ok || !(res.headers.get("content-type") || "").includes("ndjson")) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `${res.status} ${res.statusText}`);
    }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "", plan = null;
    for (;;) {
      const { value, done } = await reader.read();
      buf += done ? dec.decode() : dec.decode(value, { stream: true });
      const lines = buf.split("\n"); buf = done ? "" : lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const e = JSON.parse(line);
        if (e.stage === "plan") plan = e.plan;
        else if (e.stage === "error") throw new Error(e.error);
        else onEvent(e);
      }
      if (done) break;
    }
    if (!plan) throw new Error("the connection closed before the plan arrived");
    return plan;
  }
  async function planVisit() {
    let body;
    try { body = tripBody(); } catch (e) { $("plan-error").textContent = e.message; $("plan-error").classList.remove("hidden"); return; }
    $("visit-submit").disabled = true;
    $("plan-error").classList.add("hidden");
    progress.begin(`Planning the visit to ${body.toCity}`);
    try {
      const plan = DEMO ? await demoPlan(body) : await planStream(body, (e) => progress.event(e));
      renderPlan(plan);
      progress.finish();
    } catch (e) {
      $("plan-error").textContent = `The plan didn't complete: ${e.message.split("\n")[0]}. Try again in a moment.`;
      $("plan-error").classList.remove("hidden");
      $("answer-progress").classList.add("hidden");
    } finally {
      $("visit-submit").disabled = false;
      if (!DEMO) loadStatus();
    }
  }
  $("visit-submit").addEventListener("click", planVisit);
  const LEVEL_UI = {
    low: { icon: "circle-check", word: "Low risk", cls: "low" },
    moderate: { icon: "triangle-alert", word: "Moderate risk", cls: "moderate" },
    high: { icon: "octagon-alert", word: "High risk", cls: "high" },
    unknown: { icon: "circle-help", word: "No recent data", cls: "unknown" },
    error: { icon: "circle-off", word: "Unavailable", cls: "error" },
    skipped: { icon: "circle-off", word: "Not covered", cls: "error" },
    guidance: { icon: "book-open", word: "Advice", cls: "guidance" },
  };
  // The guidance agent's briefing is lines: a heading, "- " bullets, a closing note.
  function guidanceParts(text) {
    const lines = String(text || "").split("\n").map((l) => l.trim()).filter(Boolean);
    const bullets = lines.filter((l) => l.startsWith("- ")).map((l) => l.slice(2));
    const rest = lines.filter((l) => !l.startsWith("- "));
    return { bullets, note: rest.slice(1).join(" ") };
  }
  function renderSection(s) {
    const isGuide = s.source === "guidance";
    const key = isGuide ? "guidance" : (s.status === "ok" ? s.level : s.status);
    const L = LEVEL_UI[key] || LEVEL_UI.unknown;
    const g = isGuide ? guidanceParts(s.text) : null;
    const facts = isGuide ? g.bullets : s.facts;
    const caveats = isGuide ? [...s.caveats, g.note].filter(Boolean) : s.caveats;
    const meaning = s.meaning || (s.status === "ok" ? s.headline : "");
    const det = document.createElement("details");
    det.className = `section ${L.cls}`;
    det.id = `ps-${s.source}`;
    det.innerHTML = `
      <summary>
        <span class="sec-ic">${ic(L.icon)}</span>
        <span class="sec-title">${esc(s.title)}</span>
        <span class="sec-level">${esc(L.word)}</span>
        <span class="sec-chev">${ic("chevron-down")}</span>
      </summary>
      <div class="sec-body">
        ${meaning ? `<p class="sec-meaning">${esc(meaning)}</p>` : ""}
        ${facts.length ? `<ul class="plan-points">${facts.map((x) => `<li>${ic("dot")}<span>${esc(x)}</span></li>`).join("")}</ul>` : ""}
        ${caveats.map((c) => `<p class="caveat">${esc(c)}</p>`).join("")}
        ${s.status !== "ok" ? `<div class="plan-error" role="alert">${esc(s.error || "not available")}</div>` : ""}
        ${!isGuide && s.status === "ok" && s.text ? `<details class="sec-full"><summary>Full answer from the agent${s.model ? ` (${esc(shortModel(s.model))})` : ""}</summary><p class="plan-text">${esc(s.text)}</p></details>` : ""}
      </div>`;
    return det;
  }
  function renderPlan(plan, opts = {}) {
    currentPlan = plan;
    const v = plan.verdict;
    $("plan-empty").classList.add("hidden");
    const banner = $("plan-verdict"); banner.className = `verdict ${v.level}`;
    // The header and tagline take the verdict until the trip is edited; a restored plan skips the effects.
    setHeaderVerdict(v.level, !opts.restored);
    const TAG = { low: "Good to go", moderate: "Go with care", high: "Reconsider, or go with full precautions", unknown: "Not enough data to judge" };
    const OLD_LABEL = { "Green light": "Go", "Amber light": "Caution", "Red light": "Stop" };  // plans stored before the rename
    if (OLD_LABEL[v.label]) v.label = OLD_LABEL[v.label];
    $("verdict-label").textContent = v.label; $("verdict-reason").textContent = v.reason;
    $("plan-intro").textContent = plan.intro; $("plan-intro").classList.remove("hidden");
    const box = $("plan-sections"); box.innerHTML = "";
    plan.sections.forEach((s) => box.appendChild(renderSection(s)));
    const ticked = checksFor(plan);
    $("precautions-list").innerHTML = plan.precautions.map((x, i) =>
      `<li><label><input type="checkbox" data-i="${i}"${ticked.has(x) ? " checked" : ""}><span>${esc(x)}</span></label></li>`).join("");
    $("plan-precautions").classList.toggle("hidden", !plan.precautions.length);
    $("best-days").textContent = plan.bestDays.join(", ");
    $("plan-best").classList.toggle("hidden", !plan.bestDays.length);
    $("sources-list").innerHTML = plan.sources.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join("");
    $("models-line").textContent = "Written by " + Object.entries(plan.models).filter(([, m]) => m).map(([k, m]) => `${k}: ${m}`).join("; ") + (plan.partial ? ". Some sources were unavailable." : "");
    const ev = plan.evaluation || {}, evLine = $("eval-line");
    if (evLine) {
      const n = (ev.rounds || []).length;
      evLine.textContent = !n ? "" : ev.final === "pass"
        ? `Checked by the evaluator: passed on draft ${ev.chosenRound} of ${n}.`
        : `Checked by the evaluator: no draft passed after ${n} reviews; showing draft ${ev.chosenRound}. Open points: ${(ev.unresolved || []).join(" ")}`;
      const asked = (ev.replans || []).flatMap((rp) => rp.requests);
      if (asked.length) evLine.textContent += " The evaluator had the planner ask again for: " + asked.map((r) =>
        `${r.source}${r.action === "state_level" ? " at state level" : ""} (${r.kept === "new" ? "new answer used" : "first answer kept"})`).join(", ") + ".";
    }
    $("plan-sources").classList.remove("hidden");
    $("plan-dl").classList.remove("hidden");
    if (!DEMO) saveState(plan);
    setGoogleLink();
    drawMap(trip());
    icons();
  }
  /* ---------- the last plan survives a refresh (this browser only) ---------- */
  const STATE_KEY = "visit-planner.lastPlan";
  function saveState(plan) {
    try {
      localStorage.setItem(STATE_KEY, JSON.stringify({ plan, to: PLACE.to, from: PLACE.from, start: $("trip-start").value, end: $("trip-end").value,
        adults: $("trip-adults").value, children: $("trip-children").value, groups: trip().groups }));
    } catch {}
  }
  function restoreState() {
    let s = null;
    try { s = JSON.parse(localStorage.getItem(STATE_KEY) || "null"); } catch {}
    if (!s || !s.plan || !s.plan.verdict) return false;
    if (s.to) { PLACE.to = s.to; $("trip-to").value = s.to.name; }
    if (s.from) { PLACE.from = s.from; $("trip-from").value = s.from.name; }
    if (s.start) $("trip-start").value = s.start;
    if (s.end) $("trip-end").value = s.end;
    if (s.adults) $("trip-adults").value = s.adults;
    if (s.children != null) $("trip-children").value = s.children;
    document.querySelectorAll(".tog").forEach((b) => b.setAttribute("aria-pressed", (s.groups || []).includes(b.dataset.group) ? "true" : "false"));
    onTripChange();
    renderPlan(s.plan, { restored: true });
    return true;
  }
  /* ---------- the "Before you go" ticks: saved per plan in this browser, kept across refreshes ---------- */
  const CHECKS_KEY = "visit-planner.checks";
  function checksFor(plan) {
    try {
      const s = JSON.parse(localStorage.getItem(CHECKS_KEY) || "null");
      if (s && s.planId === plan.id) return new Set(s.done || []);
    } catch {}
    return new Set();  // a different (or new) plan starts with nothing ticked
  }
  function saveChecks() {
    if (!currentPlan) return;
    const done = [...$("precautions-list").querySelectorAll("input:checked")].map((c) => currentPlan.precautions[+c.dataset.i]);
    try { localStorage.setItem(CHECKS_KEY, JSON.stringify({ planId: currentPlan.id, done })); } catch {}
  }
  $("precautions-list").addEventListener("change", (ev) => { if (ev.target.matches("input[type=checkbox]")) saveChecks(); });
  async function demoPlan(body) {
    const plan = await (await fetch("sample-plan.json")).json();
    plan.id = "plan_demo_" + Date.now().toString(36); plan.createdAt = new Date().toISOString();
    const pause = (ms) => new Promise((r) => setTimeout(r, ms));
    const loc = (plan.trip || {}).location;
    if (loc) { progress.event({ stage: "location", state: "start", city: loc.name }); await pause(300); progress.event({ stage: "location", state: "done", place: `${loc.name}, ${loc.state}`, county: loc.county, table: loc.table, seconds: loc.seconds }); }
    // Sections hold the final answers; for sources the evaluator had re-asked, the first pass shows what came back first.
    const firstPass = {};
    for (const rp of ((plan.evaluation || {}).replans || [])) for (const r of rp.requests) if (!(r.source in firstPass)) firstPass[r.source] = r.before;
    for (const s of plan.sections) {
      const b = firstPass[s.source], status = b ? b.status : s.status, level = b ? b.level : s.level;
      progress.event({ stage: s.source, state: "start" }); await pause(250);
      progress.event({ stage: s.source, state: status === "ok" ? "done" : "failed", level, model: s.model, seconds: s.seconds, error: b ? b.headline : s.error });
    }
    for (const rp of ((plan.evaluation || {}).replans || [])) {
      progress.event({ stage: "evaluator", state: "findings", round: rp.round, requests: rp.requests }); await pause(300);
      for (const r of rp.requests) {
        progress.event({ stage: r.source, state: "start", retry: true, action: r.action }); await pause(300);
        const k = r.kept === "new" ? r.after : r.before;
        progress.event({ stage: r.source, state: k.status === "ok" ? "done" : "failed", retry: true, action: r.action, kept: r.kept, level: k.level });
      }
    }
    if (!((plan.evaluation || {}).replans || []).length) progress.event({ stage: "evaluator", state: "findings", round: 1, requests: [] });
    progress.event({ stage: "composer", state: "start", model: plan.models.composer }); await pause(400);
    for (const r of ((plan.evaluation || {}).rounds || [])) {
      if (r.round > 1) { progress.event({ stage: "composer", state: "revise", round: r.round }); await pause(300); }
      progress.event({ stage: "evaluator", state: "start", round: r.round }); await pause(300);
      progress.event({ stage: "evaluator", state: "done", round: r.round, verdict: r.verdict, issues: r.issues.length, model: r.model });
    }
    progress.event({ stage: "composer", state: "done", model: plan.models.composer, level: plan.verdict.level, seconds: plan.elapsedSeconds });
    return plan;
  }

  // The plan's points: the figures, who you'll be with, and when to check again.
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
  function eventFor() {
    const t = trip(), p = currentPlan;
    const endExclusive = new Date(Date.parse(t.end) + 864e5).toISOString().slice(0, 10);
    const title = `Visit to ${t.to ? t.to.name : t.stateName}`;
    const lines = [`${t.party}, travelling from ${t.from ? t.from.label : "home"} to ${t.to ? t.to.label : t.stateName}${t.with_ ? `, to be with ${t.with_}` : ""}.`];
    if (p) {
      lines.push("", `${p.verdict.label}: ${p.verdict.reason}`, "", p.intro, "", "Before you go:");
      lines.push(...p.precautions.map((x) => `- ${x}`));
      if (p.bestDays.length) lines.push("", "Best days outdoors: " + p.bestDays.join(", "));
    } else lines.push("No plan yet. Press \"Plan this visit\" on the planner before you go.");
    lines.push("", "Re-check before travelling: health data lags the calendar by about two weeks.", "Summarises CDC and NWS data through the team's agents. Not medical advice; check with a healthcare provider about anything health-related.");
    return { start: t.start, end: endExclusive, title, description: lines.join("\n"), location: t.to ? t.to.label : t.stateName };
  }
  /* ---------- report: the plan as a Markdown file, built here so demo mode works too ---------- */
  function reportMarkdown(p) {
    const t = trip(), v = p.verdict, tr = p.trip || {};
    const to = `${tr.toCity || (t.to && t.to.name) || ""}, ${(tr.toState || (t.to && t.to.stateCode) || "").toUpperCase()}`;
    const from = tr.fromCity ? `${tr.fromCity}, ${String(tr.fromState || "").toUpperCase()}` : (t.from ? t.from.label : "home");
    const groups = (tr.with || t.groups || []).join(", ") || "none stated";
    const L = [`# Travel plan: ${to}`, "",
      `${tr.start || t.start} to ${tr.end || t.end}, from ${from}; ${tr.adults ?? t.adults} adults, ${tr.children ?? t.children} children; with: ${groups}.`, "",
      `## ${v.label}: ${v.tagline || ""} (${v.level})`, "", v.reason, "", p.intro, ""];
    for (const s of p.sections) {
      L.push(`## ${s.title}  (${s.status === "ok" ? s.level : s.status})`, "");
      if (s.meaning) L.push(s.meaning, "");
      const facts = s.source === "guidance" ? guidanceParts(s.text).bullets : s.facts;
      L.push(...facts.map((x) => `- ${x}`));
      L.push(...s.caveats.map((c) => `- Caveat: ${c}`));
      if (s.status !== "ok") L.push(`- Not available: ${s.error || ""}`);
      if (s.source !== "guidance" && s.status === "ok" && s.text) L.push("", `> ${s.text.replace(/\n/g, "\n> ")}`);
      L.push("");
    }
    const done = checksFor(p);
    L.push("## Before you go", "", ...p.precautions.map((x) => `- [${done.has(x) ? "x" : " "}] ${x}`), "");
    if (p.bestDays.length) L.push("## Best days outdoors", "", p.bestDays.join(", "), "");
    L.push("## Sources", "", ...p.sources.map((s) => `- [${s.title}](${s.url})`), "");
    const ev = p.evaluation || {};
    if ((ev.rounds || []).length) {
      L.push("## Evaluation", "", `${ev.final} after ${ev.rounds.length} review(s); kept draft ${ev.chosenRound}.`, "");
      for (const rp of (ev.replans || [])) for (const r of rp.requests)
        L.push(`- Asked again: ${r.source} (${r.action}): ${r.reason}; ${r.before.level} -> ${r.after.level}, kept the ${r.kept} answer`);
      if ((ev.replans || []).length) L.push("");
      for (const r of ev.rounds) {
        L.push(`- Round ${r.round}: ${r.verdict}${r.model ? ` (${r.model})` : " (rules only)"}`, ...r.issues.map((i) => `  - ${i}`));
      }
      L.push("");
    }
    L.push("## Models", "", ...Object.entries(p.models).map(([k, m]) => `- ${k}: ${m || "none"}`), "");
    if (p.notes && p.notes.length) L.push("## Notes", "", ...p.notes.map((n) => `- ${n}`), "");
    L.push(`Generated ${p.createdAt} in ${p.elapsedSeconds} s${p.partial ? " (partial)" : ""}.`, "",
      "Summarises CDC and NWS data through the team's agents. Not medical advice; check with a healthcare provider about anything health-related.", "");
    return L.join("\n");
  }
  function downloadText(name, text, type) {
    const blob = new Blob([text], { type });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  function reportText(p) {
    // The Markdown report without its markup: headings as plain lines, boxes as [ ].
    return reportMarkdown(p).split("\n").map((l) => l.replace(/^#+\s*/, "").replace(/^- \[ \] /, "[ ] ").replace(/^- /, "\u2022 ").replace(/^> /, "    ").replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 ($2)")).join("\n");
  }
  function planFilename(ext) {
    const tr = currentPlan.trip || {}, t = trip();
    const city = (tr.toCity || (t.to && t.to.name) || "visit").toLowerCase().replace(/[^a-z0-9]+/g, "-");
    return `visit-plan-${city}-${tr.start || t.start}.${ext}`;
  }
  const dlMenu = $("plan-dl"), dlList = $("plan-dl-list"), dlToggle = $("plan-dl-btn");
  const closeMenu = () => { dlList.classList.add("hidden"); dlToggle.setAttribute("aria-expanded", "false"); };
  dlToggle.addEventListener("click", (ev) => { ev.stopPropagation(); const open = dlList.classList.toggle("hidden"); dlToggle.setAttribute("aria-expanded", open ? "false" : "true"); });
  document.addEventListener("click", (ev) => { if (!dlMenu.contains(ev.target)) closeMenu(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeMenu(); });
  dlList.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-fmt]"); if (!b || !currentPlan) return;
    closeMenu();
    const fmt = b.dataset.fmt;
    if (fmt === "md") downloadText(planFilename("md"), reportMarkdown(currentPlan), "text/markdown;charset=utf-8");
    else if (fmt === "txt") downloadText(planFilename("txt"), reportText(currentPlan), "text/plain;charset=utf-8");
    else if (fmt === "json") downloadText(planFilename("json"), JSON.stringify(currentPlan, null, 2), "application/json;charset=utf-8");
    else if (fmt === "pdf") { document.querySelectorAll("#plan-sections details, #plan-sources").forEach((d) => { d.open = true; }); window.print(); }
  });
  function icsFor() {
    const e = eventFor();
    const d = (s) => s.replace(/-/g, "");
    const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
    const escape = (s) => String(s).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
    return ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//wastewater-agent//visit planner//EN", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
      `UID:${(currentPlan && currentPlan.id) || "trip"}-${Date.now()}@visit-planner`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${d(e.start)}`, `DTEND;VALUE=DATE:${d(e.end)}`,
      `SUMMARY:${escape(e.title)}`, `LOCATION:${escape(e.location)}`, `DESCRIPTION:${escape(e.description)}`,
      "BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${escape("Check the wastewater again for " + e.location)}`, "TRIGGER:-P2D", "END:VALARM",
      "END:VEVENT", "END:VCALENDAR", ""].join("\r\n");
  }
  function googleCalendarUrl() {
    const e = eventFor();
    const p = new URLSearchParams({ action: "TEMPLATE", text: e.title, dates: `${e.start.replace(/-/g, "")}/${e.end.replace(/-/g, "")}`, details: e.description, location: e.location });
    return `https://calendar.google.com/calendar/render?${p}`;
  }
  $("cal-ics").addEventListener("click", () => {
    const blob = new Blob([icsFor()], { type: "text/calendar;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${eventFor().title.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.ics`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  // The Google Calendar button is optional in the markup; skip it when absent.
  const gcal = $("cal-google");
  if (gcal) gcal.addEventListener("click", () => setGoogleLink());

  /* ---------- boot ---------- */
  icons();
  loadStatus();
  onTripChange();
  setGoogleLink();
  if (DEMO) planVisit();
  else restoreState();
})();
