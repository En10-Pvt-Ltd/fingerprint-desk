// SPDX-License-Identifier: Apache-2.0
/* Fingerprint Desk: guided crowdsourcing flow. Hash-routed views over the
   session-authenticated API. Kept deliberately non-technical: the raw score
   table only appears inside a collapsed "technical details" block. */
"use strict";

/* The one place the app's name lives in JS. Rebrand = change this line plus
   the <title> in index.html and admin.html. */
const APP_NAME = "Fingerprint Desk";

const view = document.getElementById("view");
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

let ME = null;      // {email, name, picture, is_admin, csrf} or null
let CFG = {max_variants: 5, capture_enums: {}, oauth_configured: false};
let LAST_TEST_RENDERED = null;   // avoid skeleton flash on poll re-renders
let SHARE_WARNING = null;        // capacity_warning carried across a re-render

async function api(path, opts) {
  opts = opts || {};
  if (opts.method && opts.method !== "GET" && ME) {
    opts.headers = Object.assign({"X-CSRF-Token": ME.csrf},
                                 opts.headers || {});
  }
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (r.status === 401) { ME = null; renderNav(); viewSignin(); throw new Error("signed out"); }
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}
const postJSON = (path, data) => api(path, {
  method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify(data)});

/* Pack-code flow is anonymous by design: no session, no CSRF header. The
   server shows human-readable guidance in "detail" on 400/404/429 — always
   surface it. */
async function packApi(path, opts) {
  const r = await fetch(path, opts || {});
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(body.detail || r.statusText || ("HTTP " + r.status));
    e.status = r.status;
    throw e;
  }
  return body;
}

const fmtDate = iso => iso ? new Date(iso).toLocaleString() : "";
const pct = v => v == null ? "n/a" : (v * 100).toFixed(1) + "%";
const sci = v => v == null ? "n/a" : v.toExponential(1);

/* brand text derived from APP_NAME: last word gets the gold accent */
function brandHTML() {
  const words = APP_NAME.split(" ");
  const last = words.pop();
  return `${esc(words.join(" "))} <span>${esc(last)}</span>`;
}

const skeletonPage = () => `
  <div class="skel skel-title"></div>
  <div class="skel skel-row"></div>
  <div class="skel skel-row"></div>
  <div class="skel skel-card"></div>`;

const busy = text => `<div class="busy"><span class="spin"></span>
  <span class="muted">${text}</span></div>`;

/* ---------------- boot / auth ---------------- */
async function boot() {
  const brand = document.getElementById("brand");
  if (brand) brand.innerHTML = brandHTML();
  try { CFG = await api("/api/config"); } catch (e) { /* keep defaults */ }
  try {
    const r = await fetch("/api/me");
    ME = r.ok ? await r.json() : null;
  } catch (e) { ME = null; }
  renderNav();
  route();
}

function renderNav() {
  const nav = document.getElementById("topnav");
  if (!ME) { nav.innerHTML = `<a class="btn btn-gold" href="#/">Sign in</a>`; return; }
  nav.innerHTML = `
    <a href="#/">My tests</a>
    <a href="#/new" class="btn btn-gold">Start a test</a>
    ${ME.is_admin ? `<a href="/admin">Admin</a>` : ""}
    <span class="muted small">${esc(ME.name || ME.email)}</span>
    <a href="#" id="signout" class="muted small">sign out</a>`;
  document.getElementById("signout").onclick = async e => {
    e.preventDefault();
    try { await api("/auth/logout", {method: "POST"}); } catch (err) {}
    ME = null; renderNav(); location.hash = "#/"; viewSignin();
  };
}

function viewSignin() {
  view.innerHTML = `
  <section class="hero">
    <div class="hero-grid">
      <div>
        <p class="kicker">A crowd-sourced forensics experiment</p>
        <h1 style="margin-top:0">Can a phone photo betray which printed
        copy it came from?</h1>
        <p class="lede">We hide an <strong>invisible fingerprint in how a
        page is printed</strong> — position shifts of a few hundredths of a
        millimetre, undetectable to the eye. It works in the lab. We need
        your printer, your phone and your lighting to find out if it
        survives the real world.</p>
        <div class="hero-ctas">
          <a class="btn btn-gold btn-lg" href="#packstart"
             data-scrollto="packstart">I have a print pack</a>
          <a class="btn btn-ghost btn-lg" href="#ownersignin"
             data-scrollto="ownersignin">Sign in to run a campaign</a>
        </div>
      </div>
      <div>
        <div class="exhibit" role="img"
             aria-label="Stylized document whose middle line of text shifts
subtly while a scan beam sweeps across it">
          <div class="docline mid"></div>
          <div class="docline"></div>
          <div class="docline shifty"></div>
          <div class="docline"></div>
          <div class="docline mid"></div>
          <div class="docline short"></div>
          <div class="docline"></div>
          <div class="docline shifty"></div>
          <div class="docline short"></div>
          <div class="scanbeam"></div>
          <div class="stamp">exhibit &middot; marked copy</div>
        </div>
        <p class="exhibit-cap">the shift, exaggerated a thousandfold for
          the eye</p>
      </div>
    </div>
  </section>

  <h2 style="margin-top:1.6rem">How the experiment works</h2>
  <ol class="chain">
    <li><strong>Print</strong> your test sheets at <strong>100%
      scale</strong> ("Actual size" — never "Fit to page"). They look
      identical; the hidden marks differ.</li>
    <li><strong>Photograph</strong> each sheet flat on a table in normal
      room light, page filling the frame. Sending the photo through
      WhatsApp first is encouraged — that's part of the test.</li>
    <li><strong>Upload</strong> the photos here. Don't edit, crop or
      enhance them.</li>
    <li><strong>See the reveal.</strong> We tell you what the hidden marks
      said — and whether we got it right.</li>
  </ol>

  <div class="grid2" style="margin-top:1.5rem">
    <div class="card" id="packstart" style="margin:0">
      <p class="kicker">No account needed</p>
      <h3 style="color:var(--ink)">I have a print pack</h3>
      <p class="muted small">Got three test sheets with a code like
      <code>FP001</code> on them? Enter the pack code to download your
      sheets and upload your photos.</p>
      <form id="packform">
        <label class="f" for="packcode">Pack code</label>
        <input type="text" id="packcode" class="packcode" placeholder="FP001"
               maxlength="5" autocomplete="off" autocapitalize="characters"
               spellcheck="false">
        <div class="actionbar" style="margin-top:0.9rem">
          <button class="btn btn-gold" type="submit">Open my pack</button>
        </div>
        <p class="muted small" id="packerr"></p>
      </form>
    </div>
    <div class="card" id="ownersignin" style="margin:0">
      <p class="kicker">Campaign owners</p>
      <h3 style="color:var(--ink)">Sign in to run tests</h3>
      <p class="muted small">Upload a document, generate marked copies, and
      recruit contributors.</p>
      ${CFG.oauth_configured
        ? `<div class="actionbar"><a class="btn btn-gold btn-lg"
             href="/auth/login">Sign in with Google to start</a></div>`
        : CFG.dev_login
        ? `<form id="devlogin" class="rowline" style="margin-top:1rem">
             <input type="email" id="devemail" placeholder="you@example.com"
                    required style="flex:1;min-width:12rem">
             <button class="btn btn-gold" type="submit">Sign in (local dev)</button>
           </form>
           <p class="muted small">Local development sign-in — no password. This
           form never appears on a production server.</p>`
        : `<p class="note">Sign-in is not configured on this server yet.</p>`}
      <p class="muted small" style="margin-top:1rem">We store your email (to
      count contributions), your uploaded documents and photos, and your
      correct/wrong answers. Only upload things you are comfortable sharing
      with the research team.</p>
    </div>
  </div>`;
  const form = document.getElementById("devlogin");
  if (form) form.onsubmit = async e => {
    e.preventDefault();
    try {
      await postJSON("/auth/dev-login",
                     {email: document.getElementById("devemail").value});
      await boot();
    } catch (err) { alert("dev sign-in failed: " + err.message); }
  };
  /* smooth-scroll CTAs without touching location.hash (which would
     re-route) */
  view.querySelectorAll("[data-scrollto]").forEach(a => a.onclick = e => {
    e.preventDefault();
    const el = document.getElementById(a.dataset.scrollto);
    if (el) el.scrollIntoView({behavior: "smooth", block: "start"});
    if (a.dataset.scrollto === "packstart") {
      const pi = document.getElementById("packcode");
      if (pi) setTimeout(() => pi.focus({preventScroll: true}), 400);
    }
  });
  const packInput = document.getElementById("packcode");
  packInput.addEventListener("input",
    () => { packInput.value = packInput.value.toUpperCase(); });
  document.getElementById("packform").onsubmit = e => {
    e.preventDefault();
    const code = packInput.value.trim().toUpperCase();
    if (!/^FP\d{3}$/.test(code)) {
      document.getElementById("packerr").textContent =
        'Pack codes look like "FP001" — the letters FP plus three digits.';
      return;
    }
    location.hash = "#/pack/" + code;
  };
}

