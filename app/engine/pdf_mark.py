# SPDX-License-Identifier: Apache-2.0
"""Stage 2 M1: formatting-preserving line-shift embedding for foreign PDFs.

Layout analysis (PyMuPDF) selects "markable bands": runs of >= 3 consecutive
uniform-pitch body-text lines. Embedding (pikepdf) edits the page content
stream, translating each marked line's baseline by +/- LINE_SHIFT_PT
(0.48 pt = the 2 px at 300 dpi validated physically), with compensation on
the following relative positioning op so no other line moves. Everything
else in the stream is untouched, so rendering outside marked lines is
byte-stable.

Public convention unchanged: triplets (control, marked, control), bit 1 =
baseline down on paper, PRN payload bits with repetition across triplet
slots. Controls are byte-identical copies (no shifts).

Scope guards (M1): pages showing TEXT under a non-translation cm or a
rotated/sheared Tm are skipped, and lines with nonzero text rise are left
unmarked; every such decision is recorded in the meta, never silent. A
non-translation cm that only places images or vector art (q cm Do Q, no
text inside) does not disqualify the page, so pages carrying pictures,
drawings and tables still fingerprint through their body text.
"""
import io

import fitz
import pikepdf

from . import REPO  # noqa: F401
import encode

LINE_SHIFT_PT = 2.0 / 300.0 * 72.0        # 0.48 pt, matches encode.LINE_SHIFT
PAYLOAD_BITS = 64
MIN_BAND = 3
PITCH_MIN, PITCH_MAX = 5.0, 40.0
# Measured floor (M2, 2026-07-13): at 10.08 pt pitch (9 pt / 1.12 leading)
# line segmentation loses lines already at the WhatsApp preset; at 14.17 pt
# everything passes. Bands below this pitch are not marked (recorded as
# excluded); refine against physical captures at M3.
MIN_PITCH_MARK = 12.0
PITCH_TOL = 0.06                          # relative pitch uniformity in a band
MATCH_TOL = 0.35                          # pt, stream-y to layout-y matching
COMPLEX_SPAN_TOL = 0.6                    # pt, span-baseline spread within a line

Y_CHANGERS = {"Tm", "Td", "TD", "T*", "'", '"'}
SHOW_OPS = {"Tj", "TJ", "'", '"'}


# ---- layout analysis -----------------------------------------------------------
def analyze(doc):
    """Per page: candidate text lines (pdf-space baseline y) and markable
    bands (runs of uniform-pitch simple lines)."""
    pages = []
    for pno in range(doc.page_count):
        page = doc[pno]
        inv = ~page.transformation_matrix          # fitz -> pdf space
        lines = []
        d = page.get_text("dict")
        for block in d["blocks"]:
            if block.get("type") != 0:
                continue
            for ln in block["lines"]:
                spans = ln.get("spans") or []
                if not spans:
                    continue
                ys = [s["origin"][1] for s in spans]
                x0 = min(s["bbox"][0] for s in spans)
                x1 = max(s["bbox"][2] for s in spans)
                y_fitz = ys[0]
                p = fitz.Point(x0, y_fitz) * inv
                lines.append({
                    "y_pdf": round(p.y, 3), "x0": round(x0, 1),
                    "x1": round(x1, 1),
                    "text_head": "".join(s["text"] for s in spans)[:40],
                    "complex": (max(ys) - min(ys)) > COMPLEX_SPAN_TOL,
                    "size": max(s["size"] for s in spans),
                })
        lines.sort(key=lambda l: -l["y_pdf"])      # top of page first
        lines = _merge_same_baseline(lines)
        bands, excluded = _bands(lines)
        pages.append({"page_index": pno,
                      "height_pt": page.rect.height,
                      "lines": lines, "bands": bands,
                      "excluded_bands": [{"pitch_pt": e["pitch_pt"],
                                          "n_lines": len(e["line_idx"]),
                                          "reason": e["reason"]}
                                         for e in excluded]})
    return pages


