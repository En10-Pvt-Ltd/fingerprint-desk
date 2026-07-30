---
name: Bug report
about: Something is broken or behaves incorrectly
title: "[bug] "
labels: bug
---

**What happened**
A clear, concise description of the bug.

**Expected behavior**
What you expected instead.

**To reproduce**
Steps, commands, and inputs. Attach a small PDF or image if relevant (do **not** attach
anything containing real personal data or a document you do not have permission to share).

**Environment**
- Carrier / mode (rendered / preserved / raster / vector), if known:
- How you ran it (docker compose / `python app/serve.py` / self-test):
- OS and Python version:
- Custom `FF_FONT_PATH`? (a serif font is bundled by default — only note this if you overrode it)

**Self-test**
Does `python app/selftest.py` pass on your machine? (paste the last line)

**Logs / output**
Paste relevant output. Redact any emails, tokens, or document contents first.
