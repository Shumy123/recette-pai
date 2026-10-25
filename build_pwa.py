#!/usr/bin/env python3
"""Build the installable version of Recettes PAI (GitHub Pages + Firebase) from recettes-pai.html.

Usage: python3 build_pwa.py <out_dir>
The Claude artifact stays the source of truth; this script swaps the Claude runtime for Firebase
(Google sign-in + Firestore), points photos at files shipped with the site, and adds the PWA shell.
Each patch must match exactly once, so a change in the source fails loudly instead of silently.
"""
import sys, pathlib

SRC = pathlib.Path(__file__).with_name("recettes-pai.html")
out = pathlib.Path(sys.argv[1])
html = SRC.read_text(encoding="utf-8")


def patch(old, new):
    global html
    n = html.count(old)
    if n != 1:
        sys.exit(f"patch matched {n} times: {old[:70]!r}")
    html = html.replace(old, new)


HEAD = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ff5d8f">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icons/icon-192.png">
<link rel="apple-touch-icon" href="icons/icon-192.png">
<title>Recettes PAI</title>"""
patch('<title>Recettes PAI</title>\n<meta name="claude:viewport-fit-sides" content="cover">', HEAD)
patch("</style>\n\n<div class=\"wrap\">", """.login { display: grid; gap: 14px; justify-items: center; text-align: center; padding: 40px 8px; }
.login .btn { min-width: 240px; }
</style>
</head>
<body>

