#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""sim300: stress-test simulation harness for a 300-contributor campaign.

Question answered: if N contributors each print a different fingerprinted
variant of the same document and photograph it at various angles/qualities,
how many does the system identify correctly, and does it ever accuse the
wrong variant?

Phases (combinable flags; running with no phase flag runs all four):
  --build     create one test with N marked variants + 3 unmarked controls
              using the app engine's own generation path. Default document:
              docs/Niraj_Kasar_Resume_2025 (1).pdf via the formatting-
              preserving PDF path (engine.render_pdf.generate_pdf_test, the
              same function serve.py's pdf_preserved mode runs). --text
              falls back to the rendered text mode (render.generate_test)
              with render.SAMPLE_TEXT extended to >= 4 pages.
  --simulate  degrade every page PNG deterministically: perspective tilt
              (0/15/30/45 deg keystone from real projective geometry) +
              seeded in-plane jitter +/-2 deg + blur 0.6 + noise 2/255 +
              a messaging resize/JPEG chain (wa | wa2x | harsh | brutal).
  --score     run the app's scan attribution over every degraded capture,
              in parallel. NO custom decoder: scoring calls
              engine.scan_pdf.attribute (pdf_preserved) or
              engine.scan.attribute (text mode) -- exactly the functions
              serve.py's upload route dispatches to
              (`runner = scan_pdf if type == "pdf_preserved" else scan`).
  --report    aggregate rows.csv into sim300/out/summary.md and a
              per-capture inspection page sim300/out/report.html.

Everything lives under sim300/out/ (gitignored). FF_APPDATA defaults to
sim300/out/appdata; FF_FONT_PATH defaults to C:\\Windows\\Fonts\\times.ttf.

Typical runs:
  python sim300/run_sim.py --limit 12            # smoke: all four phases
  python sim300/run_sim.py                       # full 300-variant run
"""
import argparse
import csv
import json
import math
import multiprocessing as mp
import os
import re
import shutil
import sys
import threading
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
APP = os.path.join(REPO, "app")
OUT = os.path.join(HERE, "out")
CAPTURES = os.path.join(OUT, "captures")
SCANWORK = os.path.join(OUT, "scanwork")
STATE = os.path.join(OUT, "state.json")
ROWS_CSV = os.path.join(OUT, "rows.csv")
PERCAND = os.path.join(OUT, "percand.jsonl")
CAPT_MANIFEST = os.path.join(OUT, "captures.jsonl")

DEFAULT_PDF = os.path.join(REPO, "docs", "Niraj_Kasar_Resume_2025 (1).pdf")
DEFAULT_FONT = r"C:\Windows\Fonts\times.ttf"
N_CONTROLS = 3

ANGLES = [0, 15, 30, 45]
CHAIN_ORDER = ["wa", "wa2x", "harsh", "brutal"]
CHAINS = {
    "wa":     [(1600, 78)],
    "wa2x":   [(1600, 78), (1600, 78)],
    "harsh":  [(1200, 60)],
    "brutal": [(1000, 45)],
}
BLUR_SIGMA = 0.6
NOISE_SIGMA = 2.0            # on the 0..255 scale (= 2/255 of full range)
JITTER_MAX = 2.0             # +/- deg in-plane rotation
CONTROL_ANGLES = [0, 15, 30]

CSV_FIELDS = [
    "capture_id", "doc_id", "marked", "page", "angle_deg", "chain",
    "jitter_deg", "blur_sigma", "noise_sigma", "chain_steps", "capture_path",
    "path_used", "n_lines_found", "page_matched", "attributed_doc",
    "correct", "wrong_accusation", "abstained", "argmax_doc",
    "argmax_correct", "acc", "true_acc", "n_obs", "p_value", "p_adj",
    "margin", "runner_up_margin", "scan_seconds", "error",
]


# ---- environment ---------------------------------------------------------------
def ensure_env():
    os.environ.setdefault("FF_FONT_PATH", DEFAULT_FONT)
    os.environ.setdefault("FF_APPDATA", os.path.join(OUT, "appdata"))
    if APP not in sys.path:
        sys.path.insert(0, APP)


def load_state():
    if not os.path.exists(STATE):
        sys.exit("no sim300/out/state.json -- run --build first")
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def save_state(st):
    os.makedirs(OUT, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


def mark_timing(st, phase, seconds, extra=None):
    st.setdefault("timings", {})[phase] = {
        "seconds": round(seconds, 1), **(extra or {})}
    save_state(st)


# ---- build ---------------------------------------------------------------------
def build_phase(args):
    ensure_env()
    from engine import store            # noqa: E402  (needs env first)

    mode = "text" if (args.text or args.text_file) else "pdf"
    n = args.n if not args.limit else min(args.n, args.limit)
    if args.text_file:
        if not os.path.exists(args.text_file):
            sys.exit(f"[build] --text-file not found: {args.text_file}")
        test_id = f"sim{n}-{_corpus_stem(args.text_file)}"
    else:
        test_id = f"sim{n}-{mode}"
    labels = [f"Contributor {i + 1}" for i in range(n)]

    # Idempotent: skip when this exact corpus is already generated.
    mp_path = store.manifest_path(test_id)
    if os.path.exists(mp_path):
        m = store.load_manifest(test_id)
        marked = [d for d in m.get("docs", []) if d.get("marked")]
        if m.get("status") == "generated" and len(marked) == n:
            print(f"[build] corpus {test_id} already generated "
                  f"({len(marked)} variants + "
                  f"{len(m['docs']) - len(marked)} controls) -- skipping")
            _write_build_state(args, m, test_id, mode, n, rebuilt=False)
            return

    t0 = time.perf_counter()
    docs_dir = os.path.join(store.test_dir(test_id), "docs")
    stop = threading.Event()

    def monitor():
        last = -1
        total = n + N_CONTROLS
        while not stop.wait(2.0):
            try:
                done = len(os.listdir(docs_dir))
            except OSError:
                done = 0
            if done // 25 > last // 25 or done == total:
                print(f"[build] ~{done}/{total} docs generated "
                      f"({time.perf_counter() - t0:.0f}s)")
                last = done
            if done >= total:
                return

    th = threading.Thread(target=monitor, daemon=True)
    th.start()
    try:
        if mode == "pdf":
            from engine import render_pdf
            pdf_path = args.pdf
            if not os.path.exists(pdf_path):
                sys.exit(f"[build] source PDF not found: {pdf_path}")
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            print(f"[build] pdf_preserved corpus {test_id}: {n} variants + "
                  f"{N_CONTROLS} controls from {os.path.basename(pdf_path)}")
            m = render_pdf.generate_pdf_test(
                f"Sim {n} stress test", pdf_bytes, labels, N_CONTROLS,
                test_id, source_filename=os.path.basename(pdf_path))
        else:
            from engine import render
            text = build_text_content(args)
            src = (os.path.basename(args.text_file) if args.text_file
                   else "SAMPLE_TEXT")
            print(f"[build] text-mode corpus {test_id} (from {src}): {n} "
                  f"variants + {N_CONTROLS} controls, "
                  f"{render.dry_layout(text)['pages']} pages")
            m = render.generate_test(f"Sim {n} stress test", text, labels,
                                     N_CONTROLS,
                                     sample_used=not args.text_file,
                                     test_id=test_id)
    finally:
        stop.set()
        th.join(timeout=1)

    dt = time.perf_counter() - t0
    per_doc = dt / (n + N_CONTROLS)
    print(f"[build] done in {dt:.1f}s ({per_doc:.2f}s/doc; a 300-variant "
          f"build extrapolates to ~{per_doc * 303 / 60:.1f} min)")
    _write_build_state(args, m, test_id, mode, n, rebuilt=True,
                       seconds=dt, per_doc=per_doc)


def _corpus_stem(path):
    """Filesystem-safe corpus id derived from a text file's name."""
    base = os.path.splitext(os.path.basename(path))[0]
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return slug or "textfile"


def build_text_content(args=None):
    """Text-mode corpus content. With --text-file, the file's content is used
    verbatim; otherwise SAMPLE_TEXT-style content extended until the layout
    reaches 4 pages (aim 4-5), using the engine's own dry_layout to measure."""
    if args is not None and args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            text = f.read()
        if not text.strip():
            sys.exit(f"[build] --text-file is empty: {args.text_file}")
        return text
    from engine import render
    import encode
    reps = 12
    while True:
        text = " ".join(encode.CORPUS * reps)
        pages = render.dry_layout(text)["pages"]
        if pages >= 4:
            return text
        reps += 2


def _measure_capacity(mode, test_id):
    """Measured markable capacity, from the engine's own analysis."""
    from engine import store
    if mode == "pdf":
        from engine import pdf_mark, render_pdf
        with open(os.path.join(store.test_dir(test_id), "source.pdf"),
                  "rb") as f:
            cap = pdf_mark.capacity(f.read())
        v1 = render_pdf.load_doc_meta(test_id, "v1")
        cap["applied_bits_v1"] = v1.get("n_applied")
        return cap
    m = store.load_manifest(test_id)
    v1 = next(d for d in m["docs"] if d["marked"])
    per_page = [{"page_index": p["page_index"],
                 "line_bits": p["line_bits"], "word_bits": p["word_bits"]}
                for p in v1["pages"]]
    return {"pages": len(per_page), "per_page": per_page,
            "total_bits": sum(p["line_bits"] + p["word_bits"]
                              for p in per_page)}


def _layout_selfcheck(mode, test_id):
    """Scan-side sanity on the PRISTINE v1 render: does the clean segmenter
    reproduce the meta's line structure at all? If not, real photos can
    only ever match via the guided fit, and 'no page match' abstentions are
    a property of the document, not of the degradation."""
    from engine import store
    out = []
    if mode == "pdf":
        from engine import pdf_scan, render_pdf
        meta = render_pdf.load_doc_meta(test_id, "v1")
        for pg in meta["pages"]:
            png = os.path.join(store.test_dir(test_id), "docs", "v1",
                               f"page{pg['page_index']}.png")
            if not pg["bands"]:
                out.append({"page": pg["page_index"],
                            "meta_lines": pg["n_lines_total"],
                            "clean_segmented": None, "clean_match": False,
                            "note": "no markable bands: never scored"})
                continue
            obs = pdf_scan.observe_page(png, pg)
            out.append({"page": pg["page_index"],
                        "meta_lines": pg["n_lines_total"],
                        "clean_segmented": obs.get("n_lines_found"),
                        "clean_match": bool(obs.get("ok"))})
    else:
        import decode as dec
        m = store.load_manifest(test_id)
        v1 = next(d for d in m["docs"] if d["marked"])
        for p in v1["pages"]:
            png = os.path.join(store.test_dir(test_id), "docs", "v1",
                               f"page{p['page_index']}.png")
            g = cv2.imread(png, cv2.IMREAD_GRAYSCALE)
            bands = dec.segment_lines(g)
            out.append({"page": p["page_index"], "meta_lines": p["n_lines"],
                        "clean_segmented": len(bands),
                        "clean_match": len(bands) == p["n_lines"]})
    return out


def _write_build_state(args, manifest, test_id, mode, n, rebuilt,
                       seconds=None, per_doc=None):
    cap = _measure_capacity(mode, test_id)
    sc = _layout_selfcheck(mode, test_id)
    st = load_state() if os.path.exists(STATE) else {}
    st.update({"test_id": test_id, "mode": mode, "n_variants": n,
               "n_controls": N_CONTROLS, "n_pages": manifest["n_pages"],
               "document": (os.path.basename(args.pdf) if mode == "pdf"
                            else (os.path.basename(args.text_file)
                                  if args.text_file
                                  else "SAMPLE_TEXT x reps (text mode)")),
               "capacity": cap, "layout_selfcheck": sc})
    if seconds is not None:
        mark_timing(st, "build", seconds, {"per_doc_s": round(per_doc, 2)})
    else:
        save_state(st)
    print(f"[build] measured capacity per page (line, word bits): "
          f"{[(p['page_index'], p.get('line_bits'),
              p.get('word_bits') or 0) for p in cap['per_page']]}")
    for s in sc:
        print(f"[build] layout self-check page {s['page'] + 1}: clean "
              f"segmentation {s['clean_segmented']} vs meta "
              f"{s['meta_lines']} lines -> "
              f"{'ok' if s['clean_match'] else 'MISMATCH'}"
              + (f" ({s['note']})" if s.get("note") else ""))


