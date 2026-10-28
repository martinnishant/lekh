# Winsen Labs — application drafts (Forward-Deployed Engineer + Founding AI + Backend Engineer)

Read the notes in square brackets before sending. Both forms ask for short text; short
and true beats long and polished. Do not paste an essay into either box.

---

## 0. Before you send anything (do these three things, in this order)

1. **Push this repo to GitHub as `lekh`** (or whatever name you prefer). Add the topics:
   `ai-agents`, `evals`, `document-ai`, `llm`, `audit-trail`, `fintech`, `india`.
   Pin it. Your GitHub link then lands on something that is not a notebook.
2. **Deploy `reports/console.html` somewhere public** — it is a single self-contained
   file, so GitHub Pages works with zero config. Put that URL in the application. A live
   link a reviewer can click in 4 seconds beats a repo they have to clone.
3. **Record a 3-minute screen capture** with voice-over, following the script in
   `docs/RESEARCH.md` §6. Unlisted YouTube link. This is the single highest-leverage
   thing you can do for a "forward-deployed" role, because the job is standing in front of
   people and explaining.

Then send. Application review is stated to include automated screening and human review,
so the first line has to survive a keyword pass *and* a tired human.

---

## 1. Forward-Deployed Engineer (WL-2026-001, 2 positions)

The form asks for: a few lines about yourself, a link to something you have built, résumé.
Suggested answer (≈120 words — edit the bracketed bits, keep it this length):

> I'm Nishant, an AI engineer finishing a CS degree at LPU, and I've spent the last year
> building agents that have to survive contact with someone else's rules rather than a
> demo. My current project is a credit-file review kernel for Indian retail home loans: it
> reads a loan file, applies the lender's policy as code, cites the page behind every
> finding, files a breach covered by a valid deviation as *explained* instead of flagging
> it, abstains out loud when it can't verify something (missing statement, scanned page,
> OCR ambiguity), and blocks every output behind a named reviewer's signature on a
> hash-chained ledger. 15 rules, 72 synthetic files, 435 documents; the eval re-opens all
> 113 citations to prove they resolve, and the memo-only baseline on the same files scores
> 24% recall.
>
> **Link:** [live console] + [github.com/martinnishant/lekh]
>
> I want to be in the client's office when it breaks. That's why the FDE seat.

Why this works: it names a domain they sell into, uses their vocabulary (*explained*,
named approver, audit trail, coverage), and gives numbers instead of adjectives. The last
line answers the part of the JD that most candidates skip.

Whatever you send, attach the résumé *and* keep the GitHub link inside the text box too —
forms lose attachments.

## 2. Founding AI + Backend Engineer (WL-2026-006)

This one asks: link your GitHub and anything you have shipped, and tell us about the work
you are proudest of. Suggested answer (≈150 words):

> **What I'm proudest of:** a document-evidence review kernel I built to make an AI
> reviewer measurable instead of trusted ([repo]) ([live console]).
>
> The engineering decision I care about most is the split: deterministic code decides,
> the model only writes prose. Every number is recomputed from source documents — the
> statement's transactions rather than the statement's summary, the valuer's report
> rather than the memo's restatement of it — and the memo drafter runs a numeric-fidelity
> guard that rejects any draft containing a figure not already in the finding's
> derivation. The model cannot introduce a number. Three outcomes exist and no fourth:
> `finding`, `explained`, `needs_human`. Abstention has six causes, all measured, because
> extraction that silently drops a row it cannot read is the only unrecoverable failure
> mode in this domain. Everything lands in a sha256 hash-chained ledger with `verify()`
> and `replay()`. The eval scores 37/37 seeded defects, zero false positives on 21 clean
> files, 113/113 citations resolving, two runs byte-identical, against a 24% baseline.
>
> Before that: an autonomous invoice worker with a "model plans, code enforces"
> architecture (idempotent writes, risk-based human approval, SHA-256 read-back
> verification), and a serverless AWS pipeline (S3 → Lambda → Bedrock → QuickSight) at
> Futurense.
>
> **GitHub:** [link] · **Console:** [link] · **Eval report:** [link]

Two more things for this role specifically:

- **Say the honest sentence about the eval.** "It's green on a corpus I generated, so it's
  a regression suite, not a field study; the first thing I'd do on the job is run it on
  files a credit team has already reviewed and report where we disagree." This reads as
  senior, and their own issue titles are written in exactly that register.
- **Have a Platos opinion ready.** Read `github.com/winsenlabs/platos` for 30 minutes and
  be able to say which part of your kernel you would turn into a Platos tool first, and
  why. Do not pretend to have contributed.

---

## 3. If you can also get to a human (recommended)

The careers page says *"Don't see your role? Convince us we need one"* and lists
`hello@winsenlabs.com`. Use that as a third touch, two days after applying, once. Short:

> Subject: Forward-deployed + founding engineer — a credit-review kernel built for your
> stack
>
> Hi — I applied for both engineering roles (WL-2026-001 / WL-2026-006). Rather than wait,
> I built the thing I'd want to work on: **lekh**, an evidence kernel for document-review
> seats. Policy as code with clause-and-page citations that are re-verified against the
> policy PDF, a deviation gate so covered breaches come out `explained` instead of
> flagged, six measured abstention causes, and a hash-chained approval ledger.
>
> 72 synthetic Indian home-loan files, 37 seeded defects, 0 missed, 0 invented, 113/113
> citations resolve, memo-trusting baseline at 24% recall. Live console (4 seconds, no
> login): [link]. Repo: [link]. Report that lists everything it does *not* prove:
> [link].
>
> I know it's a bench, not an employee — Winsen builds the employees. I'd like to build
> the bench that proves they're right, and then go sit with the credit reviewer who has to
> sign the output.
>
> Nishant · [phone] · [github]

Do not send a second follow-up. If they reply, the next message is a 3-minute video, not
another paragraph.

---

## 4. Interview prep that isn't generic

**Expect these, in roughly this order:**

| question | your answer, in one breath |
|---|---|
| "Walk me through the architecture." | intake (page text + sha256 + manifest) → extract (every field carries doc/page/quote; unparseable rows become gaps) → rules (15 checks, each citing a clause and a page that is verified against the PDF at build) → findings (three statuses) → memo + hash-chained ledger. |
| "Why not just use an LLM for the whole thing?" | Because a wrong number is indistinguishable from a right one in prose. Code recomputes from records; the model may re-word what code proved, and a numeric guard rejects anything else. |
| "How do you know it works?" | Corpus with construction-based ground truth, per-family recall, false positives on clean files, citation fidelity re-checked by reopening the PDF, determinism across two runs, and an explicit list of what the eval cannot prove. |
| "What's the weakest part?" | The oracle shares my blind spots; the corpus is synthetic; no OCR; no core-system reconciliation; one product archetype. Say all five. |
| "A client says a finding is wrong. What happens?" | The rejection is a ledger event with their name; the finding's derivation and evidence are in the event, so the disagreement is replayable. Corrections become proposed rule changes, never silent rewrites. |
| "You're a fresher. Why should we?" | "Founding engineer, one to two years or exceptional new grads with strong portfolios" is in your JD. Here's the portfolio, here are the numbers, here's what I got wrong. |

**Also prepare:** a 5-minute live take-home-style task — given a policy clause and a
sample PDF, write a rule with a citation and a test. Practise it once out loud. The
take-home is the real filter; the interview is a discussion *around* it.

---

## 5. Two weeks after you send (do this whether or not they reply)

Pick one and ship it, publicly:

1. **A second seat on the same kernel** — alert disposition (their Kai): same policy
   engine, different rule set, proving the kernel is the reusable part. This is the
   strongest possible answer to "is this a one-off demo?"
2. **Policy diffing v3.2 → v3.3** — re-run the corpus, output which files change verdict
   and the clause that caused it. This is a thing banks actually ask for and nobody builds.
3. **A Platos tool wrapper** — make `review_case()` callable through their runtime's tool
   contract and open a small, careful PR or discussion. Small, correct, and shaped like
   their issue style.

Any one of those, added to this repo, turns "student project" into "engineer with a
body of work". That is what the founding-engineer JD says it is screening for.