<div class="wrap">""")

# Photos: Claude assets become files in photos/; photos added in the app live in Firestore as "fs:<id>".
patch('function photoSrc(id) { return state.photoUrls[id] || "/_blob/" + id; }',
      'function photoSrc(id) { return state.photoUrls[id] || (String(id).startsWith("fs:") ? "" : "photos/" + id + ".jpg"); }')
patch("""  async function envoyerPhoto(file) {
    const blob = await reduirePhoto(file);
    const r = await state.assets.upload(blob, { type: blob.type && /^image\\/(jpeg|png|webp|gif)$/.test(blob.type) ? blob.type : "image/jpeg" });
    state.photoUrls[r.id] = r.url;
    return r.id;
  }
  function oublierPhoto(id) { if (id && state.assets) state.assets.delete(id).catch(() => {}); }""",
      """  // A Firestore document holds at most 1 MB, so photos are kept small (900 px) and stored as data URLs.
  async function envoyerPhoto(file) {
    const blob = await reduirePhoto(file, 900, 0.72);
    const data = await new Promise((ok, ko) => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.onerror = ko; fr.readAsDataURL(blob); });
    if (data.length > 900000) throw { code: "too_large" };
    const ref = store.db.collection("photos").doc();
    await ref.set({ data });
    const id = "fs:" + ref.id;
    state.photoUrls[id] = data;
    return id;
  }
  function oublierPhoto(id) { if (id && String(id).startsWith("fs:") && store.db) store.db.collection("photos").doc(id.slice(3)).delete().catch(() => {}); }""")
patch("async function reduirePhoto(file) {", "async function reduirePhoto(file, max = 1280, q = 0.82) {")
patch("const k = Math.min(1, 1280 / Math.max(img.naturalWidth, img.naturalHeight));",
      "const k = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));")
patch('c.toBlob(ok, "image/jpeg", 0.82)', 'c.toBlob(ok, "image/jpeg", q)')

# Sign-in screen takes over the page until a family account is signed in.
patch("""    let kids;
    if (!state.reglagesCharges)""", """    document.querySelector("nav.tabs").hidden = !!state.ecran;
    if (state.ecran) {
      pill.hidden = true;
      $view.replaceChildren(h("div", { class: "wrap", style: "gap:18px" }, state.ecran()));
      return;
    }
    let kids;
    if (!state.reglagesCharges)""")

# Boot: Firebase instead of the Claude runtime.
start = html.index("  render();\n  (async function () {\n    let db = null, user = null, sample = null;")
end = html.index("  })();\n})();\n</script>") + len("  })();\n")
BOOT = r"""  render();

  function ecranConnexion(message) {
    return () => [h("div", { class: "login" },
      h("h2", { text: "Bienvenue" }),
      h("p", { class: "muted", text: message || "Connecte-toi avec ton compte Google pour retrouver vos recettes et vos sacs." }),
      h("button", { class: "btn", type: "button", text: "Se connecter avec Google", onclick: connecter }))];
  }
  function ecranRefus(email) {
    return () => [h("div", { class: "login" },
      h("h2", { text: "Accès réservé" }),
      h("p", { class: "muted", text: "Le compte " + email + " n'a pas accès à cette appli. Connecte-toi avec un compte du foyer." }),
      h("button", { class: "btn", type: "button", text: "Changer de compte", onclick: () => firebase.auth().signOut() }))];
  }
  function messageConnexion(e) {
    const c = (e && e.code) || "inconnu";
    if (c === "auth/unauthorized-domain") return "Firebase ne connaît pas encore ce site. Dans Firebase : Authentication, Settings, Authorized domains, ajoute " + location.hostname + ". (" + c + ")";
    if (c === "auth/operation-not-allowed") return "La connexion Google n'est pas activée dans Firebase : Authentication, Sign-in method, Google, Enable. (" + c + ")";
    if (c === "auth/network-request-failed") return "Pas de connexion internet. Réessaie. (" + c + ")";
    return "La connexion n'a pas marché. Réessaie. (" + c + ")";
  }
  async function connecter() {
    const p = new firebase.auth.GoogleAuthProvider();
    p.setCustomParameters({ prompt: "select_account" });
    try { await firebase.auth().signInWithPopup(p); }
    catch (e) {
      if (e && (e.code === "auth/popup-blocked" || e.code === "auth/operation-not-supported-in-this-environment")) return firebase.auth().signInWithRedirect(p);
      if (e && e.code !== "auth/popup-closed-by-user" && e.code !== "auth/cancelled-popup-request") { state.ecran = ecranConnexion(messageConnexion(e)); render(); }
    }
  }

  // First sign-in on an empty base: copy the data exported from the Claude version.
  async function importerSiVide(db) {
    const deja = await db.collection("recettes").limit(1).get();
    if (!deja.empty) return;
    let seed;
    try { const r = await fetch("data/seed.json", { cache: "no-store" }); if (!r.ok) return; seed = await r.json(); } catch (e) { return; }
    const ecrits = [];
    if (seed.reglages) ecrits.push([db.doc("reglages/foyer"), seed.reglages]);
    for (const col of ["recettes", "menus", "paniers"]) for (const [id, d] of Object.entries(seed[col] || {})) ecrits.push([db.collection(col).doc(id), d]);
    const banner = document.getElementById("banner");
    banner.textContent = "Première ouverture : je range vos recettes…"; banner.hidden = false;
    for (let i = 0; i < ecrits.length; i += 400) {
      const b = db.batch();
      ecrits.slice(i, i + 400).forEach(([ref, d]) => b.set(ref, d));
      await b.commit();
    }
    banner.hidden = true;
  }

  // Recipes Claude adds each week ship in data/nouveautes.json. Each one is copied into the base once,
  // so a recipe the family deletes does not come back.
  async function importerNouveautes(db) {
    let n;
    try { const r = await fetch("data/nouveautes.json", { cache: "no-store" }); if (!r.ok) return; n = await r.json(); } catch (e) { return; }
    const ref = db.doc("reglages/nouveautes");
    const vus = ((await ref.get()).data() || {}).ids || [];
    const ids = Object.keys(n.recettes || {}).filter(id => !vus.includes(id));
    if (!ids.length) return;
    const b = db.batch();
    ids.forEach(id => b.set(db.collection("recettes").doc(id), n.recettes[id]));
    b.set(ref, { ids: vus.concat(ids) });
    await b.commit();
  }

  let abonnements = [];
  function demarrer(db) {
    store.mode = "db"; store.db = db;
    state.assets = true;
    const ecoute = (q, ok, ko) => abonnements.push(q.onSnapshot(ok, ko));
    ecoute(db.doc("reglages/foyer"), snap => {
      state.reglages = snap.exists ? snap.data() : null;
      state.reglagesCharges = true;
      refreshSafe();
    }, () => { state.reglagesCharges = true; render(); });
    ecoute(db.collection("recettes"), snap => {
      state.recettes = snap.docs.map(d => Object.assign({ id: d.id }, d.data()));
      state.recettesChargees = true;
      refreshSafe();
    }, () => { state.recettesChargees = true; render(); });
    ecoute(db.collection("paniers"), snap => {
      const m = {}; snap.docs.forEach(d => { m[d.id] = d.data(); });
      state.paniers = m;
      refreshSafe();
    }, () => {});
    ecoute(db.collection("menus"), snap => {
      const m = {}; snap.docs.forEach(d => { m[d.id] = d.data(); });
      state.menus = m; state.menusCharges = true;
      if (!state.jourSel || !tousJours()[state.jourSel]) state.jourSel = jourParDefaut();
      refreshSafe();
    }, () => { state.menusCharges = true; render(); });
    ecoute(db.collection("photos"), snap => {
      snap.docs.forEach(d => { state.photoUrls["fs:" + d.id] = d.data().data; });
      refreshSafe();
    }, () => {});
  }

  if (!window.firebase || !window.FIREBASE_CONFIG) {
    bootLocal("Mode hors ligne : tes recettes sont gardées sur cet appareil seulement.");
  } else {
    firebase.initializeApp(window.FIREBASE_CONFIG);
    const db = firebase.firestore();
    try { db.enablePersistence({ synchronizeTabs: true }).catch(() => {}); } catch (e) {}
    firebase.auth().onAuthStateChanged(async user => {
      abonnements.forEach(u => u()); abonnements = [];
      if (!user) { state.ecran = ecranConnexion(); render(); return; }
      try { await db.doc("reglages/foyer").get(); }
      catch (e) { if (e && e.code === "permission-denied") { state.ecran = ecranRefus(user.email); render(); return; } }
      state.ecran = null;
      try { await importerSiVide(db); } catch (e) {}
      try { await importerNouveautes(db); } catch (e) {}
      demarrer(db);
    });
  }
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
"""
html = html[:start] + BOOT + html[end:]

html = html.rstrip() + "\n</body>\n</html>\n"
html = html.replace("<script>\n(function () {",
                    """<script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-auth-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore-compat.js"></script>
<script src="firebase-config.js"></script>
<script>
(function () {""", 1)

out.mkdir(parents=True, exist_ok=True)
(out / "index.html").write_text(html, encoding="utf-8")
print("wrote", out / "index.html", len(html), "bytes")