def _merge_same_baseline(lines):
    """Merge extraction lines sharing one baseline (table columns, side-by-
    side blocks) into a single visual line: the decoder segments ink ROWS,
    so per-column lines would inflate n_lines_total past anything a
    segmenter can match, and zero-pitch duplicates would break banding.
    A merged line is flagged complex: multi-segment baselines are table /
    multi-column zones, which stay preserved but never marked (rules and
    neighbor columns corrupt the baseline read there). `lines` must
    already be sorted top of page first."""
    merged = []
    for l in lines:
        if merged and abs(merged[-1]["y_pdf"] - l["y_pdf"]) <= MATCH_TOL:
            m = merged[-1]
            m["x0"] = min(m["x0"], l["x0"])
            m["x1"] = max(m["x1"], l["x1"])
            m["text_head"] = (m["text_head"] + " " + l["text_head"])[:40]
            m["complex"] = True
            m["size"] = max(m["size"], l["size"])
        else:
            merged.append(dict(l))
    return merged


def _bands(lines):
    """Runs of >= MIN_BAND consecutive simple lines with uniform pitch.
    Returns (bands, excluded): sub-pitch-floor runs land in excluded with a
    reason, so callers can surface why a page carries fewer bits."""
    bands, excluded, run = [], [], []

    def flush():
        if len(run) >= MIN_BAND:
            pitches = [run[i]["y_pdf"] - run[i + 1]["y_pdf"]
                       for i in range(len(run) - 1)]
            med = sorted(pitches)[len(pitches) // 2]
            rec = {"line_idx": [l["_i"] for l in run],
                   "pitch_pt": round(med, 3)}
            if med < MIN_PITCH_MARK:
                rec["reason"] = "below_pitch_floor"
                excluded.append(rec)
            else:
                bands.append(rec)
        run.clear()

    for i, l in enumerate(lines):
        l["_i"] = i
        if l["complex"]:
            flush()
            continue
        if run:
            pitch = run[-1]["y_pdf"] - l["y_pdf"]
            ref = run[-2]["y_pdf"] - run[-1]["y_pdf"] if len(run) > 1 else pitch
            if not (PITCH_MIN <= pitch <= PITCH_MAX) or \
               abs(pitch - ref) > PITCH_TOL * ref:
                # The run breaks here — but if it was too short to become a
                # band, its tail line may really belong to the run STARTING
                # at l (e.g. a title whose gap to the first body line
                # happens to pass the pitch test steals that line; losing
                # it would leave the band an interior subset of a longer
                # uniform paragraph, which the capture-side comb fit can
                # then misregister by one pitch). Re-seed with the tail if
                # it is pitch-compatible with l.
                tail = run[-1] if len(run) < MIN_BAND else None
                flush()
                if tail is not None and \
                        PITCH_MIN <= tail["y_pdf"] - l["y_pdf"] <= PITCH_MAX:
                    run.append(tail)
        run.append(l)
    flush()
    for l in lines:
        l.pop("_i", None)
    return bands, excluded


# ---- content-stream editing ----------------------------------------------------
class _TextWalk:
    """Minimal text-state simulation over a parsed content stream, tracking
    the current line-origin y in (translation-only) device space."""

    def __init__(self, ops):
        self.ops = ops
        self.records = []          # per show op: (op_idx, y, est_idx, ts, ok)
        self.page_ok = True
        self._walk()

    def _walk(self):
        y = None
        tl = 0.0
        ts = 0.0
        ctm_ty = 0.0
        ctm_complex = False        # scaled/rotated space in effect
        stack = []
        est = None                 # index of op that established current y
        est_tl = 0.0
        for i, inst in enumerate(self.ops):
            operands, op = inst.operands, str(inst.operator)
            if op == "q":
                stack.append((ctm_ty, ctm_complex))
            elif op == "Q":
                ctm_ty, ctm_complex = stack.pop() if stack else (0.0, False)
            elif op == "cm":
                a, b, c, d2, _e, f = [float(x) for x in operands]
                if (a, b, c, d2) == (1.0, 0.0, 0.0, 1.0):
                    ctm_ty += f
                else:
                    # Scaled/rotated space is harmless while it only places
                    # images or vector art (q cm Do Q). Only text SHOWN under
                    # it is un-analyzable, and that still bails the page.
                    ctm_complex = True
            elif op == "BT":
                y, est = None, None
            elif op == "Tm":
                a, b, c, d2, _e, f = [float(x) for x in operands]
                if b != 0.0 or c != 0.0:
                    self.page_ok = False
                    return
                y = float(f) + ctm_ty
                est, est_tl = i, tl
            elif op in ("Td", "TD"):
                ty = float(operands[1])
                if op == "TD":
                    tl = -ty
                y = (y if y is not None else ctm_ty) + ty
                est, est_tl = i, tl
            elif op == "TL":
                tl = float(operands[0])
            elif op == "T*":
                y = (y if y is not None else ctm_ty) - tl
                est, est_tl = i, tl
            elif op == "Ts":
                ts = float(operands[0])
            elif op in ("'", '"'):
                if ctm_complex:
                    self.page_ok = False       # text in scaled space: bail
                    return
                y = (y if y is not None else ctm_ty) - tl
                est, est_tl = i, tl
                self.records.append((i, y, est, ts, True))
            elif op in ("Tj", "TJ"):
                if ctm_complex:
                    self.page_ok = False       # text in scaled space: bail
                    return
                if y is not None:
                    self.records.append((i, y, est, ts, True))


def _num(x):
    v = round(float(x), 4)
    return int(v) if v == int(v) else v


def _mk(operands, op):
    return pikepdf.ContentStreamInstruction(operands, pikepdf.Operator(op))


EDITABLE_EST = {"Tm", "Td", "TD", "T*", "'"}
EDITABLE_COMP = {"Tm", "Td", "TD", "T*", "'"}     # Tm needs no edit; '"' never ok


def plan_and_apply(pdf, page, targets):
    """targets: list of dicts {y (pdf/device space), delta (pt, +up)}.
    Returns {y: applied_bool}. Edits the page content stream in place.

    A target is applied only if EVERY text segment on that line has an
    editable establishing op AND every needed compensation site is editable
    and collision-free; otherwise the whole line is left unmarked (recorded
    by the caller), never partially shifted."""
    ops = list(pikepdf.parse_content_stream(page))
    walk = _TextWalk(ops)
    applied = {t["y"]: False for t in targets}
    if not walk.page_ok or not targets:
        return applied

    # All establishing ops per target (a visual line may be drawn by several
    # text segments, each with its own positioning op).
    ests = {id(t): set() for t in targets}
    by_id = {id(t): t for t in targets}
    for _op_idx, y, est, ts, _ok in walk.records:
        if est is None or ts != 0.0:
            continue
        for t in targets:
            if abs(y - t["y"]) <= MATCH_TOL:
                ests[id(t)].add(est)

    # TL in effect at each op index.
    tl_at, tl = {}, 0.0
    for i, inst in enumerate(ops):
        op = str(inst.operator)
        if op == "TL":
            tl = float(inst.operands[0])
        elif op == "TD":
            tl = -float(inst.operands[1])
        tl_at[i] = tl

    def comp_site(est_idx):
        """Next y-changing op after est (None if absolute/none needed)."""
        for j in range(est_idx + 1, len(ops)):
            o = str(ops[j].operator)
            if o == "BT":
                return None
            if o in Y_CHANGERS:
                return None if o == "Tm" else j
        return None

    # Validate targets, collect edits.
    est_edits, comp_edits = {}, {}                # op_idx -> delta
    for tid, est_set in ests.items():
        t = by_id[tid]
        if not est_set:
            continue
        plan_e, plan_c = {}, {}
        valid = True
        for e in est_set:
            if str(ops[e].operator) not in EDITABLE_EST:
                valid = False
                break
            c = comp_site(e)
            if c is not None:
                if str(ops[c].operator) not in EDITABLE_COMP:
                    valid = False
                    break
                plan_c[c] = t["delta"]
            plan_e[e] = t["delta"]
        if not valid:
            continue
        keys = set(plan_e) | set(plan_c)
        if keys & (set(est_edits) | set(comp_edits)) or set(plan_e) & set(plan_c):
            continue                              # collision: skip this line
        est_edits.update(plan_e)
        comp_edits.update(plan_c)
        applied[t["y"]] = True

    if not est_edits:
        return {k: False for k in applied}

    out = []
    for i, inst in enumerate(ops):
        op = str(inst.operator)
        operands = list(inst.operands)
        if i in est_edits or i in comp_edits:
            # est: move this line by +d. comp: absorb -d so next line stays.
            d = est_edits.get(i, 0.0) - comp_edits.get(i, 0.0)
            if op == "Tm":
                operands[5] = _num(float(operands[5]) + d)
                out.append(_mk(operands, "Tm"))
            elif op == "Td":
                operands[1] = _num(float(operands[1]) + d)
                out.append(_mk(operands, "Td"))
            elif op == "TD":
                # TD also sets leading; preserve TL, then shifted Td.
                out.append(_mk([_num(-float(operands[1]))], "TL"))
                out.append(_mk([operands[0],
                                _num(float(operands[1]) + d)], "Td"))
            elif op == "T*":
                out.append(_mk([0, _num(-tl_at[i] + d)], "Td"))
            elif op == "'":
                out.append(_mk([0, _num(-tl_at[i] + d)], "Td"))
                out.append(_mk([operands[0]], "Tj"))
            else:                                  # unreachable by validation
                out.append(inst)
        else:
            out.append(inst)

    page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))
    return applied


