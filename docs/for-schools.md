# For schools and exam offices — a no-terminal guide

You do not need to be technical to use this. If someone has set up a Fingerprint Desk
instance for you (a web address), the whole job is four screens. If not, ask your IT contact
to run the one-line Docker deployment in the main README, or use a hosted instance.

## Before you start: the one thing that matters

When you generate copies, the tool creates a **recovery key** file. That key is the only
thing that can later trace a leak. **If you lose it, nothing can ever be traced.** Save it
somewhere safe and backed up the moment you download it, exactly like an exam-paper safe
combination.

Also: always keep the **control copy** the tool makes for you. It is an untagged copy used
to sanity-check any future accusation.

## Screen 1 — Upload

Drag in a PDF, or paste the text. The tool tells you in plain language what kind of document
it is ("This is a scanned document — we'll use the image method") and how many distinct
copies it can safely carry ("up to about 500 distinct copies").

## Screen 2 — Name the copies

Two ways:

- **By count.** "How many copies?" e.g. `40`, with a naming pattern like `Centre-1 …
  Centre-40`.
- **By roster.** Paste or upload a list of names (one per line, or a CSV) — one copy per
  name. This is what a university with 300 students wants.

The tool also makes **one unmarked control copy** automatically. One line explains it: *if
the system ever accuses that copy, something is wrong.*

## Screen 3 — Download and distribute

- **Download all** as a ZIP (one PDF per name), or download any single copy from a
  searchable list.
- **Download the recovery key** and tick "I have saved this". Do not skip this.
- **Printing:** print at **100% / actual size** (not "fit to page"), on plain white paper,
  and **do not photocopy** the copies (photocopying can blur the mark). Hand each named
  person their named copy.

## Screen 4 — Investigate a leak

If a page leaks (say, someone shares a phone photo), upload that photo and select your
recovery key. You get a plain-language verdict, never a raw number:

> **Most likely source: Centre-14.** Evidence strength: strong — this reading would occur by
> chance for an unrelated copy less than once in a million times. Next most likely: Centre-9,
> far behind.

or, shown with equal weight:

> **No attribution.** The photo does not carry enough recoverable signal to name a source.
> This is normal for small crops or heavily degraded images. It does **not** mean the
> document was untagged.

**Before you act on any positive result**, run your control copy through the same check. If
the control is also attributed, do not rely on the result — stop and report it.

## What you can ignore

Anything about carriers, bits, p-values, tiers, or Bonferroni lives behind an "Advanced
details" toggle for a forensic analyst. You never need it for normal use.

## Responsible use

Where the law or basic fairness requires it, tell recipients their copies are individually
traceable. Deterrence only works when people know it exists — and disclosure is often a
legal obligation.