/* ---------------- pack-code flow (anonymous, no auth) ---------------- */
const PACK_OUTCOMES = {
  "read-correct":       {good: true,  title: "We read the hidden mark — correctly"},
  "read-wrong":         {good: false, title: "We read a mark — but got it wrong"},
  "unreadable":         {good: false, title: "We couldn't read this photo"},
  "control-passed":     {good: true,  title: "Control sheet — correctly read as unmarked"},
  "control-false-alarm":{good: false, title: "Control sheet — we saw a mark that wasn't there"},
};

async function viewPack(packId) {
  packId = String(packId || "").trim().toUpperCase();
  view.innerHTML = skeletonPage();
  if (!/^FP\d{3}$/.test(packId)) {
    view.innerHTML = packErrorHTML(packId,
      'That doesn\'t look like a pack code. Codes look like "FP001" — the '
      + "letters FP plus three digits, printed on your sheets.");
    return;
  }
  let p;
  try {
    p = await packApi("/api/packs/" + encodeURIComponent(packId));
  } catch (e) {
    view.innerHTML = packErrorHTML(packId, e.message);
    return;
  }
  renderPack(p, null);
}

function packErrorHTML(packId, msg) {
  return `
  <h1>Print pack ${esc(packId)}</h1>
  <div class="card empty">
    <span class="e-mark">?</span>
    <p>${esc(msg)}</p>
    <p class="muted small">Double-check the code printed on your test
    sheets, or ask the person who gave you the pack.</p>
    <a class="btn btn-gold" href="#/">Back to the start</a>
  </div>`;
}

function packRulesHTML() {
  return `${printWarning()}
  <div class="note">
    <strong>1.</strong> Print all three sheets at 100% scale, as above.<br>
    <strong>2.</strong> Photograph each sheet <strong>flat on a
    table</strong> in normal room light, with the page filling the
    frame.<br>
    <strong>3.</strong> Sending each photo through <strong>WhatsApp</strong>
    first (to yourself is fine) is encouraged — surviving messaging apps is
    exactly what we're testing.<br>
    <strong>4.</strong> <strong>Don't edit, crop or enhance</strong> the
    photos — upload them exactly as they come out of the camera or chat.
  </div>`;
}

function renderPack(p, flashSheet, flashNote) {
  const sheets = p.sheets || [];
  const done = p.sheets_done || [];
  const total = sheets.length || 3;
  const chips = sheets.map(s => done.indexOf(s) >= 0
    ? `<span class="chip chip-ok">Sheet ${esc(s)} &#10003;</span>`
    : `<span class="chip chip-dim">Sheet ${esc(s)}</span>`).join("");
  const progress = `
    <div class="frow">
      <div class="frow-top"><span>${done.length} of ${total} sheets
        captured</span>
        <span class="fnum">${done.length}/${total}</span></div>
      <div class="meter"><i style="width:${
        Math.min(100, Math.round((done.length / total) * 100))}%"></i></div>
    </div>
    <div class="sheetchips">${chips}</div>`;

  // flashNote set = the photo was received but couldn't be read: lead with
  // the server's retake guidance instead of claiming the sheet is done.
  const flash = flashSheet ? (flashNote ? `<div class="callout callout-warn">
    <strong>Your photo of sheet ${esc(flashSheet)} was saved, but we
    couldn't read it — please retake it.</strong> ${esc(flashNote)}</div>`
    : `<div class="callout callout-warn">
    <strong>Sheet ${esc(flashSheet)} recorded.</strong> ${done.length} of
    ${total} sheets captured${done.length < total
      ? ` — ${total - done.length} to go.` : "."}</div>`) : "";

  let html = `
  <p class="kicker" style="margin-top:1.4rem">Print pack &middot; no account
    needed</p>
  <h1 style="margin-top:0">Pack ${esc(p.pack_id)}</h1>
  ${flash}`;

  if (p.revealed && p.report) {
    html += packReportHTML(p);
    view.innerHTML = html;
    return;
  }

  html += `
  <div class="card">
    <h3>1 &middot; Get your sheets</h3>
    <p class="muted small">Your pack is three sheets — A, B and C. They look
    identical, but they are not: some carry a hidden mark, and one may be an
    unmarked control. We don't tell you which is which — that's the
    experiment.</p>
    <div class="rowline">
      <a class="btn btn-gold" href="${esc(p.zip_url)}" download>Download
        pack ${esc(p.pack_id)} (ZIP, 3 sheets)</a>
    </div>
  </div>
  ${packRulesHTML()}
  <div class="card">
    <h3>2 &middot; Upload a photo of one sheet</h3>
    ${progress}
    <label class="f" for="pk-sheet">Which sheet is this photo of?</label>
    <select id="pk-sheet">
      <option value="" selected>Choose the sheet letter</option>
      ${sheets.map(s => `<option value="${esc(s)}">Sheet ${esc(s)}${
        done.indexOf(s) >= 0 ? " — already captured" : ""}</option>`).join("")}
    </select>
    <label class="f" for="pk-file" style="margin-top:1rem">The photo</label>
    <label class="filebtn" for="pk-file" id="pk-filebtn">
      <strong id="pk-filelabel">Choose your photo</strong>
      <span class="fb-hint">Tap to pick from your camera roll</span>
    </label>
    <input type="file" id="pk-file" accept="image/*" hidden>
    <div class="grid2" style="margin-top:0.5rem">
      <div><label class="f" for="pk-messaging">Sent through a messaging app
          first? (optional)</label>
        <select id="pk-messaging">
          <option value="" selected>No answer</option>
          <option value="none">No — straight from the camera</option>
          <option value="whatsapp">Yes — WhatsApp</option>
          <option value="telegram">Yes — Telegram</option>
          <option value="other">Yes — another app</option>
        </select></div>
      <div><label class="f" for="pk-note">Anything else? (optional)</label>
        <input type="text" id="pk-note" maxlength="500"
               placeholder="e.g. inkjet printer, dim light"></div>
    </div>
    <div class="actionbar">
      <button class="btn btn-gold btn-lg" id="pk-upload">Upload this
        sheet's photo</button>
    </div>
    <div id="pk-status" style="margin-top:0.6rem"></div>
  </div>
  <div class="lockbox">
    <div class="lb-title">Results stay sealed until all three are in</div>
    Your results unlock when all three sheets are captured — never before.
    That way you can't accidentally learn which sheet is the control
    mid-experiment, which would spoil your remaining photos. Upload all
    three, then the full reveal appears here.
  </div>`;

  view.innerHTML = html;
  wirePackForm(p);
}

