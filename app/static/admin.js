// SPDX-License-Identifier: Apache-2.0
/* Admin view: contribution stats, per-campaign funnels, capture list,
   corpus export. The app name is NOT hard-coded here — the header brand is
   derived from this page's <title> (rebrand = edit the HTML titles plus the
   APP_NAME const in app.js). */
"use strict";

const view = document.getElementById("view");
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmtDate = iso => iso ? new Date(iso).toLocaleString() : "";

/* header brand from <title> ("Name — Admin"), last word gold */
(function brand() {
  const el = document.getElementById("brand");
  if (!el) return;
  const name = (document.title.split("—")[0] || document.title).trim();
  const words = name.split(" ");
  const last = words.pop();
  el.innerHTML = `${esc(words.join(" "))} <span>${esc(last)}</span>`;
})();

async function api(path) {
  const r = await fetch(path);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}

let CSRF = "";      // from /api/me; needed for the invite POST

async function postJSON(path, data) {
  const r = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": CSRF},
    body: JSON.stringify(data)});
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
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

/* Per-campaign progress. Works only against a backend that exposes the
   funnel endpoint; older servers just show nothing here. */
async function renderCampaignFunnels() {
  const box = document.getElementById("funnels");
  let campaigns = [];
  try { campaigns = await api("/api/campaigns"); }
  catch (e) { box.innerHTML = ""; return; }
  if (!campaigns.length) {
    box.innerHTML = `<p class="muted small">No shared campaigns yet. Share
      a test from its page in the main app to recruit contributors.</p>`;
    return;
  }
  const cards = await Promise.all(campaigns.map(async c => {
    let funnel = "";
    try {
      funnel = funnelHTML(await api(`/api/tests/${c.test_id}/funnel`));
    } catch (e) {
      funnel = `<p class="muted small">Progress numbers aren't available
        for this campaign.</p>`;
    }
    return `<div class="card">
      <div class="rowline">
        <h3 style="margin:0">${esc(c.name)}</h3>
        <span class="chip chip-dim">${c.n_variants} copies</span>
      </div>
      <div class="funnel">${funnel}</div>
    </div>`;
  }));
  box.innerHTML = cards.join("");
}

