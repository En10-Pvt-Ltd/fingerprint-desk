#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Write provenance.json for this pack: commands, thresholds with honest
before/after disclosure, and sha256 fingerprints of every archived input
and of the decoder code that produced the results."""
import glob
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


fingerprints = {}
for pat in ("captures/*", "foreign/*", "print/*", "metas/*", "decodes/*",
            "pixel-diff/*"):
    for p in sorted(glob.glob(os.path.join(HERE, pat))):
        fingerprints[os.path.relpath(p, HERE).replace(os.sep, "/")] = sha(p)
code = {}
for rel in ("app/engine/pdf_mark.py", "app/engine/pdf_scan.py",
            "app/m3_check.py", "app/tools/m3_kit.py",
            "field-test-002/make_decodes.py", "field-test-002/pixel_diff.py"):
    code[rel] = sha(os.path.join(REPO, rel))

prov = {
    "pack": "field-test-002",
    "what": "Physical revalidation (Stage 2 M3) of formatting-preserving "
            "PDF line-shift fingerprinting: real print, hand-held phone "
            "photo, one real WhatsApp hop.",
    "date": "2026-07-13",
    "operator": "repository owner (printing, photography, WhatsApp hop); "
                "decoding and scoring fully automated by the archived code",
    "carrier": {
        "name": "line-shift only",
        "detail": "The pdf_lineshift carrier moves selected text baselines "
                  "by +/-0.48 pt (2 px at 300 dpi). All reported marks, "
                  "including the 14/14 read, are line-shift triplet bits. "
                  "Word-shift does not exist in this carrier.",
    },
    "whatsapp_chain": {
        "operator_statement": "every capture in captures/ was sent through "
                              "one WhatsApp hop as a normal photo before "
                              "being saved",
        "topology": "PENDING OPERATOR ATTESTATION: device-to-device or "
                    "send-to-self (fill in and re-run make_provenance.py)",
        "mode": "normal photo send (compressed), not document mode, per "
                "operator statement",
    },
    "commands": [
        "python app/tools/m3_kit.py            # built print PDFs + metas (seeds v1=7001, v2=7002)",
        "# print at 100% scale, photograph hand-held, one WhatsApp hop (operator)",
        "python app/m3_check.py                # first scoring run",
        "python app/m3_check.py --identify     # name-agnostic sheet identification after mix-up suspicion",
        "# capture files renamed to true sheet identities, confirmed by operator against sheet back labels;",
        "#   foreign photo (a different document) quarantined to foreign/",
        "python app/m3_check.py                # gate run after renames: PASSED",
        "# doc01 control captured by operator, then final run:",
        "python app/m3_check.py                # final: control 4/14, 9/14 (chance); gate PASSED",
        "python field-test-002/make_decodes.py # regenerates decodes/ from this pack",
        "python field-test-002/pixel_diff.py   # regenerates pixel-diff/ evidence",
    ],
    "thresholds": {
        "attribution_p": {
            "value": 1e-3, "correction": "Bonferroni x n_variants",
            "min_bits": 10,
            "set": "BEFORE any physical capture existed (app scan rule, "
                   "2026-07-12; reused unchanged by scan_pdf and m3_check)"},
        "gate_true_variant_accuracy": {
            "value": 0.90,
            "set": "BEFORE captures (m3_check.py authored with the kit)"},
        "gate_control_band": {
            "value": [0.35, 0.65],
            "set": "BEFORE captures (m3_check.py authored with the kit)"},
        "guided_segmentation_quality": {
            "value": 0.9,
            "set": "BEFORE the foreign photo was first decoded"},
        "guided_scale_band_and_valley_contrast": {
            "value": {"scale_ratio": [0.70, 1.35], "valley_ratio_max": 0.55},
            "set": "AFTER observing that the foreign photo passed the "
                   "quality-only check. HONEST DISCLOSURE: the foreign-"
                   "document REJECTION in the final identify run rests "
                   "partly on these post-hoc validity checks. Attribution "
                   "soundness does NOT rest on them: in the run where the "
                   "foreign photo WAS segmented, it scored at chance "
                   "against every variant and produced no attribution "
                   "under the pre-set p threshold above. Segmentation "
                   "validity is a usability filter, not the accusation "
                   "gate."},
    },
    "sheet_custody": {
        "issue": "printed sheets are visually identical by design; the "
                 "operator's initial file naming was rotated for doc01 and "
                 "one photographed sheet was a different document entirely",
        "resolution": "decoder-side identification (--identify: layout "
                      "match + per-variant binomial p), then operator "
                      "confirmation against the pencil labels on sheet "
                      "backs; files renamed accordingly; the foreign photo "
                      "is preserved in foreign/",
        "renames": [
            "doc01_times11__v2__p0.jpeg  -> doc01_times11__v1__p0.jpeg",
            "doc01_times11__v2__p1.jpeg  -> doc01_times11__v1__p1.jpeg",
            "doc01_times11__ctrl__p0.jpeg -> doc01_times11__v2__p0.jpeg",
            "doc01_times11__v1__p0.jpeg  -> foreign/travelwithme_report_photo.jpeg",
        ],
    },
    "result_summary": {
        "doc01_times11": "true-variant aggregate 37/41 = 0.902; page-1 "
                         "reads 14/14 (p 6.1e-5) and 13/14 (p 9.2e-4); own "
                         "control 4/14 and 9/14 (chance)",
        "control_aggregate": "29/54 = 0.537 (chance band 0.35-0.65)",
        "doc02_helv_headings": "did NOT validate (one segmentation "
                               "near-miss, one chance-level self-read); "
                               "gate requires one passing document class",
        "verdict": "M3 GATE PASSED on doc01_times11",
    },
    "scope": "Two marked copies plus controls, one printer, one phone, one "
             "WhatsApp hop, two document classes. National-scale guarantees "
             "rest on the analytic tier table and the planned corpus "
             "campaign, not on this field test.",
    "code_fingerprints_sha256": code,
    "file_fingerprints_sha256": fingerprints,
}
json.dump(prov, open(os.path.join(HERE, "provenance.json"), "w"), indent=1)
print(f"wrote provenance.json ({len(fingerprints)} files, "
      f"{len(code)} code fingerprints)")