function wirePackForm(p) {
  const fileInput = document.getElementById("pk-file");
  const fileBtn = document.getElementById("pk-filebtn");
  fileInput.addEventListener("change", () => {
    const f = fileInput.files[0];
    document.getElementById("pk-filelabel").textContent =
      f ? f.name : "Choose your photo";
    fileBtn.classList.toggle("haspick", !!f);
    fileBtn.querySelector(".fb-hint").textContent =
      f ? "Tap to choose a different photo"
        : "Tap to pick from your camera roll";
  });
  const status = document.getElementById("pk-status");
  const btn = document.getElementById("pk-upload");
  btn.onclick = async () => {
    const sheet = document.getElementById("pk-sheet").value;
    const f = fileInput.files[0];
    if (!sheet) {
      status.innerHTML = `<p class="err small">Choose the sheet letter
        first — it's printed on the sheet itself.</p>`;
      return;
    }
    if (!f) {
      status.innerHTML = `<p class="err small">Choose a photo first.</p>`;
      return;
    }
    status.innerHTML = `<div class="card" style="margin:0.6rem 0">${busy(
      "Uploading your photo… this can take a few seconds.")}</div>`;
    btn.disabled = true;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("sheet", sheet);
    const msg = document.getElementById("pk-messaging").value;
    if (msg) fd.append("messaging", msg);
    const note = document.getElementById("pk-note").value.trim();
    if (note) fd.append("note", note.slice(0, 500));
    try {
      const r = await packApi(
        `/api/packs/${encodeURIComponent(p.pack_id)}/scan`,
        {method: "POST", body: fd});
      p.sheets_done = r.sheets_done || p.sheets_done || [];
      p.revealed = !!r.revealed;
      p.report = r.report || null;
      // readable:false = the photo was recorded for the corpus but carried
      // no readable evidence; surface the server's retake guidance so the
      // volunteer doesn't believe the sheet is done.
      const retakeNote = r.readable === false
        ? (r.note || "the page could not be read from this photo; retake " +
           "it flat, sharp and filling the frame")
        : null;
      renderPack(p, p.revealed ? null : (r.sheet || sheet), retakeNote);
      window.scrollTo({top: 0, behavior: "smooth"});
    } catch (e) {
      btn.disabled = false;
      status.innerHTML = `<p class="err small">${esc(e.message)}</p>
        <p class="muted small">Nothing was spoiled — fix the photo and try
        again.</p>`;
    }
  };
}

function packReportHTML(p) {
  const cards = (p.report || []).map(item => {
    const o = PACK_OUTCOMES[item.outcome]
      || {good: false, title: esc(item.outcome || "Result")};
    const meta = [];
    if (item.agreement != null)
      meta.push(`agreement ${pct(item.agreement)}`);
    if (item.n_bits != null)
      meta.push(`${item.n_bits} readable marks (chance is 50%)`);
    return `<div class="card">
      <div class="verdict ${o.good ? "hit" : ""}">
        <p class="v-kicker">Sheet ${esc(item.sheet)} &middot; ${
          item.marked ? "carried a hidden mark" : "unmarked control"}</p>
        <div class="v-title">${o.title}</div>
        <p class="v-body">${esc(item.detail || "")}</p>
        ${meta.length ? `<p class="muted small" style="margin-top:0.6rem">${
          meta.join(" &middot; ")}</p>` : ""}
      </div>
    </div>`;
  }).join("");
  return `
  <div class="verdict hit" style="margin-top:1rem">
    <p class="v-kicker">All three sheets are in</p>
    <div class="v-title">The seal is broken — here's what your photos
      revealed</div>
    <p class="v-body">Thank you. Every one of these results — the hits and
    the misses alike — goes straight into the research benchmark.</p>
  </div>
  ${cards}
  <div class="card">
    <p class="muted small">You still have your pack ZIP:
      <a href="${esc(p.zip_url)}" download>download it again</a> any time.
      Want to do more? You can help again with another pack, or sign in to
      run a test on your own document.</p>
    <div class="rowline">
      <a class="btn btn-gold" href="#/">Back to the start</a>
    </div>
  </div>`;
}

/* ---------------- step header ---------------- */
function stepper(active) {
  const steps = ["Upload", "Print", "Photograph", "Result"];
  return `<ol class="steps">` + steps.map((s, i) => {
    const cls = i < active ? "done" : i === active ? "now" : "";
    return `<li class="step ${cls}">
      <span class="stepnum">${i < active ? "&#10003;" : i + 1}</span>
      <span class="steplabel">${s}</span></li>`;
  }).join("") + `</ol>`;
}

/* ---------------- home: my tests ---------------- */
async function viewHome() {
  if (!ME) return viewSignin();
  view.innerHTML = skeletonPage();
  const [campaigns, tests] = await Promise.all(
    [api("/api/campaigns"), api("/api/tests")]);
  let html = "";
  if (campaigns.length) {
    html += `<h1>Join a test</h1>
      <p class="muted">Pick one below — get a copy, print it, photograph it.
      No document of your own needed.</p>`;
    for (const c of campaigns) {
      html += `<div class="testrow" onclick="location.hash='#/test/${esc(c.test_id)}'">
        <div><div class="tname">${esc(c.name)}</div>
          <div class="muted small">${c.n_variants} marked copies</div></div>
        <div class="rowline">
          ${c.n_my_scans ? `<span class="chip chip-ok">${c.n_my_scans} of your photos</span>` : ""}
          <span class="chip">open to everyone</span>
        </div></div>`;
    }
  }
  if (!campaigns.length && !tests.length) {
    html += `<div class="card empty">
      <span class="e-mark">&sect;</span>
      <h2 style="margin:0">No tests yet</h2>
      <p>A test is one document, its marked copies, and every photo you have
      scanned against it. Start one with any PDF — or our sample text.</p>
      <a class="btn btn-gold btn-lg" href="#/new">Start your first test</a>
    </div>`;
    view.innerHTML = html;
    return;
  }
  html += `<h1 style="margin-top:${campaigns.length ? "2rem" : "0.4em"}">My tests</h1>`;
  if (!tests.length) {
    html += `<div class="card"><p>You can also test your own document:
      upload a PDF and we mark it.</p>
      <a class="btn" href="#/new">Start your own test</a></div>`;
  }
  for (const t of tests) {
    const status = t.status === "generated"
      ? `<span class="chip">ready</span>`
      : t.status === "generating"
        ? `<span class="chip chip-dim"><span class="spin"></span>&nbsp;preparing</span>`
        : `<span class="chip chip-dim">${esc(t.status)}</span>`;
    html += `<div class="testrow" onclick="location.hash='#/test/${esc(t.test_id)}'">
      <div><div class="tname">${esc(t.name)}</div>
        <div class="muted small">${fmtDate(t.created_utc)}</div></div>
      <div class="rowline">
        ${t.docs ? `<span class="chip chip-dim">${t.docs.filter(d => d.marked).length} copies</span>` : ""}
        ${t.n_scans ? `<span class="chip chip-dim">${t.n_scans} photo${t.n_scans > 1 ? "s" : ""}</span>` : ""}
        ${status}
      </div></div>`;
  }
  view.innerHTML = html;
}