async function main() {
  let stats, cfg = {};
  try { stats = await api("/api/admin/stats"); }
  catch (e) {
    view.innerHTML = `<div class="card"><p>${esc(e.message)}</p>
      <p class="muted small">Sign in on the <a href="/">main app</a> with an
      admin account first.</p></div>`;
    return;
  }
  try {
    cfg = await api("/api/config");
    CSRF = (await api("/api/me")).csrf;
  } catch (e) { /* invite card just won't render */ }
  const fb = stats.feedback || {};
  const labeled = (fb.correct || 0) + (fb.wrong || 0);
  view.innerHTML = `
  <h1>Crowdsourcing dashboard</h1>
  <div class="statgrid">
    <div class="stat"><span class="bignum">${stats.users}</span>
      <span class="muted small">contributors</span></div>
    <div class="stat"><span class="bignum">${stats.tests}</span>
      <span class="muted small">tests</span></div>
    <div class="stat"><span class="bignum">${stats.scans_real}</span>
      <span class="muted small">real photos</span></div>
    <div class="stat"><span class="bignum">${stats.scans_attributed}</span>
      <span class="muted small">attributed</span></div>
    <div class="stat"><span class="bignum">${fb.correct || 0}</span>
      <span class="muted small">confirmed correct</span></div>
    <div class="stat"><span class="bignum">${fb.wrong || 0}</span>
      <span class="muted small">confirmed wrong</span></div>
    <div class="stat"><span class="bignum">${fb.unsure || 0}</span>
      <span class="muted small">unsure</span></div>
    <div class="stat"><span class="bignum">${labeled}</span>
      <span class="muted small">exportable labels</span></div>
  </div>
  <div class="rowline" style="margin:1.2rem 0">
    <a class="btn btn-gold" href="/api/admin/export">Download corpus export
      (zip)</a>
    <span class="muted small">real captures with confirmed ground truth,
      intake-style sidecars</span>
  </div>
  ${cfg.mode === "server" ? `
  <h2>Invite a contributor</h2>
  <div class="card">
    <p class="muted small">Accounts are invite-only: create a single-use
    link (valid for a few days) and send it to the contributor yourself —
    the server sends no email.</p>
    <form id="inviteform" class="rowline">
      <input type="email" id="inv-email" required
             placeholder="contributor@example.org"
             style="flex:1;min-width:12rem">
      <button class="btn btn-gold" type="submit">Create invite link</button>
    </form>
    <p class="small" id="inv-out" style="word-break:break-all"></p>
  </div>` : ""}
  <h2>Recover a campaign from a key</h2>
  <div class="card">
    <p class="muted small">Import a recovery key exported from another
    installation to investigate a leak here — even if this machine never had the
    campaign. Imported campaigns are <strong>investigation-only</strong>: you can
    attribute leaked photos, but not generate new copies.</p>
    <div class="rowline">
      <input type="file" id="imp-file" accept=".json,application/json">
      <input type="password" id="imp-pass" autocomplete="off"
             placeholder="Passphrase (if the key is encrypted)"
             style="min-width:14rem">
      <button class="btn btn-gold" id="imp-btn">Import recovery key</button>
    </div>
    <div id="imp-out" class="small" style="margin-top:0.5rem;word-break:break-all"></div>
  </div>
  <h2>Campaign progress</h2>
  <div id="funnels"><div class="skel skel-row"></div></div>
  <h2>Latest contributions</h2>
  <div id="contribs"><div class="skel skel-row"></div></div>`;

  const invForm = document.getElementById("inviteform");
  if (invForm) invForm.onsubmit = async e => {
    e.preventDefault();
    const out = document.getElementById("inv-out");
    out.textContent = "";
    try {
      const r = await postJSON("/api/admin/invite",
        {email: document.getElementById("inv-email").value.trim()});
      out.innerHTML = `Send this link (single-use, expires in
        ${r.expires_days} days):<br>
        <code>${esc(location.origin + r.invite_path)}</code>`;
    } catch (err) { out.textContent = err.message; }
  };

  const impBtn = document.getElementById("imp-btn");
  if (impBtn) impBtn.onclick = async () => {
    const out = document.getElementById("imp-out");
    const f = document.getElementById("imp-file").files[0];
    if (!f) { out.textContent = "Choose a recovery key (.fdkey.json) first."; return; }
    const fd = new FormData();
    fd.append("file", f);
    fd.append("passphrase", document.getElementById("imp-pass").value);
    impBtn.disabled = true;
    out.textContent = "Verifying and importing…";
    try {
      const r = await fetch("/api/import-recovery-key",
        {method: "POST", headers: {"X-CSRF-Token": CSRF}, body: fd});
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const d = body.detail || {};
        if (d.code === "passphrase_required")
          out.textContent = "This key is encrypted — enter its passphrase and import again.";
        else if (d.code === "incorrect_passphrase")
          out.textContent = "Incorrect passphrase. Check it and try again.";
        else if (d.code === "conflict")
          out.innerHTML = "A different version of this campaign already exists "
            + "here — refused (nothing was overwritten). Compare the digests:<br>"
            + `local codebook: <code>${esc(d.local_codebook_sha256)}</code><br>`
            + `key codebook:&nbsp; <code>${esc(d.imported_codebook_sha256)}</code>`;
        else
          out.textContent = (typeof d === "string" ? d : d.message)
            || "The recovery key could not be imported.";
        return;
      }
      if (body.status === "already_present")
        out.textContent = "This campaign is already present here with an "
          + "identical codebook — nothing to do.";
      else
        out.innerHTML = `Imported <strong>${esc(body.test_id)}</strong> — `
          + `${body.n_copies} copies, ${body.n_recipients} recipient(s). `
          + `<a href="/#/test/${esc(body.test_id)}">Open it to investigate a leak.</a>`;
    } catch (e) { out.textContent = e.message; }
    finally { impBtn.disabled = false; }
  };

  renderCampaignFunnels();

  const rows = await api("/api/admin/contributions?limit=100");
  const box = document.getElementById("contribs");
  if (!rows.length) {
    box.innerHTML = `<div class="card empty">
      <p>None yet. They'll appear here the moment a contributor uploads a
      photo.</p></div>`;
    return;
  }
  box.innerHTML = `<div class="table-scroll"><table>
    <tr><th>when</th><th>who</th><th>test</th><th>predicted</th>
        <th>p (adj)</th><th>judgment</th><th>truth</th><th>capture</th></tr>` +
    rows.map(r => {
      const cm = JSON.parse(r.capture_meta || "{}");
      return `<tr>
        <td>${fmtDate(r.created_utc)}</td>
        <td>${esc(r.email)}</td>
        <td>${esc(r.test_id)}</td>
        <td>${r.attributed ? esc(r.predicted_doc_id) : "—"}</td>
        <td>${r.p_adj != null ? r.p_adj.toExponential(1) : "—"}</td>
        <td>${esc(r.judgment || "pending")}</td>
        <td>${esc(r.true_doc_id || "—")}</td>
        <td class="small">${esc([cm.printer, cm.phone, cm.lighting]
          .filter(v => v && v !== "unknown").join(", "))}</td>
      </tr>`;
    }).join("") + `</table></div>`;
}
main();