# ---- simulate ------------------------------------------------------------------
def tilt_homography(w, h, tilt_deg, jitter_deg, f_factor=1.2, margin=40):
    """Homography of a pinhole camera tilted by tilt_deg about the
    horizontal axis through the page center (top edge farther away ->
    keystone: top compressed relative to bottom), composed with an in-plane
    rotation of jitter_deg. Derived from projective geometry, not corner
    hand-waving: page point (X, Y, 0) -> rotate about X axis -> project
    with focal length f from distance d = f (unit magnification at 0 deg).
    """
    t, j = math.radians(tilt_deg), math.radians(jitter_deg)
    f = f_factor * max(w, h)
    d = f
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float64)
    dst = []
    for x, y in src:
        X, Y = x - w / 2.0, y - h / 2.0
        Z = d - Y * math.sin(t)              # top (Y<0) recedes from camera
        dst.append((f * X / Z, f * Y * math.cos(t) / Z))
    dst = np.array(dst)
    c = dst.mean(axis=0)
    R = np.array([[math.cos(j), -math.sin(j)],
                  [math.sin(j), math.cos(j)]])
    dst = (dst - c) @ R.T + c
    dst -= dst.min(axis=0) - margin
    size = (int(math.ceil(dst[:, 0].max())) + margin,
            int(math.ceil(dst[:, 1].max())) + margin)
    H = cv2.getPerspectiveTransform(src.astype(np.float32),
                                    dst.astype(np.float32))
    return H, size


