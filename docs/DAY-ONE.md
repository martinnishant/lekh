# If I joined tomorrow

Not a wish list. The order I would actually do these in, and why.

**Week 1 — get inside the work before touching the code.**
Sit with two credit reviewers for a full day each, one who is fast and one who is slow.
Take away: the ten files they disagree about, and the three checks they do that are not in
the SOP. Those two artefacts are worth more than any architecture decision I could make
from a desk in Mumbai.

**Week 1–2 — the disagreement list.**
Run the kernel over 200 historical files the client has already reviewed. Produce one
table: file, what the human decided, what the kernel decided, and for every disagreement,
the clause and the page. Do not fix anything yet. The disagreement list *is* the product
case, and it is the first honest number the client sees.

**Week 2–3 — kill the classes of error that cost trust.**
Order matters: false positives on explained breaches first (they destroy reviewer
attention), then silent passes (they destroy the argument), then extraction gaps. Anything
that produces a confident wrong number is a stop-the-line bug.

**Week 3–4 — make it replayable.**
Persist the extracted field graph and the policy fingerprint per run, so a finding can be
re-derived from the same inputs a year later. This is what Rho's "reopen any decision"
requires, and it is much cheaper to design now than to retrofit.

**Week 4 — one seat, wired into the client's systems.**
Replace the synthetic statement with the core-system feed where one exists; keep the
document path where it does not. Two sources that disagree is a feature: it is how you
learn which one the reviewers actually trust.

**Ongoing — the thing I would defend in a design review.**
Deterministic code decides; the model only writes. If a future seat needs the model to
decide something, it has to arrive as a proposal with a confidence and a fallback, never as
an answer. The moment a number comes from a model, the audit trail becomes an opinion.

**What I would want feedback on in the first month.**
Whether the abstention taxonomy is right for this bank (I have six causes; a real book will
have more, and some of mine are probably rare in practice), and whether per-family recall is
the number the credit head actually wants, or whether it is "files I would have signed that
you stopped".