/* ---------------- step 1: upload / create ---------------- */
function viewNew() {
  if (!ME) return viewSignin();
  const maxV = CFG.max_variants;
  view.innerHTML = `${stepper(0)}
  <h1>Set up your document</h1>
  <div class="card">
    <label class="f">Upload a PDF</label>
    <div class="rowline">
      <button class="btn btn-gold" id="w-pdfbtn">Choose a PDF file</button>
      <button class="btn" id="w-sample">No PDF handy? Use our sample text</button>
      <input type="file" id="w-pdf" accept="application/pdf" hidden>
    </div>
    <p class="muted small" id="w-preview" style="margin-top:0.8rem">
      Pick any text document — an exam paper, a memo, a report. We will make
      marked copies of it.</p>
    <div id="w-textwrap" hidden>
      <label class="f">Document text</label>
      <textarea id="w-content"></textarea>
    </div>

    <label class="f">Name this test</label>
    <input type="text" id="w-name" placeholder="e.g. March exam paper" maxlength="80">

    <label class="f">How many copies? (each gets its own hidden mark)</label>
    <select id="w-nvar">${[2, 3, 4, 5].filter(n => n <= maxV).map(n =>
      `<option value="${n}" ${n === Math.min(3, maxV) ? "selected" : ""}>${n} copies</option>`).join("")}
    </select>

    <div class="actionbar">
      <button class="btn btn-gold btn-lg" id="w-go">Create the marked copies</button>
    </div>
    <div id="w-status" class="muted small" style="margin-top:0.6rem"></div>
  </div>
  <p class="note">All copies show exactly the same text. The differences are
  tiny position shifts — fractions of a millimetre — invisible to the eye.
  We also make one <strong>control</strong> page with no mark at all; it
  keeps us honest.</p>`;

  const preview = document.getElementById("w-preview");
  const content = document.getElementById("w-content");
  const textwrap = document.getElementById("w-textwrap");
  const nvar = document.getElementById("w-nvar");
  let pdfState = null;   // {upload_id, filename, cap} when preserving layout
  let sampleUsed = false, lastLay = null;

  // With N copies, attribution from a real photo needs
  // ceil(log2(N/1e-3)) line bits (>=10) on the photographed page.
  const bitsNeeded = n => Math.max(10, Math.ceil(Math.log2(Math.max(1, n) / 0.001)));

  function capacityMessage() {
    const n = +nvar.value || 2;
    const need = bitsNeeded(n);
    if (pdfState) {
      const rasterNote = pdfState.mode === "pdf_raster"
        ? ` Scanned PDF detected: the mark is embedded in the page images
           themselves — tables, figures and stamps stay pixel-identical.`
        : pdfState.mode === "pdf_vector"
        ? ` Outline-text PDF detected: whole text lines are shifted a
           quarter millimetre in the drawing commands — vector quality is
           preserved exactly.`
        : "";
      const weak = pdfState.cap.per_page.filter(p => p.line_bits < need);
      if (!weak.length) {
        if (pdfState.mode === "pdf_raster" || pdfState.mode === "pdf_vector") {
          // These carriers only analyze (and mark) the first few pages, so
          // never promise "every page" — say exactly which pages carry it.
          const nAna = pdfState.cap.per_page.length;
          return `<strong>${esc(pdfState.filename)}</strong> — good: the
            ${nAna > 1 ? `first ${nAna} pages carry` : "first page carries"}
            a strong hidden mark — photograph ${nAna > 1
              ? `any of pages 1–${nAna}` : "page 1"} when the time comes.
            Your PDF keeps its exact look.${rasterNote}`;
        }
        return `<strong>${esc(pdfState.filename)}</strong> — good: every page
          can carry a strong hidden mark. Your PDF keeps its exact
          look.${rasterNote}`;
      }
      if (weak.length < pdfState.cap.per_page.length) {
        const okPages = pdfState.cap.per_page.filter(p => p.line_bits >= need)
          .map(p => p.page_index + 1);
        return `<strong>${esc(pdfState.filename)}</strong> — page${okPages.length > 1 ? "s" : ""}
          ${okPages.join(", ")} can carry a strong mark; the other pages are
          too short or too dense. <strong>Photograph page ${okPages[0]}</strong>
          when the time comes.`;
      }
      return `<span style="color:var(--gold)">This PDF's pages are too short
        or too tightly packed for a phone-photo test with ${n} copies. Try
        fewer copies, another document, or the sample text.</span>`;
    }
    if (lastLay) {
      const weak = lastLay.per_page.filter(p => p.line_bits < need);
      if (!weak.length) {
        return `${lastLay.pages} page${lastLay.pages > 1 ? "s" : ""} of text —
          good: every page can carry a strong hidden mark.`;
      }
      return `<span style="color:var(--gold)">Some pages are too short for a
        phone-photo test with ${n} copies — add more text (a full page of
        normal paragraphs is plenty) or photograph a full page.</span>`;
    }
    return "";
  }

  function refreshPreview() {
    const msg = capacityMessage();
    if (msg) preview.innerHTML = msg;
  }
  nvar.addEventListener("input", refreshPreview);

  let t = null;
  content.addEventListener("input", () => {
    sampleUsed = false; pdfState = null;
    clearTimeout(t);
    t = setTimeout(async () => {
      const text = content.value.trim();
      if (!text) { lastLay = null; return; }
      try { lastLay = await postJSON("/api/layout", {content: text}); refreshPreview(); }
      catch (e) { preview.textContent = e.message; }
    }, 500);
  });

  document.getElementById("w-sample").onclick = async () => {
    const d = await api("/api/sample");
    pdfState = null;
    textwrap.hidden = false;
    content.disabled = false;
    content.value = d.content;
    sampleUsed = true;
    lastLay = await postJSON("/api/layout", {content: d.content});
    refreshPreview();
  };

  const pdfInput = document.getElementById("w-pdf");
  document.getElementById("w-pdfbtn").onclick = () => pdfInput.click();
  pdfInput.addEventListener("change", async () => {
    const f = pdfInput.files[0];
    if (!f) return;
    preview.innerHTML = `<span class="spin"></span> Reading your PDF…`;
    const fd = new FormData();
    fd.append("file", f);
    try {
      const d = await api("/api/analyze-pdf", {method: "POST", body: fd});
      pdfState = {upload_id: d.upload_id, filename: d.filename,
                  mode: d.mode || "pdf_preserved", cap: d};
      textwrap.hidden = true;
      content.value = "";
      if (!document.getElementById("w-name").value) {
        document.getElementById("w-name").value =
          (f.name || "").replace(/\.pdf$/i, "").slice(0, 80);
      }
      refreshPreview();
    } catch (e) {
      // Fall back: extract the text and re-typeset it with our own layout.
      pdfState = null;
      preview.innerHTML = `We can't hide marks in this PDF's own layout
        (${esc(e.message)}). Extracting its text instead — the copies will
        look different from your original but read the same…`;
      try {
        const fd2 = new FormData();
        fd2.append("file", f);
        const d2 = await api("/api/extract-pdf", {method: "POST", body: fd2});
        textwrap.hidden = false;
        content.disabled = false;
        content.value = d2.content;
        lastLay = await postJSON("/api/layout", {content: d2.content});
        preview.innerHTML = `Text imported (${d2.words} words). ` + capacityMessage();
      } catch (e2) {
        preview.innerHTML = `<span style="color:var(--gold)">Sorry — this PDF
          can't be used (${esc(e2.message)}). Try another document or the
          sample text.</span>`;
      }
    }
    pdfInput.value = "";
  });

  document.getElementById("w-go").onclick = async () => {
    const name = document.getElementById("w-name").value.trim()
      || (pdfState ? pdfState.filename : "My document");
    const text = content.value.trim();
    const n = +nvar.value || 2;
    const labels = [...Array(n).keys()].map(i => `Variant ${i + 1}`);
    const status = document.getElementById("w-status");
    if (!pdfState && !text) {
      status.textContent = "Upload a PDF or load the sample text first.";
      return;
    }
    status.innerHTML = `<span class="spin"></span> Making ${n} marked copies
      + 1 control…`;
    document.getElementById("w-go").disabled = true;
    try {
      const payload = pdfState
        ? {name, mode: pdfState.mode || "pdf_preserved",
           upload_id: pdfState.upload_id,
           content: "", variant_labels: labels, n_controls: 1}
        : {name, content: text, variant_labels: labels, n_controls: 1,
           sample_used: sampleUsed};
      const r = await postJSON("/api/tests", payload);
      const warn = r.capacity_warning
        ? `<div class="callout callout-warn"><strong>Heads up:</strong>
           ${esc(r.capacity_warning)}</div>` : "";
      status.innerHTML = `${warn}<span class="spin"></span> Making ${n}
        marked copies + 1 control…`;
      const poll = setInterval(async () => {
        const m = await api("/api/tests/" + r.test_id);
        if (m.status === "generated") {
          clearInterval(poll);
          if (r.capacity_warning) SHARE_WARNING = r.capacity_warning;
          location.hash = "#/test/" + r.test_id;
        } else if (m.status === "error") {
          clearInterval(poll);
          status.textContent = "Something went wrong preparing the copies. "
            + "Try different content.";
          document.getElementById("w-go").disabled = false;
        }
      }, 1200);
    } catch (e) {
      status.textContent = e.message;
      document.getElementById("w-go").disabled = false;
    }
  };
}

