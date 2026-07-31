// SPDX-License-Identifier: Apache-2.0
/* All numbers rendered by this script come from build-generated JSON in
   assets/ (see make_demo_assets.py and assets/provenance.json). This file
   contains layout logic only; it must never define a result number. */

"use strict";

const $ = (sel, el) => (el || document).querySelector(sel);

async function fetchJSON(path, optional) {
  const r = await fetch(path).catch(() => null);
  if (!r || !r.ok) {
    if (optional) return null;
    throw new Error("missing asset: " + path);
  }
  return r.json();
}

const FMT = {
  acc1: v => v.toFixed(1),
  acc2: v => v.toFixed(2),
  acc3: v => v.toFixed(3),
  pct0: v => Math.round(v * 100) + "%",
  pct1: v => (v * 100).toFixed(1) + "%",
  sci: v => v.toExponential(0).replace("+", ""),
  sci2: v => v.toExponential(2).replace("+", ""),
  grp: v => v.toLocaleString("en-US"),
  int: v => String(v),
};

function fillNumbers(NUM) {
  document.querySelectorAll("[data-num]").forEach(el => {
    const v = NUM[el.dataset.num];
    if (v === undefined || v === null) {
      el.textContent = "?";
      el.classList.add("missing-num");
      return;
    }
    const f = FMT[el.dataset.fmt || "int"] || FMT.int;
    el.textContent = f(v);
  });
}

/* ---- Act 2: compare slider ---- */
function initCompare() {
  const stage = $("#compare .compare-stage");
  const top = $("#compare .compare-top");
  const handle = $("#compare .compare-handle");
  const range = $("#compare input[type=range]");
  const innerImg = top.querySelector("img");
  const baseImg = stage.querySelector("img");
  function size() {
    innerImg.style.width = baseImg.clientWidth + "px";
    innerImg.style.height = "auto";
  }
  function set(pct) {
    top.style.width = pct + "%";
    handle.style.left = pct + "%";
  }
  range.addEventListener("input", () => set(range.value));
  new ResizeObserver(size).observe(stage);
  baseImg.addEventListener("load", size);
  size();
  set(range.value);
}

/* ---- Act 3: channel gallery ---- */
const CHANNEL_TABS = [
  { key: "clean", title: "Clean render",
    blurb: "The marked page exactly as rendered, no channel." },
  { key: "wa", title: "WhatsApp",
    blurb: "Rotation, blur, WhatsApp-grade downscale and JPEG." },
  { key: "double", title: "Double hop",
    blurb: "A harsher first hop, then a second recompression." },
  { key: "harsh", title: "Harsh",
    blurb: "Strong rotation and blur, small output, low JPEG quality." },
];

function frac(ok, tot) { return ok + "/" + tot; }

function decodeRows(d) {
  const rows = [];
  if (d.aborted) {
    rows.push(`<div class="stat"><span>segmentation</span>
      <b>aborted (line count mismatch)</b></div>`);
    return rows.join("");
  }
  if (d.line_acc !== null && d.line_acc !== undefined)
    rows.push(`<div class="stat"><span>line-shift bits</span>
      <b>${frac(d.line_ok, d.line_tot)} = ${d.line_acc.toFixed(3)}</b></div>`);
  if (d.word_acc !== null && d.word_acc !== undefined)
    rows.push(`<div class="stat"><span>word-shift bits</span>
      <b>${frac(d.word_ok, d.word_tot)} = ${d.word_acc.toFixed(3)}</b></div>`);
  else if (d.erasures)
    rows.push(`<div class="stat"><span>word-shift bits</span>
      <b>erased (${d.erasures} erasures)</b></div>`);
  if (d.payload_tot)
    rows.push(`<div class="stat"><span>payload recovered</span>
      <b>${frac(d.payload_ok, d.payload_tot)} bits</b></div>`);
  if (d.deskew_deg !== undefined)
    rows.push(`<div class="stat"><span class="muted">deskew found</span>
      <span class="muted">${d.deskew_deg.toFixed(2)} deg</span></div>`);
  return rows.join("");
}

