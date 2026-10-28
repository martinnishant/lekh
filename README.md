# lekh

[![ci](https://github.com/martinnishant/lekh/actions/workflows/ci.yml/badge.svg)](https://github.com/martinnishant/lekh/actions/workflows/ci.yml)

**A document-evidence review kernel.** It reads a loan file, applies the lender's
credit policy as code, cites the page behind every claim, files a breach covered
by a valid deviation as *explained* rather than flagged, abstains out loud when it
cannot verify something, and blocks every output behind a named human signature on
a hash-chained ledger.

Built for the kind of work Winsen One's AI employees do (credit file review,
reconciliation, alert disposition), and built so an AI reviewer can be **measured**
instead of trusted.

> `lekh` (लेख) — a record, an account. The thing that is written down and can be
> produced later when someone asks how you knew.

```
72 files · 435 documents · 645 pages    →    37 seeded defects, 0 missed, 0 invented
113 citations re-opened and checked     →    113 resolve to the page they name
15 files that cannot be decided         →    15 abstentions, 0 silent passes
 6 breaches covered by a real deviation  →     6 filed as explained, 0 false alarms
memo-trusting baseline on the same files → 24.3% recall, 7 false positives
```

---

## Why this, and not another agent demo

Winsen's own writing says the thing they care about most plainly:
*"The last mile is the whole game… real volume, real constraints, real signatures."*
And their product copy draws a line that most AI demos blur: **coverage, not speed**.
A hand review samples 2–5% of a book; an AI employee reads 100% of it. That argument
only survives if three unglamorous properties hold:

1. **Every claim resolves to a document, a clause and a page.** A finding without a
   citation is an opinion, and an opinion at 100% coverage is a liability.
2. **A breach covered by a valid, unexpired approval is not a false positive.** If the
   system flags explained breaches, reviewers learn to click Approve without reading,
   and the audit trail becomes theatre.
3. **When it cannot verify, it says so.** A missing statement, a scanned page, an OCR
   ambiguity, two valuations — all of these must produce an abstention, never a silent
   pass. A confident wrong review is the only unrecoverable failure mode here.

`lekh` is built entirely around those three properties, because everything else in this
category is a demo.

## The three commitments, in code

**1. Code decides; the model only writes prose.**
Numbers are recomputed from source documents — the statement's *transactions*, not the
statement's summary; the valuer's *report*, not the memo's restatement of it. If an LLM
is used at all it re-words a finding that deterministic code already proved, and
`memo.numeric_fidelity()` rejects any draft that contains a number not already present
in that finding's derivation or evidence. The model cannot introduce a figure. This is
the "model plans, code enforces" split, applied to text instead of writes.

**2. A deviation is a first-class outcome.**
`explained` is a distinct status from `finding`, and the evidence for it is the
register row itself. Invalid deviations are reported *with their reasons*
(lapsed 20 days before sanction, signed at L1 where policy needs L2, registered
against another file) rather than silently dropped — because the reason is exactly
what a credit head needs.

**3. Abstention is a measured outcome, not a bug.**
Six independent causes produce `needs_human`, each with the artifact that caused it:

| cause | what it looks like in a real file |
|---|---|
| missing document | the statement never made it into the file |
| unreadable document | the branch scanned the bureau report; 0 characters of text |
| extraction gap | OCR read a digit as `O`: `1,O9,700` — the row is withheld, not guessed |
| label drift | this branch's memo says "gross", not "net"; the figure is not comparable |
| conflicting valuations | a revised opinion lands after the original report |
| unevidenced co-applicant income | stated in the memo, no statement on file |

## Architecture

```
                 ┌──────────────────────────────────────────────┐
   PDFs +        │  intake          page text · sha256          │
   manifest ────▶│                  manifest comparison          │
                 └───────────────┬──────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────┐
                 │  extract         every field carries         │
                 │                  {doc, page, quote}          │
                 │                  count-preserving: rows that  │
                 │                  fail to parse are gaps      │
                 └───────────────┬──────────────────────────────┘
                                 ▼
   policy.yaml   ┌──────────────────────────────────────────────┐
   + policy.pdf ─▶  rules          15 checks, each citing a     │
   (citation-    │                 clause *and its page*; the    │
    verified)    │                 citation is re-verified       │
                 │                 against the PDF at build time │
                 └───────────────┬──────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────┐
                 │  findings       finding | explained |        │
                 │                 needs_human                  │
                 └───────────┬──────────────────┬───────────────┘
                             ▼                  ▼
              ┌────────────────────┐   ┌────────────────────────┐
              │ memo (template or  │   │ ledger: append-only,   │
              │ LLM, number-guard) │   │ sha256 hash chain,     │
              └────────────────────┘   │ replay(), audit pack   │
                                       └────────────────────────┘
```

Nothing in this diagram requires a network call. The system runs at ₹0.

## Worked examples (real output from this repo)

**1. A covered breach that must not become a false alarm — `HL-20126`**

```
status: explained · foir_breach · clause 5.2 · policy p.3
claim:  FOIR 62.0% exceeds the 55% cap, covered by deviation D-2317
deriv:  emi_contractual 30,800 · obligations_verified 54,500 · income_verified 1,37,550
        deviation D-2317 · L2 - Credit Head · valid to 30 Sep 2026
evid:   bank_statement.pdf p.1 (credits) · sanction_memo.pdf p.1 · deviation_register.pdf p.1
```

The memorandum states an FOIR of 63.1% and carries the deviation that covers it, which is
the whole argument in one file: a violation that has already been decided by the right
person, with the evidence attached. A checker with no deviation logic produces a false
positive here; a reviewer that only samples never sees the file at all.

**2. An OCR ambiguity that would otherwise become a confident wrong number — `HL-20273`**

```
status: needs_human · extraction_gap · clause 3.4 · policy p.1
claim:  1 transaction row could not be parsed with confidence
sample: "07/03/2026  SALARY CREDIT - NEFT  O,59,100  3,04,100"
```

The leading digit was read as a letter. Averaging the other five credits would have
produced a plausible income and a plausible FOIR. The system stops instead, and says
which row stopped it.

**3. Deviations that do not provide cover — `HL-20343`, `HL-20399`**

```
FOIR 64.9% breaches the 55% cap → D-2511: lapsed on 13 Sep 2026, before sanction
FOIR 73.8% breaches the 55% cap → D-2519: registered against HL-90056, not this file
```

The deviation is not silently ignored: it is reported next to the breach with the reason
it failed, because the reason is the thing a credit head has to act on.

## Results (regression suite, not a field study)

`python -m lekh.cli eval` — 72 synthetic files with construction-based ground truth:

| metric | lekh | memo-trusting baseline |
|---|---|---|
| defect recall | **100%** (37/37) | 24.3% (9/37) |
| precision | **100%** | 56.2% |
| false positives | **0** | 7 |
| defects a memo-only reviewer cannot see (income, valuation, tamper, KYC, PDD, stale bureau, arithmetic) | **22/22** | **0/22** |
| citation validity | **100%** (113/113 re-opened) | n/a — cites nothing |
| deviations correctly credited as explained | **6/6** | 0/6 |
| files correctly abstained | **15/15** | 0/15 |
| unnecessary abstentions on reviewable files | **0** | n/a |
| determinism | two runs, identical digests | — |

**Read this table the way it should be read.** It is green on a corpus I designed, so it
is a **regression suite** — evidence that the rules behave as specified and that nothing
drifts between runs. It is *not* evidence of field performance. The oracle knows the
numbers because it wrote them; it cannot catch a rule that is wrong in the same way in
both places. Only a pilot on historical files a credit team has already reviewed can do
that, and that is the first thing I would ask for.

## What this deliberately does not do

- **No OCR.** Scanned files are detected and abstained, not guessed at.
- **No core-system access.** Numbers are verified against documents, not against the
  loan management system. The real pilot wires that in; until then the review is
  document-true, not system-true.
- **One policy, one product, one archetype.** Retail home loans, one lender's policy.
  Nothing here is tested against co-lending, balance transfer, or restructured accounts.
- **No autonomous action.** There is no code path where a finding has effect without a
  named reviewer's decision in the ledger. That is a design choice, not a missing feature.
- **No claim to be Winsen One.** See below.

## Where this fits Winsen's stack (and where it does not)

This is not a re-implementation of Winsen One, and it would be a bad look to pretend it
is. It is the **evidence kernel** underneath a seat like Vera, offered as the thing that
makes a seat measurable:

| Winsen piece | how lekh connects |
|---|---|
| **Platos** (agent runtime) | the rule engine is deterministic and stateless — a Platos tool call, not a competing orchestrator. `review_case()` is the natural tool boundary. |
| **MCP** (tool surface for OCSO/OVO) | `findings`, `evidence`, `decide` and `verify_ledger` are the four tools any reviewed workflow needs; they map onto MCP 1:1. |
| **Winsen Rho** (accountability) | every finding already carries an input digest, a policy fingerprint, a derivation and an approval — the exact shape Rho's decision record wants. Consistency rate per rule is one query away. |
| **Winsen One** (the seats) | the same kernel serves credit review (Vera), alert disposition (Kai), GRN reconciliation (Neel) and freight bill audit (Freya): the policy changes, the kernel does not. |
| **Their deviation nuance** | Winsen's own demo shows a breach "explained" by a deviation on record. That behaviour is implemented and measured here, including the four ways a deviation can be invalid. |

The honest one-line version: **Winsen builds the employees; this is the bench that
proves an employee is right, cited and signed.**

## Run it

Full deployment walkthrough (zip → GitHub → live URL → optional API): **[docs/DEPLOY.md](docs/DEPLOY.md)**.

```bash
pip install -r requirements.txt

python -m lekh.cli generate     # 72 synthetic loan files (all local, ~10s)     # 72 synthetic loan files (PDFs + ground truth)
python -m lekh.cli check        # verify every rule's citation resolves to its page
python -m lekh.cli run          # review all files, write the hash-chained ledger
python -m lekh.cli eval         # score against ground truth, write the report
python -m lekh.cli memo <LOAN>  # one review memorandum
python -m lekh.cli decide <LOAN> <FINDING> approve --reviewer "R. Mehta"
python -m lekh.cli html         # one self-contained console file (no network needed)
python -m lekh.cli serve        # live console + decision API on :8000

pytest -q                       # 26 tests, including the corpus regression gate
```

Optional LLM drafting (still ₹0): `--draft-with ollama` against a local model, or
`--draft-with groq` with a free-tier key. Either way the numeric-fidelity guard runs
first and the template is the fallback.

## Map

```
lekh/
  policy.py      rules cite a clause *and a page*, verified against the PDF
  pdf.py         intake: page text, sha256, manifest comparison
  extract.py     fields with provenance; unparseable rows become gaps, not zeros
  rules.py       15 checks; finding | explained | needs_human, never a silent pass
  engine.py      the review run → a boring, replayable CaseRecord
  ledger.py      append-only hash chain, verify(), replay(), audit pack
  memo.py        memo drafting + numeric-fidelity guard
  evals.py       scoring: recall, precision, citations, abstention, baseline
  api.py         console, case API, decision gate, ledger endpoints
  cli.py         everything above, from one entry point
synth/
  generate.py    72 files: 19 defect families incl. an adversarial slice
  make_policy_pdf.py  the policy PDF the rules cite
web/index.html  the console (self-contained; works with no network)
reports/        eval report, per-file records, memos, the console export
tests/          26 tests, each naming a failure mode in the domain
```

## What I would build next, in order

1. **A real-file pilot kit.** Run the kernel over historical files a credit team has
   already reviewed, and report only where the kernel and the humans disagree. That
   disagreement list is the product's first honest number.
2. **Trace and replay.** Persist the extracted field graph per run so any finding can be
   re-derived from the same inputs years later (Rho's "reopen any decision" requirement).
3. **Policy diffing.** When the policy moves v3.2 → v3.3, re-run the corpus and show which
   files change verdict, with the clause that caused it.
4. **OCR as a first-class source**, with per-field confidence, so a scanned file becomes a
   low-confidence review instead of an abstention.
5. **A second seat on the same kernel** (alert disposition: Kai) to prove the kernel is
   the reusable part and the employee is the configuration.