/* ---------------- test hub (steps 2-4) ---------------- */
async function viewTest(testId, sub) {
  if (!ME) return viewSignin();
  if (LAST_TEST_RENDERED !== testId) view.innerHTML = skeletonPage();
  let m;
  try { m = await api("/api/tests/" + testId); }
  catch (e) { view.innerHTML = `<p>${esc(e.message)}</p>`; return; }
  LAST_TEST_RENDERED = testId;

  if (m.status === "generating") {
    view.innerHTML = `${stepper(0)}<h1>${esc(m.name)}</h1>
      <div class="card">${busy(`Preparing your marked copies… this takes a
      few seconds.`)}
      <div class="skel skel-row"></div><div class="skel skel-row"></div></div>`;
    setTimeout(() => { if (location.hash.includes(testId)) viewTest(testId, sub); }, 1200);
    return;
  }
  if (m.status === "error") {
    view.innerHTML = `<h1>${esc(m.name)}</h1>
      <div class="card">Something went wrong preparing this test. Start a
      new one with different content.</div>`;
    return;
  }

  // Assigned-campaign flow: contributors get one specific copy each.
  // Falls back silently to pick-your-own when the backend doesn't send
  // assign_mode (older server) or for the owner's view.
  const assigned = !!m.assign_mode && !m.is_owner;
  if (assigned && !m.my_assignment) return renderJoinStep(m);

  if (sub === "photo") renderPhotoStep(m);
  else if (sub === "log") renderLog(m);
  else renderPrintStep(m);
}

/* ---------------- assigned campaigns: join / full ---------------- */
function renderJoinStep(m) {
  view.innerHTML = `${stepper(1)}
  <h1>${esc(m.name)}</h1>
  <div class="card hero-card" style="text-align:center">
    <h2 style="margin-top:0">Get your own copy</h2>
    <p class="muted">When you join, we hand you <strong>your own uniquely
    marked copy</strong> of this document. It looks exactly like everyone
    else's — the difference is invisible — and it's yours alone, so your
    photo tells us precisely how well the mark survived your printer and
    your phone.</p>
    <div class="actionbar">
      <button class="btn btn-gold btn-lg" id="join-btn">Get my copy</button>
    </div>
    <p class="muted small" id="join-status"></p>
  </div>`;
  const btn = document.getElementById("join-btn");
  const status = document.getElementById("join-status");
  btn.onclick = async () => {
    btn.disabled = true;
    status.innerHTML = `<span class="spin"></span> Reserving your copy…`;
    try {
      await postJSON(`/api/campaigns/${m.test_id}/join`, {});
      await viewTest(m.test_id);
    } catch (e) {
      if (/full/i.test(e.message)) return renderFullState(m);
      status.textContent = e.message;
      btn.disabled = false;
    }
  };
}

function renderFullState(m) {
  view.innerHTML = `
  <h1>${esc(m.name)}</h1>
  <div class="card hero-card empty">
    <span class="e-mark">&#10003;</span>
    <h2 style="margin:0">All copies are taken — thank you!</h2>
    <p>Every marked copy of this document already has a contributor. That
    means this test is fully staffed, which is wonderful news for the
    research.</p>
    <p>If you'd still like to help, you can run a test on a document of your
    own, or check back later for a new campaign.</p>
    <div class="rowline" style="justify-content:center">
      <a class="btn btn-gold" href="#/">See other tests</a>
      <a class="btn" href="#/new">Test my own document</a>
    </div>
  </div>`;
}

/* ---------------- step 2: print ---------------- */
function printWarning() {
  return `<div class="callout-print">
    <div class="cp-title">Before you print — the one rule</div>
    Print at <strong>100% scale</strong> (sometimes called
    <strong>"Actual size"</strong>). Never choose <strong>"Fit to
    page"</strong> or "Shrink to fit" — any resizing destroys the hidden
    mark and the test won't work. A laser printer works best, but any
    printer is fine.
  </div>`;
}

function docCard(m, d, opts) {
  opts = opts || {};
  const label = d.marked ? esc(d.label) : "Control page";
  return `
    <div class="doccard ${opts.hero ? "doccard-hero" : ""}">
      <div class="rowline"><strong>${label}</strong>
        ${d.marked
          ? `<span class="chip">${opts.mine ? "your copy" : "marked"}</span>`
          : `<span class="chip chip-dim">no mark</span>`}</div>
      <div class="thumbs"><img
        src="/api/files/${esc(m.test_id)}/docs/${esc(d.doc_id)}/page0_thumb.png"
        alt="${label} preview" loading="lazy"></div>
      <a class="btn ${d.marked ? "btn-gold" : ""} ${opts.hero ? "btn-lg" : ""}"
         href="/api/tests/${esc(m.test_id)}/pdf/${esc(d.doc_id)}">
        Download ${label} (PDF)</a>
    </div>`;
}

