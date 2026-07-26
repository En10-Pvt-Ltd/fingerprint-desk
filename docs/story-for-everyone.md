# The Story of What We Built

*(Plain-language summary for a general audience. Every number here traces
back to the repo's generated records: demo/assets/provenance.json for the
website, field-test-002/ for the physical test.)*

## The problem we wanted to solve

Imagine a big exam. The question papers are printed and locked away. But
the night before the exam, someone who is *supposed* to guard them takes a
photo of a paper with their phone and sends it on WhatsApp. By morning,
thousands of students have seen it. The exam is ruined.

Here's the tricky part: everyone's paper looks exactly the same. So even
if the photo is found, nobody can tell *whose* copy was photographed. The
leaker gets away.

## Our idea: an invisible name tag

What if every printed copy was *secretly a little different*?

Not the words. The words stay the same. Instead, we nudge things by a
tiny amount: some lines of text sit a touch higher or lower, some gaps
between words are a touch wider or narrower. The nudges are about 170 to
250 microns, roughly two to three widths of a human hair. Sitting inside
a page full of text, they are invisible to the eye, but a computer can
measure them in a photo.

Each copy gets its own secret pattern of nudges, like a name tag written
in invisible ink. If a photo of a leaked paper shows up, the computer
reads the pattern and says: *"This came from copy number 2."*

## What we built

1. **A website** that explains the whole idea with real, working examples
   (it's on the internet now).
2. **An app on your computer** where you can do the whole thing yourself
   with clicks, not code: type or upload a document, make secret-tagged
   copies, print them, and later "scan" a leaked photo to find out which
   copy it was.
3. **The clever part we added last**: you can upload *any* PDF, with its
   pictures, headings, and fancy layout, and the app tags it **without
   changing how it looks at all**. We checked pixel by pixel: except for
   the secret nudges themselves, not a single dot changes.

## What we proved (this is the exciting bit)

**Test 1: can WhatsApp destroy the tag?** WhatsApp squishes photos to make
them smaller, which destroys most hidden marks. We tested ours: the tag
survived, and the computer read it **perfectly**.

**Test 2: does it work in real life, not just on a computer?** We printed
tagged papers, photographed them with a phone, and sent them through real
WhatsApp. The computer read the tags almost perfectly, **14 out of 14**
secret marks on one copy and **13 out of 14** on the other, and correctly
said which copy was which. To be fair about the size of this test: it was
two tagged copies from one printer and one phone; the promise that it
scales to thousands of copies rests on the mathematics behind the system
(its "evidence tier" table), which the bigger measurement campaign in the
research plan is designed to confirm.

**Test 3, the most important one: can it blame an innocent person?** We
printed a copy with **no tag at all** and tested it the same way. The
computer basically shrugged: "I see nothing here." It got about half its
guesses right, which is exactly what coin-flipping luck looks like. And
the system only ever points a finger when the odds of being wrong are
tiny; at full strength it is engineered so the chance of accusing an
innocent copy is at most **one in a million**. Better to stay silent
about a guilty person than to blame an innocent one: that rule is built
into the math.

**Bonus: the system even caught a mistake.** The printed sheets got mixed
up (they all look identical, remember?), and one photo was of a totally
different document. The computer worked out which sheet was really which,
and said "this one isn't even our document" about the stranger. It sorted
out the muddle by itself.

## What it does NOT do (being honest matters)

- If a leaker **retypes** the questions instead of photographing the
  page, the invisible tag is gone. Nothing survives retyping.
- If the paper leaks **before** the copies are printed with their tags,
  there is nothing to trace.
- **Tiny scraps** of a page give only a hint, not proof. Bigger leaks
  give stronger proof.
- Papers with **very small, squeezed-together text** hold the tag less
  well; normal-sized text works best.

## The one-sentence version

We turned an anonymous leaked photo into a signed confession: every
printed copy secretly carries its own invisible name tag that survives
printing, phone cameras, and WhatsApp, we proved it with real paper and a
real phone, and just as importantly, we proved the system stays silent
when there is no tag to find, and is built so the chance of ever blaming
an innocent copy is at most one in a million.