def capacity(src_bytes):
    """Nominal marking capacity of a PDF (for the wizard preview): line bits
    per page from band analysis. Actual applied slots can be slightly lower
    (stream-edit skips) and are recorded at generation."""
    doc = fitz.open(stream=src_bytes, filetype="pdf")
    pages = analyze(doc)
    doc.close()
    per_page, total = [], 0
    for pg in pages:
        bits = sum((len(b["line_idx"]) - len(b["line_idx"]) % 3) // 3
                   for b in pg["bands"])
        per_page.append({"page_index": pg["page_index"],
                         "n_lines": len(pg["lines"]), "line_bits": bits,
                         "excluded_bands": pg["excluded_bands"]})
        total += bits
    return {"pages": len(pages), "per_page": per_page, "total_bits": total,
            "min_pitch_pt": MIN_PITCH_MARK}


# ---- top-level embed -----------------------------------------------------------
def embed(src_bytes, seed, unmarked=False):
    """Return (variant_pdf_bytes, meta_v2). Controls are byte copies."""
    doc = fitz.open(stream=src_bytes, filetype="pdf")
    pages = analyze(doc)
    doc.close()

    payload = encode.prn_bits(seed, PAYLOAD_BITS)
    meta = {"version": 2, "kind": "pdf_lineshift", "seed": seed,
            "unmarked": bool(unmarked), "payload": payload,
            "line_shift_pt": LINE_SHIFT_PT, "n_pages": len(pages),
            "pages": []}

    slot = 0
    plans = []                       # per page: list of target dicts
    for pg in pages:
        page_targets = []
        mpage = {"page_index": pg["page_index"], "height_pt": pg["height_pt"],
                 "n_lines_total": len(pg["lines"]),
                 "line_ys_px300": [round((pg["height_pt"] - l["y_pdf"])
                                         / 72.0 * 300.0, 2)
                                   for l in pg["lines"]],
                 "excluded_bands": pg["excluded_bands"], "bands": []}
        for band in pg["bands"]:
            idxs = band["line_idx"]
            n_whole = len(idxs) - (len(idxs) % 3)
            mband = {"pitch_pt": band["pitch_pt"], "start_line": idxs[0],
                     "lines": []}
            for j, li in enumerate(idxs):
                l = pg["lines"][li]
                rec = {"y_pdf": l["y_pdf"],
                       "y_px300": round((pg["height_pt"] - l["y_pdf"])
                                        / 72.0 * 300.0, 2),
                       "text_head": l["text_head"],
                       "role": "control", "bit": None, "delta_pt": 0.0,
                       "applied": False}
                if j < n_whole and j % 3 == 1:
                    bit = payload[slot % PAYLOAD_BITS]
                    slot += 1
                    rec.update({"role": "marked", "bit": bit})
                    if not unmarked:
                        # bit 1 = down on paper = pdf y decrease
                        delta = -LINE_SHIFT_PT if bit == 1 else LINE_SHIFT_PT
                        rec["delta_pt"] = delta
                        page_targets.append({"y": l["y_pdf"], "delta": delta,
                                             "_rec": rec})
                mband["lines"].append(rec)
            mpage["bands"].append(mband)
        meta["pages"].append(mpage)
        plans.append(page_targets)
    meta["n_slots"] = slot

    if unmarked or slot == 0:
        return src_bytes, meta

    pdf = pikepdf.open(io.BytesIO(src_bytes))
    for pno, page_targets in enumerate(plans):
        if not page_targets:
            continue
        applied = plan_and_apply(pdf, pdf.pages[pno], page_targets)
        for t in page_targets:
            ok = applied.get(t["y"], False)
            t["_rec"]["applied"] = bool(ok)
            if not ok:
                t["_rec"]["delta_pt"] = 0.0        # honest: nothing moved
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    meta["n_applied"] = sum(1 for pg in meta["pages"] for b in pg["bands"]
                            for l in b["lines"] if l["applied"])
    return buf.getvalue(), meta