def degrade(src_png, dst_jpg, tilt_deg, jitter_deg, chain_steps, noise_seed):
    img = cv2.imread(src_png, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"cannot read {src_png}")
    h, w = img.shape
    H, size = tilt_homography(w, h, tilt_deg, jitter_deg)
    cur = cv2.warpPerspective(img, H, size, flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    cur = cv2.GaussianBlur(cur, (0, 0), BLUR_SIGMA)
    rng = np.random.default_rng(noise_seed)
    noisy = cur.astype(np.float64) + rng.normal(0.0, NOISE_SIGMA, cur.shape)
    cur = np.clip(noisy, 0, 255).astype(np.uint8)
    data = None
    for longside, q in chain_steps:
        hh, ww = cur.shape
        s = longside / max(hh, ww)
        if s < 1.0:
            cur = cv2.resize(cur, (int(round(ww * s)), int(round(hh * s))),
                             interpolation=cv2.INTER_AREA)
        ok, data = cv2.imencode(".jpg", cur,
                                [cv2.IMWRITE_JPEG_QUALITY, int(q)])
        if not ok:
            raise RuntimeError("jpeg encode failed")
        cur = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    with open(dst_jpg, "wb") as f:
        f.write(data.tobytes())


def variant_cell(idx):
    """Deterministic grid cell for variant index idx (0-based):
    angle cycles fastest, chain every 4 variants. 300 variants -> 18-19
    per cell; a 12-variant smoke covers all four angles x three chains."""
    return ANGLES[idx % 4], CHAIN_ORDER[(idx // 4) % 4]


def jitter_for(idx):
    return round(float(np.random.default_rng(555_000 + idx)
                       .uniform(-JITTER_MAX, JITTER_MAX)), 2)


def simulate_phase(args):
    ensure_env()
    from engine import store
    st = load_state()
    test_id = st["test_id"]
    m = store.load_manifest(test_id)
    marked = [d for d in m["docs"] if d["marked"]]
    controls = [d for d in m["docs"] if not d["marked"]]
    if args.limit:
        marked = marked[:args.limit]

    # Regenerated deterministically every run; clear stale captures from a
    # previous corpus so report.html never shows orphans.
    shutil.rmtree(CAPTURES, ignore_errors=True)
    os.makedirs(CAPTURES, exist_ok=True)
    t0 = time.perf_counter()
    records, count = [], 0

    def one(doc, page, angle, chain, jitter, seed_idx):
        cid = f"{doc['doc_id']}_p{page}_a{angle}_{chain}"
        dst = os.path.join(CAPTURES, cid + ".jpg")
        steps = CHAINS[chain]
        degrade(os.path.join(store.test_dir(test_id), "docs", doc["doc_id"],
                             f"page{page}.png"),
                dst, angle, jitter, steps, noise_seed=seed_idx)
        records.append({
            "capture_id": cid, "doc_id": doc["doc_id"],
            "marked": doc["marked"], "page": page, "angle_deg": angle,
            "chain": chain, "jitter_deg": jitter,
            "blur_sigma": BLUR_SIGMA, "noise_sigma": NOISE_SIGMA,
            "chain_steps": [list(s) for s in steps],
            "capture_path": f"captures/{cid}.jpg"})

    for i, doc in enumerate(marked):
        idx = int(doc["doc_id"][1:]) - 1
        angle, chain = variant_cell(idx)
        jit = jitter_for(idx)
        for page in range(m["n_pages"]):
            one(doc, page, angle, chain, jit,
                seed_idx=(idx + 1) * 1000 + page)
            count += 1
        if (i + 1) % 25 == 0 or i + 1 == len(marked):
            print(f"[simulate] {i + 1}/{len(marked)} variants degraded "
                  f"({time.perf_counter() - t0:.0f}s)")

    for c, doc in enumerate(controls):
        angle = CONTROL_ANGLES[c % len(CONTROL_ANGLES)]
        jit = jitter_for(100_000 + c)
        for page in range(m["n_pages"]):
            one(doc, page, angle, "wa", jit,
                seed_idx=9_000_000 + c * 100 + page)
            count += 1
    print(f"[simulate] {len(controls)} controls degraded (wa chain, angles "
          f"{CONTROL_ANGLES})")

    with open(CAPT_MANIFEST, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    dt = time.perf_counter() - t0
    per = dt / max(count, 1)
    full = (300 * m["n_pages"] + N_CONTROLS * m["n_pages"]) * per
    print(f"[simulate] {count} captures in {dt:.1f}s ({per:.2f}s/capture; "
          f"full 300-variant run ~{full / 60:.1f} min)")
    mark_timing(st, "simulate", dt,
                {"captures": count, "per_capture_s": round(per, 2)})


# ---- score ---------------------------------------------------------------------
_G = {}


def init_worker(appdata, font, test_id, scanwork, keep_work):
    os.environ["FF_APPDATA"] = appdata
    os.environ["FF_FONT_PATH"] = font
    if APP not in sys.path:
        sys.path.insert(0, APP)
    import functools
    from engine import store, scan, scan_pdf, render, render_pdf
    # Meta-load caching only (pure IO memoization; scoring code untouched).
    scan_pdf.load_doc_meta = functools.lru_cache(maxsize=None)(
        render_pdf.load_doc_meta)
    scan.load_page_meta = functools.lru_cache(maxsize=None)(
        render.load_page_meta)
    _G.update(manifest=store.load_manifest(test_id), scan=scan,
              scan_pdf=scan_pdf, scanwork=scanwork, keep=keep_work)
    cv2.setNumThreads(1)     # one OpenCV thread per worker process


def score_one(task):
    """Score one degraded capture with the app's own attribution function
    (the exact code path behind POST /api/tests/{id}/scan)."""
    m = _G["manifest"]
    runner = _G["scan_pdf"] if m.get("type") == "pdf_preserved" \
        else _G["scan"]
    wd = os.path.join(_G["scanwork"], task["capture_id"])
    os.makedirs(wd, exist_ok=True)
    img = os.path.join(OUT, task["capture_path"].replace("/", os.sep))
    source = {"kind": "sim300", "label": "stress-sim degraded render",
              "synthetic": True, "capture_id": task["capture_id"]}
    t0 = time.perf_counter()
    err = ""
    try:
        res = runner.attribute(m, img, wd, source)
    except Exception as e:                                  # noqa: BLE001
        res, err = {}, f"{type(e).__name__}: {e}"
    dt = time.perf_counter() - t0
    if not _G["keep"]:
        shutil.rmtree(wd, ignore_errors=True)

    verdict = res.get("verdict") or {}
    scores = res.get("scores") or []
    cands = {r["doc_id"]: [r["ok"], r["tot"]] for r in scores}
    attributed = bool(verdict.get("attributed"))
    attributed_doc = verdict.get("doc_id") or ""
    argmax_doc = scores[0]["doc_id"] if scores else ""
    true_row = next((r for r in scores if r["doc_id"] == task["doc_id"]),
                    None)
    is_marked = bool(task["marked"])
    correct = (attributed and attributed_doc == task["doc_id"]) \
        if is_marked else (not attributed)
    wrong = attributed and (not is_marked
                            or attributed_doc != task["doc_id"])
    row = {
        "capture_id": task["capture_id"], "doc_id": task["doc_id"],
        "marked": is_marked, "page": task["page"],
        "angle_deg": task["angle_deg"], "chain": task["chain"],
        "jitter_deg": task["jitter_deg"], "blur_sigma": task["blur_sigma"],
        "noise_sigma": task["noise_sigma"],
        "chain_steps": ";".join(f"{ls}@q{q}"
                                for ls, q in task["chain_steps"]),
        "capture_path": task["capture_path"],
        "path_used": res.get("path_used") or "",
        "n_lines_found": json.dumps(res.get("n_lines_found"))
        if isinstance(res.get("n_lines_found"), dict)
        else (res.get("n_lines_found") if res.get("n_lines_found")
              is not None else ""),
        "page_matched": res.get("page_index")
        if res.get("page_index") is not None else "",
        "attributed_doc": attributed_doc,
        "correct": correct, "wrong_accusation": wrong,
        "abstained": not attributed,
        "argmax_doc": argmax_doc,
        "argmax_correct": (is_marked and argmax_doc == task["doc_id"])
        if scores else "",
        "acc": verdict.get("acc") if verdict.get("acc") is not None else "",
        "true_acc": (true_row or {}).get("acc")
        if (true_row or {}).get("acc") is not None else "",
        "n_obs": verdict.get("tot") if verdict.get("tot") is not None
        else "",
        "p_value": verdict.get("p_value")
        if verdict.get("p_value") is not None else "",
        "p_adj": verdict.get("p_adj")
        if verdict.get("p_adj") is not None else "",
        "margin": verdict.get("margin")
        if verdict.get("margin") is not None else "",
        "runner_up_margin": round((scores[1]["acc"] or 0)
                                  - (scores[2]["acc"] or 0), 3)
        if len(scores) >= 3 and scores[1]["acc"] is not None else "",
        "scan_seconds": round(dt, 2), "error": err,
    }
    return row, {"capture_id": task["capture_id"],
                 "doc_id": task["doc_id"], "marked": is_marked,
                 "angle_deg": task["angle_deg"], "chain": task["chain"],
                 "cands": cands}


def score_phase(args):
    ensure_env()
    st = load_state()
    if not os.path.exists(CAPT_MANIFEST):
        sys.exit("no captures.jsonl -- run --simulate first")
    with open(CAPT_MANIFEST, encoding="utf-8") as f:
        tasks = [json.loads(line) for line in f if line.strip()]
    if args.limit:
        keep = {f"v{i + 1}" for i in range(args.limit)}
        tasks = [t for t in tasks
                 if not t["marked"] or t["doc_id"] in keep]
    workers = args.workers or max(2, (os.cpu_count() or 8) - 4)
    os.makedirs(SCANWORK, exist_ok=True)
    print(f"[score] {len(tasks)} captures, {workers} workers, "
          f"attribution via engine."
          f"{'scan_pdf' if st['mode'] == 'pdf' else 'scan'}.attribute")

    t0 = time.perf_counter()
    rows = []
    with open(ROWS_CSV, "w", newline="", encoding="utf-8") as cf, \
            open(PERCAND, "w", encoding="utf-8") as pf:
        w = csv.DictWriter(cf, fieldnames=CSV_FIELDS)
        w.writeheader()
        with mp.Pool(workers, initializer=init_worker,
                     initargs=(os.environ["FF_APPDATA"],
                               os.environ["FF_FONT_PATH"],
                               st["test_id"], SCANWORK,
                               args.keep_work)) as pool:
            for i, (row, cand) in enumerate(
                    pool.imap_unordered(score_one, tasks), 1):
                rows.append(row)
                w.writerow(row)
                cf.flush()
                pf.write(json.dumps(cand) + "\n")
                if i % 10 == 0 or i == len(tasks):
                    el = time.perf_counter() - t0
                    print(f"[score] {i}/{len(tasks)} scored "
                          f"({el:.0f}s, {el / i:.1f}s/capture, "
                          f"eta {(len(tasks) - i) * el / i:.0f}s)")
    dt = time.perf_counter() - t0
    per = dt / max(len(tasks), 1)
    n_pages = st.get("n_pages", 2)
    full_caps = 300 * n_pages + N_CONTROLS * n_pages
    print(f"[score] done in {dt:.1f}s ({per:.1f}s/capture with {workers} "
          f"workers; full 300-variant run of {full_caps} captures "
          f"~{full_caps * per / 60:.1f} min)")
    errs = [r for r in rows if r["error"]]
    if errs:
        print(f"[score] WARNING: {len(errs)} captures errored, e.g. "
              f"{errs[0]['capture_id']}: {errs[0]['error']}")
    mark_timing(st, "score", dt, {"captures": len(tasks),
                                  "workers": workers,
                                  "per_capture_s": round(per, 2)})
    if not args.keep_work:
        shutil.rmtree(SCANWORK, ignore_errors=True)


# ---- report --------------------------------------------------------------------
def _binom_p(ok, tot):
    """Exact one-sided binomial tail, safe for pooled totals > 1023 bits
    (engine.scan.binom_p's 2.0**tot overflows there; int/int division
    keeps arbitrary precision)."""
    if tot <= 0:
        return None
    return sum(math.comb(tot, k) for k in range(ok, tot + 1)) / (1 << tot)


def _pct(a, b):
    return f"{100.0 * a / b:.0f}%" if b else "-"


def report_phase(args):
    ensure_env()
    from engine.scan import P_THRESHOLD, MIN_BITS
    st = load_state()
    if not os.path.exists(ROWS_CSV):
        sys.exit("no rows.csv -- run --score first")
    with open(ROWS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["marked"] = r["marked"] == "True"
        r["correct"] = r["correct"] == "True"
        r["wrong_accusation"] = r["wrong_accusation"] == "True"
        r["abstained"] = r["abstained"] == "True"
        r["argmax_correct"] = r["argmax_correct"] == "True"
        r["angle_deg"] = int(r["angle_deg"])
    percand = []
    if os.path.exists(PERCAND):
        with open(PERCAND, encoding="utf-8") as f:
            percand = [json.loads(line) for line in f if line.strip()]

    n_var = st["n_variants"]
    mrows = [r for r in rows if r["marked"]]
    crows = [r for r in rows if not r["marked"]]

    # -- per-photo grid ----------------------------------------------------------
    def cell_rows(a, ch):
        return [r for r in mrows if r["angle_deg"] == a and r["chain"] == ch]

    def grid_table(metric):
        head = "| angle \\ chain | " + " | ".join(CHAIN_ORDER) + " |"
        sep = "|---" * (len(CHAIN_ORDER) + 1) + "|"
        lines = [head, sep]
        for a in ANGLES:
            cells = []
            for ch in CHAIN_ORDER:
                rs = cell_rows(a, ch)
                cells.append(metric(rs))
            lines.append(f"| {a} deg | " + " | ".join(cells) + " |")
        return "\n".join(lines)

    def m_ident(rs):
        return _pct(sum(r["correct"] for r in rs), len(rs)) \
            + f" ({sum(r['correct'] for r in rs)}/{len(rs)})" if rs else "-"

    def m_argmax(rs):
        sc = [r for r in rs if r["argmax_doc"]]
        return (_pct(sum(r["argmax_correct"] for r in sc), len(sc))
                + f" ({sum(r['argmax_correct'] for r in sc)}/{len(sc)}"
                + (f", {len(rs) - len(sc)} unscored" if len(sc) < len(rs)
                   else "") + ")") if rs else "-"

    def m_abst(rs):
        return _pct(sum(r["abstained"] for r in rs), len(rs)) if rs else "-"

    def m_trueacc(rs):
        accs = [float(r["true_acc"]) for r in rs if r["true_acc"]]
        return f"{np.mean(accs):.2f}" if accs else "-"

    # -- aggregated per contributor ---------------------------------------------
    pooled = {}
    for pc in percand:
        if not pc["marked"]:
            continue
        d = pooled.setdefault(pc["doc_id"],
                              {"angle": pc["angle_deg"],
                               "chain": pc["chain"], "cands": {}})
        for cid, (ok, tot) in pc["cands"].items():
            e = d["cands"].setdefault(cid, [0, 0])
            e[0] += ok
            e[1] += tot
    agg = []
    for doc_id, d in sorted(pooled.items(),
                            key=lambda kv: int(kv[0][1:])):
        ranked = sorted(
            ((cid, ok, tot, (ok / tot if tot else 0.0))
             for cid, (ok, tot) in d["cands"].items()),
            key=lambda x: (x[3], x[2]), reverse=True)
        if not ranked:
            agg.append({"doc_id": doc_id, "angle": d["angle"],
                        "chain": d["chain"], "best": "", "frac": None,
                        "tot": 0, "p_adj": None, "attributed": False,
                        "correct": False, "wrong": False, "margin": None,
                        "argmax_correct": False})
            continue
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        p = _binom_p(best[1], best[2])
        p_adj = min(1.0, p * n_var) if p is not None else None
        attributed = (p_adj is not None and p_adj <= P_THRESHOLD
                      and best[2] >= MIN_BITS)
        agg.append({
            "doc_id": doc_id, "angle": d["angle"], "chain": d["chain"],
            "best": best[0], "frac": best[3], "tot": best[2],
            "p_adj": p_adj, "attributed": attributed,
            "correct": attributed and best[0] == doc_id,
            "wrong": attributed and best[0] != doc_id,
            "argmax_correct": best[0] == doc_id,
            "margin": round(best[3] - second[3], 3) if second else None})

    def agg_cell(a, ch):
        rs = [g for g in agg if g["angle"] == a and g["chain"] == ch]
        if not rs:
            return "-"
        idn = sum(g["correct"] for g in rs)
        am = sum(g["argmax_correct"] for g in rs)
        return f"attr {idn}/{len(rs)} · argmax {am}/{len(rs)}"

    # Aggregated controls (pool every control capture's candidates)
    cagg = {}
    for pc in percand:
        if pc["marked"]:
            continue
        d = cagg.setdefault(pc["doc_id"], {})
        for cid, (ok, tot) in pc["cands"].items():
            e = d.setdefault(cid, [0, 0])
            e[0] += ok
            e[1] += tot
    control_agg_accused = []
    for doc_id, cands in cagg.items():
        for cid, (ok, tot) in cands.items():
            p = _binom_p(ok, tot)
            if p is not None and min(1.0, p * n_var) <= P_THRESHOLD \
                    and tot >= MIN_BITS:
                control_agg_accused.append((doc_id, cid, ok, tot))

    # -- headline safety numbers -------------------------------------------------
    photo_wrong = [r for r in rows if r["wrong_accusation"]]
    agg_wrong = [g for g in agg if g["wrong"]]
    control_photo_accused = [r for r in crows if not r["abstained"]]

    # -- capacity / collision commentary (MEASURED capacity) ---------------------
    cap = st.get("capacity") or {}
    cap_lines = []
    per_page_bits = {p["page_index"]: (p.get("line_bits") or 0,
                                       p.get("word_bits") or 0)
                     for p in cap.get("per_page", [])}
    tot_line = sum(l for l, w in per_page_bits.values())
    tot_word = sum(w for l, w in per_page_bits.values())
    # A photo shows ONE page; observable evidence = that page's line bits
    # plus (text mode only) its word bits -- both carriers are pooled by
    # the scan's binomial rule.
    max_page_bits = max((l + w for l, w in per_page_bits.values()),
                        default=0)
    cap_lines.append(
        f"Measured markable capacity of this document (engine analysis, "
        f"not the ~15 line bits/page assumption): **{tot_line} line bits"
        + (f" + {tot_word} word bits" if tot_word else "")
        + " total**, per page: "
        + ", ".join(f"page {k + 1}: {l} line"
                    + (f" + {w} word" if w else "") + " bits"
                    for k, (l, w) in sorted(per_page_bits.items())) + ".")
    if st["mode"] == "pdf":
        cap_lines.append(
            f"(pdf_preserved carries line-shift only; applied slots in v1: "
            f"{cap.get('applied_bits_v1')}. Word-shift does not exist in "
            f"this carrier.)")
    B = max_page_bits
    if B > 0:
        # smallest k passing the app's accusation rule at this capacity
        t_min = next((k for k in range(B + 1)
                      if (_binom_p(k, B) or 1) * n_var <= P_THRESHOLD),
                     None)
        if B < MIN_BITS:
            cap_lines.append(
                f"**A single photo can never be attributed with this "
                f"document**: the best page exposes B={B} bits, below the "
                f"MIN_BITS={MIN_BITS} evidence floor -- the app's rule "
                f"abstains by construction, for the true variant too.")
        elif t_min is None:
            cap_lines.append(
                f"With B={B} bits and {n_var} variants, even a perfect "
                f"B/B read cannot pass the Bonferroni-corrected "
                f"p <= {P_THRESHOLD} rule; single-photo attribution is "
                f"impossible.")
        else:
            p_tail = _binom_p(t_min, B)
            risk = n_var * p_tail
            cap_lines.append(
                f"Accusation threshold at B={B} bits, {n_var} variants: "
                f">= {t_min}/{B} correct. Innocent-collision bound: "
                f"{n_var} x P(Binom({B},0.5) >= {t_min}) = {risk:.2e} "
                f"per photo.")
        if _binom_p(B, B) is not None and B >= MIN_BITS:
            pbb = _binom_p(B, B)
            max_safe = int(P_THRESHOLD / pbb) if pbb > 0 else 10 ** 7
            cap_lines.append(
                f"Max variants for which a perfect single-photo read can "
                f"still attribute at p <= {P_THRESHOLD}: "
                + (f"~{max_safe}." if max_safe <= 10 ** 6
                   else "effectively unlimited (> 10^6)."))
        else:
            need = next(k for k in range(1, 100)
                        if _binom_p(k * B, k * B) is not None
                        and _binom_p(k * B, k * B) * n_var <= P_THRESHOLD
                        and k * B >= MIN_BITS)
            cap_lines.append(
                f"Pooling helps: ~{need} clean photos of the "
                f"{max_page_bits}-bit page pooled (all bits agreeing) "
                f"would clear both the MIN_BITS floor and the "
                f"{n_var}-way-corrected threshold.")

    sc = st.get("layout_selfcheck") or []
    if sc:
        cap_lines.append("")
        cap_lines.append("Layout self-check on the PRISTINE v1 render "
                         "(clean segmentation vs meta line count): "
                         + "; ".join(
                             f"page {s['page'] + 1}: "
                             f"{s['clean_segmented']} vs "
                             f"{s['meta_lines']} -> "
                             f"{'ok' if s['clean_match'] else 'MISMATCH'}"
                             for s in sc) + ".")
        mism = [s for s in sc if not s["clean_match"]]
        if mism and len(mism) < len(sc) \
                and all(s["page"] == sc[-1]["page"] for s in mism):
            cap_lines.append(
                "Only the short LAST page mismatches: its trailing "
                "partial-triplet filler line can be dropped by the "
                "row-profile segmenter, so that page's photos may fail "
                "the line-count match. Cost is abstain-only (the photo "
                "matches no page and is never scored); it cannot cause a "
                "wrong accusation, and aggregation over the other pages "
                "is unaffected.")
        if not any(s["clean_match"] for s in sc):
            cap_lines.append(
                "Even the undegraded render fails the engine's line-count "
                "match for every page of this document (the PDF layout "
                "reports more text lines than there are separable ink "
                "rows), so photos can only ever score via the guided fit "
                "-- high 'no page match' rates here are a property of the "
                "document, not of the camera model.")

    # -- breaking-point narrative ------------------------------------------------
    narrative = []
    for a in ANGLES:
        rs = [r for r in mrows if r["angle_deg"] == a]
        sc = [r for r in rs if r["argmax_doc"]]
        am = sum(r["argmax_correct"] for r in sc)
        ab = sum(r["abstained"] for r in rs)
        if rs:
            narrative.append(
                f"- {a} deg: argmax picks the true variant in "
                f"{am}/{len(sc)} scored photos"
                + (f" ({len(rs) - len(sc)} photos never matched a page "
                   f"layout)" if len(sc) < len(rs) else "")
                + f"; {_pct(ab, len(rs))} of photos end in abstention.")
    hard = [r for r in mrows if r["chain"] in ("harsh", "brutal")]
    hsc = [r for r in hard if r["argmax_doc"]]
    if hard:
        narrative.append(
            f"- harsh/brutal chains: argmax correct in "
            f"{sum(r['argmax_correct'] for r in hsc)}/{len(hsc)} scored "
            f"photos.")

    # -- summary.md --------------------------------------------------------------
    ident = sum(r["correct"] for r in mrows)
    sc_all = [r for r in mrows if r["argmax_doc"]]
    lines = [
        "# sim300 stress-test summary",
        "",
        f"- corpus: `{st['test_id']}` -- {st['n_variants']} marked variants"
        f" + {st['n_controls']} unmarked controls, "
        f"{st['n_pages']} pages, document: {st['document']} "
        f"({st['mode']} mode)",
        f"- scoring: engine.{'scan_pdf' if st['mode'] == 'pdf' else 'scan'}"
        f".attribute (the app upload route's exact code path); rule: "
        f"p x {n_var} <= {P_THRESHOLD} and >= {MIN_BITS} observed bits",
        f"- captures: {len(mrows)} variant photos + {len(crows)} control "
        f"photos; grid: angles {ANGLES} x chains {CHAIN_ORDER} "
        f"(deterministic per variant index)",
        "",
        "## Headline safety numbers",
        "",
        f"- **Wrong accusations (per-photo): {len(photo_wrong)}** "
        f"(attributed to a doc other than the true one)",
        f"- **Wrong accusations (per-contributor aggregated): "
        f"{len(agg_wrong)}**",
        f"- **Control photos attributed to any variant: "
        f"{len(control_photo_accused)}** (must be 0)"
        + ("" if not control_photo_accused else " -- "
           + ", ".join(f"{r['capture_id']} -> {r['attributed_doc']}"
                       for r in control_photo_accused)),
        f"- Controls aggregated: "
        f"{len(control_agg_accused)} false accusations"
        + ("" if not control_agg_accused else " -- "
           + ", ".join(f"{d} -> {c} ({ok}/{tot})"
                       for d, c, ok, tot in control_agg_accused)),
        "",
        "## Measured capacity and collision risk",
        "",
        *cap_lines,
        "",
        "## Per-photo identification (attributed AND correct)",
        "",
        f"Overall: {_pct(ident, len(mrows))} ({ident}/{len(mrows)})",
        "",
        grid_table(m_ident),
        "",
        "## Per-photo argmax accuracy (true variant tops the score "
        "table; evidence threshold ignored -- signal diagnostic)",
        "",
        f"Overall: "
        f"{_pct(sum(r['argmax_correct'] for r in sc_all), len(sc_all))} "
        f"({sum(r['argmax_correct'] for r in sc_all)}/{len(sc_all)} scored"
        f" photos; {len(mrows) - len(sc_all)} photos matched no page)",
        "",
        grid_table(m_argmax),
        "",
        "## Per-photo abstention rate",
        "",
        grid_table(m_abst),
        "",
        "## Mean agreement of the TRUE variant (scored photos)",
        "",
        grid_table(m_trueacc),
        "",
        "## Per-contributor aggregated attribution",
        "",
        "Pooled bit agreements across all of a contributor's page photos "
        "(sum ok / sum tot per candidate), argmax with pooled "
        "Bonferroni-corrected binomial rule:",
        "",
        f"- aggregated attributed-and-correct: "
        f"{sum(g['correct'] for g in agg)}/{len(agg)}",
        f"- aggregated argmax-correct: "
        f"{sum(g['argmax_correct'] for g in agg)}/{len(agg)}",
        f"- aggregated wrong: {len(agg_wrong)}",
        "",
        "| angle \\ chain | " + " | ".join(CHAIN_ORDER) + " |",
        "|---" * (len(CHAIN_ORDER) + 1) + "|",
    ]
    for a in ANGLES:
        lines.append(f"| {a} deg | "
                     + " | ".join(agg_cell(a, ch)
                                  for ch in CHAIN_ORDER) + " |")
    lines += [
        "",
        "## Control results",
        "",
        f"{len(crows)} control photos (unmarked prints, wa chain, angles "
        f"{CONTROL_ANGLES}): "
        + ("**no attribution on any control photo -- 0 false "
           "accusations.**" if not control_photo_accused
           else "**FALSE ACCUSATIONS -- see headline section.**"),
        "",
        "## Erasure / abstention overview",
        "",
        f"- photos that matched no page layout at all: "
        f"{len(mrows) - len(sc_all)}/{len(mrows)} variant photos",
        f"- abstentions (no attribution) on variant photos: "
        f"{sum(r['abstained'] for r in mrows)}/{len(mrows)}",
        f"- scan errors: {sum(1 for r in rows if r['error'])}",
        "",
        "## Breaking point",
        "",
        *narrative,
        "",
        "## Timings",
        "",
        "```json",
        json.dumps(st.get("timings", {}), indent=1),
        "```",
        "",
        "Per-capture inspection (image + exact treatment + outcome): "
        "open `report.html` next to this file.",
    ]
    with open(os.path.join(OUT, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[report] wrote {os.path.join(OUT, 'summary.md')}")

    write_html(rows, st)
    print(f"[report] wrote {os.path.join(OUT, 'report.html')}")


def _outcome(r):
    if not r["marked"]:
        return ("FALSE ACCUSATION", "bad") if not r["abstained"] \
            else ("control clean", "ok")
    if r["correct"]:
        return "identified", "ok"
    if r["wrong_accusation"]:
        return "WRONG VARIANT", "bad"
    if not r["argmax_doc"]:
        return "no page match", "gray"
    if r["argmax_correct"]:
        return "abstain (argmax correct)", "mid"
    return "abstain (argmax wrong)", "gray"


def write_html(rows, st):
    cells = sorted({f"{r['angle_deg']}deg/{r['chain']}" for r in rows},
                   key=lambda s: (int(s.split("deg")[0]),
                                  s.split("/")[1]))
    trs = []
    for r in sorted(rows, key=lambda r: (not r["marked"],
                                         int(r["doc_id"][1:])
                                         if r["doc_id"][1:].isdigit()
                                         else 999,
                                         r["capture_id"])):
        label, cls = _outcome(r)
        cell = f"{r['angle_deg']}deg/{r['chain']}"
        treat = (f"tilt {r['angle_deg']} deg, jitter {r['jitter_deg']} deg, "
                 f"blur σ{r['blur_sigma']}, noise σ{r['noise_sigma']}/255, "
                 f"chain {r['chain_steps']}")
        diag = f"path={r['path_used'] or '-'}"
        if r["page_matched"] != "":
            diag += f", page {int(r['page_matched']) + 1} matched"
        trs.append(
            f'<tr data-cell="{cell}" data-outcome="{cls}" '
            f'data-doc="{r["doc_id"]}">'
            f'<td><a href="{r["capture_path"]}" target="_blank">'
            f'<img loading="lazy" src="{r["capture_path"]}"></a></td>'
            f'<td class="mono">{r["capture_id"]}<br>'
            f'<span class="dim">{diag}</span></td>'
            f'<td>{treat}</td>'
            f'<td class="mono">{r["doc_id"]}'
            f'{"" if r["marked"] else " (control)"}</td>'
            f'<td class="mono">{r["attributed_doc"] or "—"}'
            + (f'<br><span class="dim">argmax {r["argmax_doc"]}</span>'
               if r["argmax_doc"] else "")
            + f'</td><td><span class="badge {cls}">{label}</span></td>'
            f'<td class="mono">acc {r["acc"] or "—"} / true '
            f'{r["true_acc"] or "—"}<br><span class="dim">n={r["n_obs"] or 0}'
            f', margin {r["margin"] or "—"}</span></td></tr>')
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>sim300 capture inspector</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;margin:18px;background:#fafafa;
color:#222}}
h1{{font-size:20px}} .dim{{color:#777;font-size:12px}}
.mono{{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}}
table{{border-collapse:collapse;width:100%;background:#fff}}
td,th{{border:1px solid #ddd;padding:6px 8px;vertical-align:top;
text-align:left}}
img{{width:140px;height:auto;border:1px solid #ccc;background:#fff}}
.badge{{padding:2px 8px;border-radius:10px;font-size:12px;white-space:nowrap}}
.badge.ok{{background:#d7f2d7;color:#145014}}
.badge.mid{{background:#fff3cd;color:#6b5200}}
.badge.gray{{background:#e8e8e8;color:#555}}
.badge.bad{{background:#f8d7da;color:#7a1220;font-weight:700}}
select,input{{margin-right:12px;padding:3px}}
</style></head><body>
<h1>sim300 capture inspector — {st['test_id']}</h1>
<p class="dim">{st['n_variants']} variants + {st['n_controls']} controls,
{st['n_pages']} pages, {st['document']} ({st['mode']} mode). Each row is one
degraded photo: the exact treatment it received and how the app's scan
attributed it.</p>
<p>
Cell: <select id="fcell"><option value="">all</option>
{''.join(f'<option>{c}</option>' for c in cells)}</select>
Outcome: <select id="fout"><option value="">all</option>
<option value="ok">identified / control clean</option>
<option value="mid">abstain (argmax correct)</option>
<option value="gray">abstain / no page match</option>
<option value="bad">wrong accusation</option></select>
Doc: <input id="fdoc" placeholder="e.g. v12" size="8">
<span id="count" class="dim"></span>
</p>
<table><thead><tr><th>capture</th><th>id / decode path</th>
<th>treatment</th><th>true doc</th><th>attributed</th><th>outcome</th>
<th>scores</th></tr></thead><tbody>
{''.join(trs)}
</tbody></table>
<script>
const rows=[...document.querySelectorAll('tbody tr')];
function apply(){{
 const c=document.getElementById('fcell').value,
       o=document.getElementById('fout').value,
       d=document.getElementById('fdoc').value.trim();
 let n=0;
 rows.forEach(r=>{{
  const show=(!c||r.dataset.cell===c)&&(!o||r.dataset.outcome===o)
   &&(!d||r.dataset.doc===d);
  r.style.display=show?'':'none'; if(show)n++;
 }});
 document.getElementById('count').textContent=n+' / '+rows.length+' captures';
}}
['fcell','fout'].forEach(id=>document.getElementById(id)
 .addEventListener('change',apply));
document.getElementById('fdoc').addEventListener('input',apply);
apply();
</script></body></html>
"""
    with open(os.path.join(OUT, "report.html"), "w", encoding="utf-8") as f:
        f.write(html)


# ---- main ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--n", type=int, default=300,
                    help="number of marked variants (default 300)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only process the first K variants (smoke tests); "
                         "at build time caps the corpus size too")
    ap.add_argument("--pdf", default=DEFAULT_PDF,
                    help="source PDF for the pdf_preserved corpus "
                         "(default: the resume in docs/)")
    ap.add_argument("--text", action="store_true",
                    help="use the rendered text-mode corpus "
                         "(SAMPLE_TEXT extended to 4+ pages) instead of "
                         "the PDF path")
    ap.add_argument("--text-file", default=None,
                    help="rendered text-mode corpus built from this file's "
                         "content instead of SAMPLE_TEXT (corpus name derived "
                         "from the filename); implies text mode")
    ap.add_argument("--workers", type=int, default=None,
                    help="scoring processes (default max(2, cpu-4))")
    ap.add_argument("--keep-work", action="store_true",
                    help="keep per-capture scan work dirs (crops)")
    args = ap.parse_args()

    phases = [p for p in ("build", "simulate", "score", "report")
              if getattr(args, p)]
    if not phases:
        phases = ["build", "simulate", "score", "report"]
    t0 = time.perf_counter()
    for p in phases:
        {"build": build_phase, "simulate": simulate_phase,
         "score": score_phase, "report": report_phase}[p](args)
    print(f"[done] phases {phases} in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