function initGallery(decs) {
  const tabs = $("#channel-tabs");
  const img = $("#gallery-image");
  const cap = $("#gallery-caption");
  const panel = $("#decode-panel");
  CHANNEL_TABS.forEach((t, i) => {
    const b = document.createElement("button");
    b.textContent = t.title;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", i === 0 ? "true" : "false");
    b.addEventListener("click", () => select(t, b));
    tabs.appendChild(b);
  });
  function select(t, btn) {
    tabs.querySelectorAll("button").forEach(b =>
      b.setAttribute("aria-selected", b === btn ? "true" : "false"));
    const d = decs[t.key];
    img.src = "assets/" + d.image.replace(/^.*[\\/]/, "");
    img.alt = "Marked page, " + t.title + ", simulated channel";
    cap.innerHTML = `<span class="tag">simulated channel</span> ${t.blurb}
      <span class="muted">(${d.cmdnote || "see provenance.json"})</span>`;
    panel.innerHTML = `<h4>Blind decode (decode.py)</h4>` + decodeRows(d) +
      verdictBadge(d);
    panel.setAttribute("data-variant", t.key);
  }
  select(CHANNEL_TABS[0], tabs.querySelector("button"));
}

function verdictBadge(d) {
  if (d.gate === "GO")
    return `<div class="verdict go">payload readable</div>`;
  return "";
}

/* ---- Act 3: score cards ---- */
function scoreCard(title, tagHTML, d, footer) {
  return `<div><h4>${title}</h4><p class="labelline">${tagHTML}</p>
    ${decodeRows(d)}${footer || ""}</div>`;
}

function initRealAndControls(real, decCtrlWA) {
  const rm = real.marked, rc = real.control;
  document.querySelectorAll("[data-real]").forEach(el => {
    const src = real[el.dataset.real];
    if (el.dataset.field === "line_frac")
      el.textContent = frac(src.line_ok, src.line_tot);
  });
  $("#real-marked-card").innerHTML = scoreCard(
    "Blind decode of the real capture",
    `<span class="tag tag-real">real capture (single dry-run print)</span>`,
    rm,
    `<div class="verdict go">smoke-test gate: ${rm.gate}</div>`);
  $("#ctrl-sim-card").innerHTML = scoreCard(
    "Unmarked control, simulated WhatsApp channel",
    `<span class="tag">simulated channel</span>`, decCtrlWA,
    `<div class="verdict chance">reads at chance</div>`);
  $("#ctrl-real-card").innerHTML = scoreCard(
    "Unmarked control, real capture",
    `<span class="tag tag-real">real capture (single dry-run print)</span>`,
    rc, `<div class="verdict chance">reads at chance</div>`);
}

/* ---- Act 4: tier table ---- */
function initTierTable(tiers) {
  const cols = [
    ["flip_0.5", "flip, power 0.5"],
    ["flip_0.9", "flip, power 0.9"],
    ["erasure_0.5", "erasure, power 0.5"],
    ["erasure_0.9", "erasure, power 0.9"],
  ];
  const fmt = v => v > 0 ? v.toFixed(3) : "infeasible";
  let html = `<div class="table-scroll"><table>
    <caption class="axis-label">Largest tolerable symbol-error rate that still
      clears the courtroom budget (${FMT.sci(tiers.budget)}), n = ${tiers.n}
      copies. Corrected hard-decision factor (1 - 2p).</caption>
    <tr><th>fragment scale</th><th>colluders c</th><th>symbols k</th>` +
    cols.map(c => `<th>${c[1]}</th>`).join("") + `</tr>`;
  tiers.rows.forEach(r => {
    html += `<tr><td>${r.name}</td><td>${r.c}</td><td>${r.k}</td>` +
      cols.map(c => `<td>${fmt(r[c[0]])}</td>`).join("") + `</tr>`;
  });
  html += "</table></div>";
  $("#tier-table").innerHTML = html;
  $("#fix-source").textContent = tiers.correction_source;
}