function renderPrintStep(m) {
  const assigned = !!m.assign_mode && !m.is_owner;
  if (assigned) return renderAssignedPrintStep(m);

  const marked = m.docs.filter(d => d.marked);
  const ctrl = m.docs.find(d => !d.marked);
  let cards = marked.map(d => docCard(m, d)).join("");
  if (ctrl) cards += docCard(m, ctrl);

  const ownerHTML = ownerPanelHTML(m);
  let looseWarn = "";
  if (!ownerHTML && m.is_owner && SHARE_WARNING) {
    looseWarn = `<div class="callout callout-warn"><strong>Heads up:</strong>
      ${esc(SHARE_WARNING)}</div>`;
    SHARE_WARNING = null;
  }

  view.innerHTML = `${stepper(1)}
  <h1>${esc(m.name)}</h1>
  ${looseWarn}
  <p>They all look identical — that's the point. Now:</p>
  ${printWarning()}
  <div class="note">
    <strong>1.</strong> Pick <strong>one</strong> variant. Don't tell us
    which — that's the test.<br>
    <strong>2.</strong> Print it (100% scale, as above).<br>
    <strong>3.</strong> Write the variant number on the <em>back</em> of the
    sheet so you remember it.<br>
    <strong>4.</strong> If you can, also print the Control page — it lets us
    check we don't accuse blank pages.
  </div>
  <div class="docgrid" style="margin-top:1rem">${cards}</div>
  ${ownerHTML}
  <div class="actionbar">
    <a class="btn btn-gold btn-lg" href="#/test/${esc(m.test_id)}/photo">
      I've printed a page — continue</a>
    ${m.scans.length ? `<a class="btn" href="#/test/${esc(m.test_id)}/log">
      Past photos (${m.scans.length})</a>` : ""}
  </div>`;
  wireOwnerPanel(m);
}

function renderAssignedPrintStep(m) {
  const mine = m.docs.find(d => d.doc_id === m.my_assignment) || m.docs[0];
  const total = mine ? (mine.n_pages || m.n_pages) : 0;
  // The no-text PDF carriers only mark the first few analyzed pages, so
  // the multi-page pitch must not promise pages beyond the marked set.
  const noText = m.type === "pdf_raster" || m.type === "pdf_vector";
  const markedPg = (noText && mine && mine.pages)
    ? mine.pages.filter(p => p.line_bits > 0).map(p => p.page_index + 1)
    : [];
  const contiguous = markedPg.every((v, i) => v === i + 1);
  const markedPhrase = markedPg.length > 1
    ? (contiguous ? `pages 1–${markedPg.length}` : `pages ${markedPg.join(", ")}`)
    : `page ${markedPg[0]}`;
  const partialMark = noText && markedPg.length && markedPg.length < total;
  const multiPageMsg = !mine || !(total > 1) ? ""
    : noText && !markedPg.length ? ""
    : partialMark
      ? `It has ${total} pages, but only ${markedPg.length > 1
          ? `${markedPg.length} of them carry` : "one of them carries"}
         the hidden mark — please print all of them and photograph
         <strong>${markedPg.length > 1 ? `each of ${markedPhrase}`
           : markedPhrase}</strong> separately. Photos of the other pages
         carry no mark.`
      : `It has ${total} pages — please print
         <strong>all of them</strong> and photograph <strong>each page
         separately</strong>. Every extra page makes the hidden mark much
         harder to lose.`;
  const body = mine ? `
    <div class="docgrid" style="margin-top:1rem">
      ${docCard(m, mine, {hero: true, mine: true})}
    </div>
    ${printWarning()}
    <div class="note">
      <strong>1.</strong> Download and print your copy (100% scale, as
      above).<br>
      <strong>2.</strong> Photograph the printed page with your phone —
      normal room light is fine.<br>
      <strong>3.</strong> Upload the photo here and see if we can tell it
      was your copy.
    </div>`
    : `<div class="card"><p class="muted">Your copy isn't ready yet.
       Refresh in a moment.</p></div>`;
  view.innerHTML = `${stepper(1)}
  <h1>${esc(m.name)}</h1>
  <p>This is <strong>your copy</strong> — every contributor gets a different
  one, marked invisibly. ${multiPageMsg}</p>
  ${body}
  <div class="actionbar">
    <a class="btn btn-gold btn-lg" href="#/test/${esc(m.test_id)}/photo">
      I've printed it — continue</a>
    ${m.scans.length ? `<a class="btn" href="#/test/${esc(m.test_id)}/log">
      Past photos (${m.scans.length})</a>` : ""}
  </div>`;
}

/* ---------------- owner tools: share + funnel ---------------- */
function ownerPanelHTML(m) {
  if (!ME || !ME.is_admin || !m.is_owner) return "";
  const warn = SHARE_WARNING
    ? `<div class="callout callout-warn"><strong>Heads up:</strong>
       ${esc(SHARE_WARNING)}</div>` : "";
  if (!m.shared) {
    return `<div class="card" id="owner-panel">
      <h3>Recruit contributors</h3>
      ${warn}
      <p class="muted small">Share this test so every signed-in contributor
      can see it and take part.</p>
      <label class="check"><input type="checkbox" id="share-assign" checked>
        Hand out one specific copy per contributor (recommended — no two
        people print the same copy, and we know exactly who has which)</label>
      <div class="rowline">
        <button class="btn btn-gold" id="share-btn">Share with contributors</button>
      </div>
      <div id="share-warn"></div>
    </div>`;
  }
  return `<div class="card" id="owner-panel">
    <div class="rowline">
      <h3 style="margin:0">Shared with contributors</h3>
      ${m.assign_mode != null
        ? `<span class="chip ${m.assign_mode ? "" : "chip-dim"}">${m.assign_mode
            ? "one copy per person" : "pick your own copy"}</span>` : ""}
    </div>
    ${warn}
    <div id="funnel" class="funnel"><div class="skel skel-row"></div></div>
    <div class="rowline" style="margin-top:0.8rem">
      <button class="btn" id="share-btn">Stop sharing</button>
    </div>
    <div id="share-warn"></div>
  </div>`;
}

function wireOwnerPanel(m) {
  SHARE_WARNING = null;   // shown once by ownerPanelHTML, then cleared
  const shareBtn = document.getElementById("share-btn");
  if (shareBtn) shareBtn.onclick = async () => {
    const warnBox = document.getElementById("share-warn");
    const assignBox = document.getElementById("share-assign");
    shareBtn.disabled = true;
    try {
      const payload = m.shared
        ? {shared: false}
        : {shared: true, assigned: !!(assignBox && assignBox.checked)};
      const r = await postJSON(`/api/admin/tests/${m.test_id}/share`, payload);
      SHARE_WARNING = (r && r.capacity_warning) || null;
      viewTest(m.test_id);
    } catch (e) {
      shareBtn.disabled = false;
      if (warnBox) warnBox.innerHTML =
        `<p class="muted small">${esc(e.message)}</p>`;
    }
  };
  const funnelBox = document.getElementById("funnel");
  if (funnelBox) loadFunnel(m.test_id, funnelBox);
}

async function loadFunnel(testId, el) {
  try {
    const f = await api(`/api/tests/${testId}/funnel`);
    el.innerHTML = funnelHTML(f);
  } catch (e) {
    // Older backend without the funnel endpoint — just hide the panel part.
    el.innerHTML = "";
  }
}

