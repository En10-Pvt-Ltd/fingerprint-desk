---
name: False attribution report
about: The tool attributed a control/innocent copy, or you can force it to
title: "[false-attribution] "
labels: false-attribution, priority
---

> This is the most valuable bug report this project can receive. An unmarked **control**
> copy must never be attributed. We treat a confirmed case as **release-blocking**.
>
> If this could let someone manufacture false evidence against a real person, please
> report it **privately** first via [SECURITY.md](../../SECURITY.md) instead of here.

**What was attributed**
Which copy did the tool name, and which copy was the capture actually from (control? a
different variant? a foreign document)?

**The verdict it gave**
Paste the full verdict: attributed doc, agreement, observed bits, corrected p-value, and
the margin over the runner-up.

**How to reproduce**
- Carrier / mode:
- The document or a minimal one that reproduces it:
- The capture (image) or the exact simulate preset used:
- The ground-truth metadata, if needed to score (do not include real personal data):

**Did you run the control through the same pipeline?**
What did the control read? (This is the check every operator should run.)

**Environment**
OS, Python version, how you ran it, and any custom `FF_FONT_PATH` (a serif font is bundled by default).