/* ---- Act 4: e-process animation ---- */
function initEProcess(traj) {
  const card = $("#eprocess-card");
  const canvas = $("#eprocess-canvas");
  if (!traj) {
    canvas.hidden = true;
    $("#eprocess-pending").hidden = false;
    return;
  }
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height, PAD = 46;
  const all = traj.guilty.concat(traj.innocent);
  const n = Math.max(...all.map(t => t.length));
  const maxLog = Math.max(
    Math.log10(traj.bar || 10) + 1,
    ...all.flat().filter(v => v > 0).map(v => Math.log10(v)));
  const x = i => PAD + (W - 2 * PAD) * i / (n - 1);
  const y = v => {
    const lv = Math.log10(Math.max(v, 1e-2));
    return H - PAD - (H - 2 * PAD) * (lv + 2) / (maxLog + 2);
  };
  let f = 0;
  function draw() {
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = "#2a3650"; ctx.fillStyle = "#b9b4a5";
    ctx.font = "11px Consolas, monospace";
    ctx.strokeRect(PAD, PAD, W - 2 * PAD, H - 2 * PAD);
    ctx.fillText("evidence (e-value, log scale)", PAD, PAD - 8);
    ctx.fillText("symbols observed as the leak drips", W / 2 - 90, H - 10);
    if (traj.bar) {
      ctx.strokeStyle = "#c9a227"; ctx.setLineDash([6, 5]);
      ctx.beginPath(); ctx.moveTo(PAD, y(traj.bar));
      ctx.lineTo(W - PAD, y(traj.bar)); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = "#c9a227";
      ctx.fillText("accusation bar", W - PAD - 100, y(traj.bar) - 6);
    }
    const upto = Math.max(2, Math.floor(f));
    function plot(ts, color, width) {
      ctx.strokeStyle = color; ctx.lineWidth = width;
      ts.forEach(t => {
        ctx.beginPath();
        t.slice(0, upto).forEach((v, i) => {
          const px = x(i), py = y(v);
          i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
        });
        ctx.stroke();
      });
      ctx.lineWidth = 1;
    }
    plot(traj.innocent, "#5c6a85", 1.2);
    plot(traj.guilty, "#c9a227", 1.8);
    ctx.fillStyle = "#c9a227"; ctx.fillText("guilty copy", PAD + 8, PAD + 16);
    ctx.fillStyle = "#5c6a85"; ctx.fillText("innocent copies (stay flat)",
                                            PAD + 8, PAD + 30);
    if (f < n) { f += n / 360; requestAnimationFrame(draw); }
  }
  // Render the completed chart immediately (so the panel is never blank,
  // including in print or offscreen capture), then replay the climb once
  // the card scrolls into view.
  f = n;
  draw();
  const io = new IntersectionObserver(es => {
    if (es.some(e => e.isIntersecting)) { f = 0; draw(); io.disconnect(); }
  });
  io.observe(card);
}