function funnelHTML(f) {
  const total = Math.max(f.n_variants || 0, 1);
  const confirmed = (f.feedback_correct || 0) + (f.feedback_wrong || 0);
  const bar = (label, val, cls) => `
    <div class="frow">
      <div class="frow-top"><span>${label}</span>
        <span class="fnum">${val} / ${total}</span></div>
      <div class="meter ${cls || ""}"><i style="width:${
        Math.min(100, Math.round((val / total) * 100))}%"></i></div>
    </div>`;
  return `
    ${bar("Copies handed out", f.assigned || 0)}
    ${bar("Contributors who uploaded a photo", f.contributors_uploaded || 0)}
    ${bar("Results confirmed by contributors", confirmed, "m-ok")}
    <p class="fsub">${f.feedback_correct || 0} confirmed right &middot;
      ${f.feedback_wrong || 0} confirmed wrong &middot;
      ${f.unassigned || 0} cop${(f.unassigned || 0) === 1 ? "y" : "ies"}
      still available</p>`;
}

/* ---------------- step 3: photograph ---------------- */
function renderPhotoStep(m) {
  const enums = CFG.capture_enums || {};
  // Blank default so an untouched form records "unknown" server-side
  // instead of fabricating whichever enum value happens to be first.
  const opts = (key, labels) => `<option value="" selected>No answer</option>` +
    (enums[key] || []).map(v =>
    `<option value="${v}">${labels[v] || v}</option>`).join("");
  view.innerHTML = `${stepper(2)}
  <h1>Photograph the printed page</h1>
  <div class="card">
    <p>Lay the sheet flat, keep it roughly upright in the frame, and
    <strong>fill the frame with the paper</strong>. Normal room light is
    fine. Sending the photo through WhatsApp first is allowed — that's part
    of what we're testing.</p>
    <label class="filebtn" for="s-file" id="s-filebtn">
      <strong id="s-filelabel">Choose your photo</strong>
      <span class="fb-hint">Tap to pick from your camera roll</span>
    </label>
    <input type="file" id="s-file" accept="image/*" hidden>
    <div class="grid2" style="margin-top:0.5rem">
      <div><label class="f">Printer used (optional)</label>
        <select id="s-printer">${opts("printer", {laser_mono: "Laser, black & white",
          laser_color: "Laser, colour", inkjet: "Inkjet", unknown: "Don't know"})}</select></div>
      <div><label class="f">Phone (optional)</label>
        <select id="s-phone">${opts("phone", {budget: "Budget phone", mid: "Mid-range phone",
          flagship: "High-end phone", unknown: "Don't know"})}</select></div>
      <div><label class="f">Lighting (optional)</label>
        <select id="s-lighting">${opts("lighting", {office: "Normal indoor light",
          dim: "Dim light", flash_glare: "Flash / glare", window_backlight: "Bright window behind",
          unknown: "Don't know"})}</select></div>
      <div><label class="f">Anything else? (optional)</label>
        <input type="text" id="s-note" placeholder="e.g. sent via WhatsApp once"></div>
    </div>
    <div class="actionbar">
      <button class="btn btn-gold btn-lg" id="s-upload">Upload and read the mark</button>
      <a class="btn" href="#/test/${esc(m.test_id)}">Back to printing</a>
    </div>
  </div>
  <div id="s-status"></div>
  <div id="s-result"></div>`;

  const fileInput = document.getElementById("s-file");
  const fileBtn = document.getElementById("s-filebtn");
  fileInput.addEventListener("change", () => {
    const f = fileInput.files[0];
    document.getElementById("s-filelabel").textContent =
      f ? f.name : "Choose your photo";
    fileBtn.classList.toggle("haspick", !!f);
    fileBtn.querySelector(".fb-hint").textContent =
      f ? "Tap to choose a different photo" : "Tap to pick from your camera roll";
  });

  const status = document.getElementById("s-status");
  const resBox = document.getElementById("s-result");
  document.getElementById("s-upload").onclick = async () => {
    const f = fileInput.files[0];
    if (!f) { status.innerHTML = `<p class="muted">Choose a photo first.</p>`; return; }
    status.innerHTML = `<div class="card">${busy(`Reading the hidden mark…
      this takes a few seconds.`)}
      <div class="skel skel-row"></div></div>`;
    document.getElementById("s-upload").disabled = true;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("printer", document.getElementById("s-printer").value);
    fd.append("phone", document.getElementById("s-phone").value);
    fd.append("lighting", document.getElementById("s-lighting").value);
    fd.append("note", document.getElementById("s-note").value);
    try {
      const r = await api(`/api/tests/${m.test_id}/scan`, {method: "POST", body: fd});
      status.innerHTML = "";
      resBox.innerHTML = resultCard(r, m);
      wireFeedback(resBox, r, m);
      resBox.scrollIntoView({behavior: "smooth"});
    } catch (e) {
      status.innerHTML = `<p>${esc(e.message)}</p>`;
    }
    document.getElementById("s-upload").disabled = false;
  };
}

/* ---------------- result card + feedback ---------------- */
function plainVerdict(r) {
  const v = r.verdict || {};
  if (v.attributed) {
    const strong = v.p_adj != null && v.p_adj <= 1e-6
      && (v.margin == null || v.margin >= 0.1);
    return {
      kind: "attributed",
      title: "We read this as",
      big: esc(v.label),
      body: strong
        ? "The mark came through clearly — we are very confident about this one."
        : "We think so, but not with full confidence.",
    };
  }
  if (v.reason === "runner-up too close") {
    return {
      kind: "unsure",
      title: "Two copies match too closely",
      big: null,
      body: `Two copies match this photo almost equally well — at this photo
        quality we can't honestly tell them apart, so we don't guess. A
        sharper photo, or a photo of another page, should separate them.`,
    };
  }
  if (v.reason === "below evidence threshold") {
    const best = (r.scores || [])[0];
    const close = best && best.p_adj != null && best.p_adj <= 0.05;
    return {
      kind: "unsure",
      title: "We can't tell which copy this is",
      big: null,
      body: close
        ? `Our closest guess is ${esc(best.label)}, but the evidence isn't
           strong enough to call it. If you photographed the <strong>Control
           page</strong> (the one with no mark), this is exactly the right
           answer.`
        : `No copy stands out from chance. If you photographed the
           <strong>Control page</strong>, this is exactly the right answer.
           Otherwise the mark didn't survive — which is also useful for us
           to know.`,
    };
  }
  return {
    kind: "unread",
    title: "We couldn't read the page",
    big: null,
    body: esc(r.note || v.reason || "") +
      " You can retake the photo and try again — no harm done.",
  };
}

function resultCard(r, m) {
  const p = plainVerdict(r);
  const v = r.verdict || {};
  const img = (r.source && r.source.input_file)
    ? `<img class="scan-img" src="/api/files/${esc(r.source.input_file)}"
        alt="your photo" loading="lazy">` : "";
  let table = "";
  if (r.scores) {
    table = `<div class="table-scroll"><table>
      <tr><th>copy</th><th>line bits</th><th>word bits</th>
          <th>agreement</th><th>corrected p</th></tr>` +
      r.scores.map((s, i) => `<tr class="${i === 0 && v.attributed ? "best" : ""}">
        <td>${esc(s.label)}</td>
        <td>${s.line_tot ? `${s.line_ok}/${s.line_tot}` : "erased"}</td>
        <td>${s.word_tot == null ? "-"
              : s.word_tot ? `${s.word_ok}/${s.word_tot}` : "erased"}</td>
        <td>${pct(s.acc)}</td><td>${sci(s.p_adj)}</td></tr>`).join("") +
      `</table>
      <p class="muted small">Chance is 50%. Pipeline ${esc(r.path_used || "n/a")},
      deskew ${r.deskew_deg ?? "?"}&deg;, ${r.n_lines_found ?? "?"} lines,
      page ${r.page_index != null ? r.page_index + 1 : "?"}.</p></div>`;
  }
  const fb = feedbackBlock(r, m, p);
  return `<div class="card" data-scan="${esc(r.scan_id)}">
    <div class="verdict ${p.kind === "attributed" ? "hit" : ""}">
      <p class="v-kicker">Our reading</p>
      <div class="v-title">${p.title}</div>
      ${p.big ? `<div class="v-big">${p.big}</div>` : ""}
      <p class="v-body">${p.body}</p>
    </div>
    ${fb}
    <details style="margin-top:0.8rem"><summary class="muted small">Technical
      details</summary>
      <div class="grid2" style="margin-top:0.6rem"><div>${table}</div>
      <div>${img}</div></div></details>
  </div>`;
}

