// SPDX-License-Identifier: Apache-2.0
/* Volunteer portal glue. Static-only: everything server-side lives in a
 * free-tier Supabase project (auth = magic link, Postgres, Storage).
 *
 * SETUP (one time, ~10 minutes):
 *   1. Create a free project at supabase.com.
 *   2. Run docs/volunteer-portal/schema.sql in its SQL editor.
 *   3. Create a PRIVATE storage bucket named "captures".
 *   4. Paste the project URL and anon (public) key below and redeploy the
 *      demo site. The anon key is safe to publish; row-level security in
 *      the schema is what protects the data.
 *   5. Generate packs (app/tools/make_volunteer_packs.py) so demo/packs/
 *      exists, and INSERT the pack rows (the tool prints index.json; see
 *      schema.sql tail for the one-line import).
 */
const SUPABASE_URL = "PASTE_SUPABASE_URL_HERE";
const SUPABASE_ANON_KEY = "PASTE_SUPABASE_ANON_KEY_HERE";

const configured = !SUPABASE_URL.startsWith("PASTE_");
const $ = (id) => document.getElementById(id);
let sb = null;
let me = null;
let myPack = null;

function setStatus(el, msg, cls) {
  el.textContent = msg;
  el.className = cls || "muted";
}

async function init() {
  if (!configured) {
    $("setup-banner").hidden = false;
    $("btn-login").disabled = true;
    return;
  }
  sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  const { data: { session } } = await sb.auth.getSession();
  if (session) await onSignedIn(session.user);
  sb.auth.onAuthStateChange(async (_evt, sess) => {
    if (sess && !me) await onSignedIn(sess.user);
  });
}

$("btn-login").addEventListener("click", async () => {
  const email = $("email").value.trim();
  if (!email) return setStatus($("auth-status"), "Enter your email.", "err");
  setStatus($("auth-status"), "Sending magic link…");
  const { error } = await sb.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: window.location.href },
  });
  setStatus($("auth-status"),
    error ? "Could not send link: " + error.message
          : "Check your inbox and click the sign-in link.",
    error ? "err" : "ok");
});

async function onSignedIn(user) {
  me = user;
  setStatus($("auth-status"), "Signed in as " + user.email, "ok");
  $("pack-card").hidden = false;
  $("upload-card").hidden = false;
  $("subs-card").hidden = false;
  await ensurePack();
  await refreshSubs();
}

async function ensurePack() {
  // one pack per volunteer; claim_pack() is atomic (see schema.sql)
  const { data, error } = await sb.rpc("claim_pack");
  if (error) {
    setStatus($("pack-status"), "Pack claim failed: " + error.message, "err");
    return;
  }
  myPack = data;
  if (!myPack) {
    setStatus($("pack-status"),
      "All packs are currently claimed: email us and we'll add more.",
      "err");
    return;
  }
  setStatus($("pack-status"), "Your pack: " + myPack.pack_id, "ok");
  const a = $("pack-link");
  a.href = myPack.url;
  a.hidden = false;
}

$("btn-submit").addEventListener("click", async () => {
  const st = $("submit-status");
  if (!me || !myPack) return setStatus(st, "Sign in first.", "err");
  if (!$("f-consent").checked)
    return setStatus(st, "Please confirm the consent checkbox.", "err");
  const orig = $("f-original").files[0];
  const msgd = $("f-messaged").files[0];
  const messaging = $("f-messaging").value;
  if (!orig) return setStatus(st, "Attach the original photo.", "err");
  if (messaging !== "none" && !msgd)
    return setStatus(st, "Attach the received (messaged) copy.", "err");

  $("btn-submit").disabled = true;
  setStatus(st, "Uploading…");
  try {
    const stamp = Date.now();
    const up = async (file, tag) => {
      if (!file) return null;
      const path = `${me.id}/${stamp}_${tag}_${file.name.replace(/[^\w.\-]/g, "_")}`;
      const { error } = await sb.storage.from("captures")
        .upload(path, file, { upsert: false });
      if (error) throw error;
      return path;
    };
    const originalPath = await up(orig, "orig");
    const messagedPath = await up(msgd, "msgd");
    const row = {
      volunteer: me.id,
      pack_id: myPack.pack_id,
      sheet: $("f-sheet").value,
      phone_tier: $("f-phone").value,
      angle: parseInt($("f-angle").value, 10),
      lighting: $("f-lighting").value,
      framing: $("f-framing").value,
      messaging: messaging,
      original_path: originalPath,
      messaged_path: messagedPath,
      note: $("f-note").value.slice(0, 500),
      consent: true,
    };
    const { error } = await sb.from("captures").insert(row);
    if (error) throw error;
    setStatus(st, "Uploaded: thank you!", "ok");
    $("f-original").value = "";
    $("f-messaged").value = "";
    await refreshSubs();
  } catch (e) {
    setStatus(st, "Upload failed: " + (e.message || e), "err");
  } finally {
    $("btn-submit").disabled = false;
  }
});

async function refreshSubs() {
  const { data, error } = await sb.from("captures")
    .select("created_at, sheet, phone_tier, angle, lighting, framing, messaging, original_path, messaged_path")
    .order("created_at", { ascending: false });
  if (error) return;
  $("subs-body").innerHTML = (data || []).map((r) => `
    <tr>
      <td>${new Date(r.created_at).toLocaleString()}</td>
      <td>${r.sheet}</td>
      <td>${r.phone_tier}, ${r.angle}&deg;, ${r.lighting}, ${r.framing}, ${r.messaging}</td>
      <td>${r.original_path ? "orig" : ""}${r.messaged_path ? " + messaged" : ""}</td>
    </tr>`).join("");
}

init();