/* ---- Act 4: evidence curve (SVG) ---- */
function initCurve(curve) {
  const W = 900, H = 360, PAD = 55;
  const ks = curve.k, es = curve.epsilon1;
  const lx = v => Math.log10(v);
  const xmin = lx(ks[0]), xmax = lx(ks[ks.length - 1]);
  const clamped = es.map(v => Math.max(v, 1e-16));
  const ymin = -16, ymax = 0;
  const X = k => PAD + (W - 2 * PAD) * (lx(k) - xmin) / (xmax - xmin);
  const Y = e => H - PAD - (H - 2 * PAD) * (lx(e) - ymin) / (ymax - ymin);
  let path = "";
  ks.forEach((k, i) => {
    path += (i ? "L" : "M") + X(k).toFixed(1) + "," +
            Y(clamped[i]).toFixed(1) + " ";
  });
  let bounds = "";
  for (const [name, v] of Object.entries(curve.tier_bounds)) {
    bounds += `<line x1="${PAD}" x2="${W - PAD}" y1="${Y(v)}" y2="${Y(v)}"
      stroke="#2a3650" stroke-dasharray="5 5"/>
      <text x="${W - PAD - 4}" y="${Y(v) - 4}" text-anchor="end"
        class="axis-label">${name}</text>`;
  }
  $("#evidence-curve").innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" role="img"
       aria-label="False-accusation bound versus observed symbols, analytic curve from metrics.py">
      <rect x="${PAD}" y="${PAD}" width="${W - 2 * PAD}" height="${H - 2 * PAD}"
        fill="none" stroke="#2a3650"/>
      ${bounds}
      <path d="${path}" fill="none" stroke="#c9a227" stroke-width="2"/>
      <text x="${PAD}" y="${PAD - 10}" class="axis-label">
        false-accusation bound (log scale), flip semantics,
        error rate ${curve.p.toFixed(2)}, c = ${curve.c}</text>
      <text x="${W / 2}" y="${H - 12}" text-anchor="middle" class="axis-label">
        symbols observed in the leaked fragment (log scale)</text>
    </svg>`;
}

/* ---- Act 5: industries ---- */
const INDUSTRIES = [
  { key: "legal", title: "Legal discovery",
    who: "A party, reviewer or expert with lawful access to produced documents.",
    channel: "Photographed or scanned exhibit pages passed to press or " +
             "counterparties.",
    row: "single page",
    note: "Discovery copies go to named recipients, so the plausible " +
          "coalition is small and captures are typically flatbed scans, " +
          "far cleaner than a rushed phone photo." },
  { key: "manuscripts", title: "Manuscripts and award screeners",
    who: "A reviewer, judge or screener holding a numbered advance copy.",
    channel: "Photographed galley pages or screener excerpts posted online.",
    row: "single page",
    note: "Each screener copy has one recipient. A single leaked page of " +
          "clean capture already sits at the strongest rows of the table." },
  { key: "board", title: "Board minutes and briefs",
    who: "A director, observer or assistant with a numbered set of minutes " +
         "or a briefing paper.",
    channel: "A photographed page reaching a journalist or a trader.",
    row: "single page",
    note: "This fits the prose parts of a board pack: minutes, briefs, " +
          "memoranda of several pages of continuous text. Financial packs " +
          "and slide decks carry too few text lines to hold the mark; the " +
          "app checks and refuses those rather than tagging them silently. " +
          "Recipients are few, so the question is which of a handful leaked." },
  { key: "government", title: "Government documents",
    who: "A recipient on a controlled distribution list.",
    channel: "Photographed briefing pages passed to press.",
    row: "full paper",
    note: "Longer documents put more marked text in any substantial leak, " +
          "which is exactly what drives the guarantee toward the strongest " +
          "row of the table." },
];

function initIndustries(tiers) {
  const tabs = $("#industry-tabs");
  const card = $("#industry-card");
  const fmt = v => v > 0 ? v.toFixed(3) : "infeasible";
  INDUSTRIES.forEach((ind, i) => {
    const b = document.createElement("button");
    b.textContent = ind.title;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", i === 0 ? "true" : "false");
    b.addEventListener("click", () => select(ind, b));
    tabs.appendChild(b);
  });
  function select(ind, btn) {
    tabs.querySelectorAll("button").forEach(b =>
      b.setAttribute("aria-selected", b === btn ? "true" : "false"));
    const row = tiers.rows.find(r => r.name === ind.row);
    card.innerHTML = `<h3>${ind.title}</h3>
      <dl>
        <dt>who leaks</dt><dd>${ind.who}</dd>
        <dt>leak channel</dt><dd>${ind.channel}</dd>
        <dt>same primitive</dt><dd>${ind.note}</dd>
        <dt>the math row</dt><dd>"${row.name}" from the Act 4 table:
          c = ${row.c}, k = ${row.k} symbols, tolerated error rate
          ${fmt(row["flip_0.5"])} (power 0.5) or ${fmt(row["flip_0.9"])}
          (power 0.9), corrected flip semantics. Identical machinery,
          gentler channel.</dd>
      </dl>`;
  }
  select(INDUSTRIES[0], tabs.querySelector("button"));
}

/* ---- boot ---- */
(async function boot() {
  const prov = await fetchJSON("assets/provenance.json");
  fillNumbers(prov.numbers);
  initCompare();

  const decs = {};
  for (const t of CHANNEL_TABS)
    decs[t.key] = await fetchJSON(`assets/dec_${t.key}_marked.json`);
  initGallery(decs);

  const real = await fetchJSON("assets/real_capture.json");
  const ctrlWA = await fetchJSON("assets/dec_wa_control.json");
  initRealAndControls(real, ctrlWA);

  const tiers = await fetchJSON("assets/tiers.json");
  initTierTable(tiers);
  initIndustries(tiers);

  initCurve(await fetchJSON("assets/evidence_curve.json"));
  initEProcess(await fetchJSON("assets/eprocess_trajectories.json", true));
})();

/* ---- scroll-reveal (progressive enhancement: classes are added here, so
   users without JS simply see everything immediately) ---- */
(() => {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const targets = document.querySelectorAll(
    "main section, .statband, .realcap, .volcta");
  if (!("IntersectionObserver" in window)) return;
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        e.target.classList.add("reveal-in");
        io.unobserve(e.target);
      }
    }
  }, { threshold: 0.08 });
  targets.forEach((el) => {
    el.classList.add("reveal");
    io.observe(el);
  });
})();