function feedbackBlock(r, m, p) {
  if (!r.source || r.source.kind !== "upload") return "";
  if (r.feedback) {
    return `<p class="muted small">You marked this
      <strong>${esc(r.feedback.judgment)}</strong>. Thank you!</p>`;
  }
  const docChoices = m.docs.map(d =>
    `<option value="${esc(d.doc_id)}">${d.marked ? esc(d.label) : "The Control page"}</option>`)
    .join("") + `<option value="other">A different page entirely</option>`;
  if (p.kind === "attributed") {
    return `<div class="fb" id="fb">
      <p><strong>You know which page you printed — did we get it right?</strong></p>
      <div class="rowline">
        <button class="btn btn-gold" data-fb="correct">Yes, correct</button>
        <button class="btn" data-fb="wrong">No, wrong</button>
      </div>
      <div class="fb-wrong" hidden style="margin-top:0.7rem">
        <label class="f">Which page did you actually photograph?</label>
        <select class="fb-truedoc">${docChoices}</select>
        <div class="rowline" style="margin-top:0.6rem">
          <button class="btn btn-gold" data-fb="wrong-submit">Send answer</button>
        </div>
      </div>
      <p class="fb-status muted small"></p>
    </div>`;
  }
  return `<div class="fb" id="fb">
    <p><strong>Help us score this one — what did you actually photograph?</strong></p>
    <div class="rowline">
      <select class="fb-truedoc" style="max-width:280px">${docChoices}</select>
      <button class="btn btn-gold" data-fb="reveal-submit">Send answer</button>
      <button class="btn" data-fb="unsure">Not sure</button>
    </div>
    <p class="fb-status muted small"></p>
  </div>`;
}

function wireFeedback(root, r, m) {
  const fb = root.querySelector("#fb");
  if (!fb) return;
  const status = fb.querySelector(".fb-status");
  const send = async payload => {
    status.innerHTML = `<span class="spin"></span>`;
    try {
      await postJSON(`/api/tests/${m.test_id}/scans/${r.scan_id}/feedback`, payload);
      fb.innerHTML = `<p><strong>Thank you!</strong> Every answer makes the
        benchmark better.</p>
        <div class="rowline">
          <a class="btn btn-gold" href="#/test/${esc(m.test_id)}/photo"
             onclick="setTimeout(route)">Scan another photo</a>
          <a class="btn" href="#/new">Start a new test</a>
        </div>`;
    } catch (e) { status.textContent = e.message; }
  };
  fb.addEventListener("click", e => {
    const b = e.target.closest("[data-fb]");
    if (!b) return;
    const kind = b.dataset.fb;
    if (kind === "correct") send({judgment: "correct"});
    else if (kind === "wrong") fb.querySelector(".fb-wrong").hidden = false;
    else if (kind === "wrong-submit")
      send({judgment: "wrong", true_doc_id: fb.querySelector(".fb-truedoc").value});
    else if (kind === "reveal-submit") {
      const truth = fb.querySelector(".fb-truedoc").value;
      const predicted = (r.verdict || {}).doc_id;
      // No attribution + an unmarked control or a foreign page is the
      // decoder being right (abstention IS the correct answer there);
      // "wrong" is reserved for actual decoder mistakes.
      const truthDoc = (m.docs || []).find(d => d.doc_id === truth);
      const abstainedRight = !predicted &&
        (truth === "other" || (truthDoc && !truthDoc.marked));
      const judgment = predicted
        ? (predicted === truth ? "correct" : "wrong")
        : (abstainedRight ? "correct" : "wrong");
      send({judgment, true_doc_id: truth});
    } else if (kind === "unsure") send({judgment: "unsure"});
  });
}

/* ---------------- past photos ---------------- */
/* Combined per-contributor reading: pooling every photo across pages is
   far stronger than any single photo, so when the contributor has 2+ real
   photos we show the pooled verdict above the per-photo list. */
function pooledCard(m) {
  const pv = m.pooled_verdict;
  if (!pv || pv.n_photos < 2) return "";
  const kicker = `Combined reading across your ${pv.n_photos} photos`;
  if (pv.attributed) {
    return `<div class="card">
      <div class="verdict hit">
        <p class="v-kicker">${esc(kicker)}</p>
        <div class="v-title">Together, your photos read as</div>
        <div class="v-big">${esc(pv.label)}</div>
        <p class="v-body">Pooling the best photo of each page, the hidden
          marks agree ${pct(pv.agreement)} across ${pv.n_bits} readable
          marks — a much stronger reading than any single photo. Photos of
          the <strong>same</strong> page don't stack, so if you can, upload
          a photo of <strong>every</strong> page you printed.</p>
      </div></div>`;
  }
  return `<div class="card">
    <div class="verdict">
      <p class="v-kicker">${esc(kicker)}</p>
      <div class="v-title">No copy stands out yet</div>
      <p class="v-body">Even combined, your photos don't single out one
        copy: ${esc(pv.abstain_reason || "the evidence is not strong enough yet")}.
        Each extra page photo makes the reading stronger — try uploading a
        photo of every page you printed.</p>
    </div></div>`;
}

function renderLog(m) {
  const scans = (m.scans || []).filter(s => s.source && s.source.kind === "upload");
  let html = `${stepper(3)}<h1>${esc(m.name)} — past photos</h1>
    <div class="rowline" style="margin:0.6rem 0 1rem">
      <a class="btn btn-gold" href="#/test/${esc(m.test_id)}/photo">Scan another photo</a>
      <a class="btn" href="#/test/${esc(m.test_id)}">Printing instructions</a>
    </div>`;
  html += pooledCard(m);
  if (!scans.length) {
    html += `<div class="card empty">
      <span class="e-mark">&#9675;</span>
      <p>No photos yet. Print a page, photograph it, and your results will
      appear here.</p>
      <a class="btn btn-gold" href="#/test/${esc(m.test_id)}/photo">
        Upload your first photo</a>
    </div>`;
  }
  for (const s of scans) html += resultCard(s, m);
  view.innerHTML = html;
  for (const s of scans) {
    const el = view.querySelector(`[data-scan="${CSS.escape(s.scan_id)}"]`);
    if (el) wireFeedback(el, s, m);
  }
}

/* ---------------- router ---------------- */
async function route() {
  const h = location.hash.replace(/^#\/?/, "");
  try {
    if (!h) await viewHome();
    else if (h === "new") viewNew();
    else if (h.startsWith("pack/")) {
      await viewPack(h.split("/")[1]);       // anonymous — no sign-in gate
    } else if (h.startsWith("test/")) {
      const [, id, sub] = h.split("/");
      await viewTest(id, sub);
    } else await viewHome();
  } catch (e) {
    if (e.message !== "signed out")
      view.innerHTML = `<p>Error: ${esc(e.message)}</p>`;
  }
}
window.addEventListener("hashchange", route);
boot();
