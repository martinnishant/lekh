# Winsen Labs — what they actually want, and what to build for them

Research notes behind the `lekh` project. Everything here is from Winsen's own public
material, read closely, plus the two job descriptions. Sources at the bottom.

---

## 1. What the company actually is

| piece | what it is | why it matters to a candidate |
|---|---|---|
| **Winsen One** | role-specific "AI employees" for financial services: credit file review (Vera), alert disposition (Kai), reconciliation (Ira), freight bill audit (Freya)… each owns a queue, works 100% of it, and every output is a **draft until a named person signs it** | this is the product the Forward-Deployed Engineer ships |
| **Winsen Rho** | accountability layer: inventory of every agent, decision explorer, cost/value, vendor scorecards, human-oversight, drift, evidence packs mapped to 50 rules in 12 jurisdictions (RBI FREE-AI, MAS, EU AI Act…) | their argument is *measurable* accountability, not vibes |
| **Alfred** | the in-house harness every AI employee runs on: own machine inside the client VPC, persistent memory/state, credential vault, guarded outbound calls, sandboxed computer use, explicit model routing | "the model route is set explicitly and recorded, never guessed" |
| **Platos** | model-agnostic, self-hostable agent runtime, **v2 being rebuilt** from production lessons | live OSS surface, open issues, real engineering |
| **OCSO** | open customer success orchestration: WhatsApp/Slack/Teams, human handoff both ways, MCP tools, **maker-checker on every change**, tamper-evident audit store | their control vocabulary in one repo |
| **OVO** | open voice orchestrator, everything a plugin | speculative, less relevant |
| **Pioli / Winsen Ontology** | physical observability for plants, ports, cities | manufacturing/logistics angle |
| **Rocketman** | project hub that lives in the repo, because coding agents write most of the code | they are genuinely AI-native in *process*, not just in product |

Their public capability deck lists **"ten seats under a CRO"**: two deployable (credit
risk, operational risk) and eight in progress (compliance/regulatory change, liquidity &
ALM, market risk, fraud, cyber, model risk, enterprise risk, and "the manager").

**Reading:** they are not selling a chatbot or a copilot. They are selling *a worker with
a queue, a citation, an approval and an audit trail*, inside a regulated institution,
deployed forward. Everything they say about quality is about the last mile: volume,
constraints, signatures.

## 2. Decoding the two job descriptions

Both JDs are short, and every line is a filter. Reading them as a scoring rubric:

| line in the JD | what they are screening for | how to prove it, not claim it |
|---|---|---|
| "Strong on evals… evaluation datasets, regression tests, traces, failure analysis" (Founding) | you can measure an AI system, not just run one | a corpus with ground truth + a scored report, including where you fail |
| "build the evals, guardrails and audit trails that regulated work demands" (FDE) | you understand *why* a regulated buyer differs from a startup buyer | findings with clause + page; a hash-chained ledger; a human signature gate |
| "Wire into real stacks: core systems, mail, documents, data warehouses" | document plumbing is the job | PDF page-level extraction, manifests, hashes, labelled-field drift |
| "Systems-oriented… reliability, scale, failure modes, architecture" | you think in failure modes | explicit abstention taxonomy; determinism check; retries/idempotency in the ledger |
| "You write and speak clearly. Half this job happens with people" | they will put you in front of a credit head | a memo a credit officer would actually sign; a 3-minute demo script |
| "shipped things people actually used, and stuck around to maintain them" | not a weekend notebook | tests, a CLI, a runbook, a roadmap with the boring parts in it |
| "AI native… strong, earned opinions about where AI helps and where it gets in the way" | taste, not enthusiasm | the `code decides / model drafts` split, and saying plainly what the model must never do |
| "Mumbai, hybrid / on-site; deploy inside client institutions" | you will sit with a credit reviewer | write like someone who has watched a reviewer work |

**What they are almost certainly tired of seeing:** another RAG chatbot, another
"multi-agent framework", another Streamlit demo on a public dataset, and resumes that say
"AI-powered" without a single measured number. The differentiator is not more AI. It is
**evidence, refusal, and measurement**.

## 3. Their taste, inferred from their artefacts

These are the specific behaviours in their public product and repos that read as
*intentional*, and that a candidate can mirror:

1. **Citation to the page, not the document.** Winsen One's findings say
   "evidence · sanction memo p.2 · credit policy §4.3". Their policy maps cite clause and page.
2. **"Explained" is a real state.** Their demo shows `HL-8592 · LTV 84% against 80% cap,
   deviation approval on record` → "Noted in the memo as **explained**". A naive checker
   flags that. Theirs doesn't. This is the single most copy-able piece of product taste they have.
3. **Nothing counts without a named person.** "No output without a named approver" is
   listed as a thing they *never* compromise on.
4. **Replayability.** "Every decision, reopenable years later, exactly as it was."
5. **Residue stated exactly.** Their Platos issue titles literally say things like
   *"verify the whole branch, fix twelve gate failures it was carrying, and state the
   residue exactly"*. Honest scoping is house style.
6. **Model routing never guessed.** Alfred records the model route on every run.
7. **Open by default.** What can help others goes back out as Apache-2.0/MIT.

## 4. Problems I considered (and why most were rejected)

Scored on: *additive-not-derivative* (does it look like a copy of their product?),
*cost to build as a student (₹0)*, *demoability in 3 minutes*, and *evidence of the
signal they screen for*.

| idea | verdict | reason |
|---|---|---|
| Another "AI employee" that reviews loan files | ❌ reject | this *is* Winsen One. Rebuilding their product reads as either naive or arrogant. |
| RAG chatbot over RBI circulars | ❌ reject | crowded, no evals story, no failure discipline |
| Contribute a feature to Platos v2 | 🟡 good but risky | their issue list is dense and deep; a superficial PR would be visible immediately. Better as a *follow-up* after the interview, not the opener |
| Multi-agent invoice worker (already on my CV) | ❌ reject | it exists already; extending it says nothing new about *them* |
| **An eval + evidence kernel for a document-review seat** | ✅ chosen | additive (the bench, not the employee), squarely in their control vocabulary, impossible to fake, cheap to run, and it produces numbers |
| A policy-diff tool (v3.2 → v3.3 verdict changes) | ✅ strong, later | excellent second project; smaller demo surface on its own |
| Freight bill audit variant | 🟡 | same kernel, different policy — good as a "the kernel generalises" slide, not a separate build |

## 5. The chosen build, in one paragraph

**`lekh`** is a document-evidence review kernel. It ingests a loan file, applies the
lender's credit policy as code (15 rules, each with a clause and a page that is
*re-verified against the policy PDF at build time*), extracts every field with
`{document, page, quote}` provenance, and emits three kinds of outcome: `finding`,
`explained` (a breach covered by a valid, unexpired, correctly-leveled deviation — with
the register row as evidence), and `needs_human` (six distinct abstention causes:
missing doc, scanned doc, OCR ambiguity, label drift, conflicting valuations,
unevidenced co-applicant income). Every output is a draft until a named reviewer's
decision lands in a sha256 hash-chained ledger that can be verified and replayed.
`eval` scores the reviewer against 72 synthetic files with construction-based ground
truth, re-opens all 113 citations to check they resolve, and compares against a
memo-trusting baseline.

**Why it is additive:** Winsen builds the employees. Nobody in their public stack
publishes the thing that proves an employee is *right, cited and signed* — Platos is
runtime, OCSO is customer success, OVO is voice, Rho is the institution-level record.
This is the per-file, per-claim bench that sits underneath all of them.

## 6. The 3-minute demo script (rehearse this)

1. **0:00** — "Winsen's claim is coverage: 100% of the book instead of a 3% sample. That
   claim only survives if every finding resolves to a page and every explained breach
   stays explained. So I built the bench that measures that." Show the metric strip.
2. **0:30** — Open `HL-20035`. A breach, cited, with the deviation register row that
   explains it, and the derivation showing contractual EMI, verified obligations and
   verified income. "A memo-trusting reviewer files nothing here. A naive checker files a
   false positive. Both are wrong."
3. **1:15** — Open an abstention case. Show `1,O9,700` — "OCR turned a digit into an O. The
   row is withheld. Averaging the other five would give a confident, wrong income."
4. **2:00** — Show a bad deviation: `lapsed 20 days before sanction`, `signed at L1 where
   policy needs L2`. "The reason is the thing a credit head needs, so the reason is in the
   finding."
5. **2:40** — Show `eval`: 37/37, 0 false positives, 113/113 citations resolve, two runs
   identical. Then say the honest sentence out loud: "This is green on a corpus I designed,
   so it's a regression suite, not a field study. The first real thing I'd do on the job is
   run it against files your clients' teams have already reviewed and report where we
   disagree."
6. **3:00** — Stop. Let them ask the next question.

## 7. Questions they will ask, and the answers

**"Isn't this just rebuilding Winsen One?"**
No — it does not own a queue, it does not draft a workflow, it does not try to be an
employee. It is the checker and the record underneath one: policy in, findings out, a
signature and a chain. I built the part that would let *you* prove a seat is right.

**"Why not contribute to Platos instead?"**
I read the issue list. The right way to contribute is to know the runtime first. If I get
the job, my first PR is to make this kernel a Platos tool with the MCP surface their
runtime already versions, rather than a parallel path around it.

**"Your eval is 100%. Isn't that suspicious?"**
Yes, and I say so in the report. It is a regression suite built on a corpus I generated;
the oracle knows the answers because it wrote the numbers. The numbers that *aren't*
vanity are the awkward ones: the baseline at 24.3% recall, the seven false positives it
files on explained breaches, and the fact that this kernel abstains on 15 files instead
of guessing.

**"You're a student. Have you shipped anything?"**
The repository is the answer: 26 tests, a CLI, a hash-chained ledger with tamper
detection, a console that runs offline, an eval that reruns deterministically, and a
report that lists its own limitations.

---

### Sources
- winsenlabs.com/about, /build, /careers, /careers/forward-deployed-engineer — positioning, roles, OSS list
- winsen.one, winsen.one/how-it-works — AI employees, role cards, approvals, deviation/explained nuance, six-chapter workflow
- winsenrho.com — inventory, decision explorer, vendor scorecard, oversight, drift, regulation map
- winsenlabs.com/docs/winsen-labs-capabilities.pdf — Alfred, ten seats under a CRO, Pioli, OCSO case study
- github.com/winsenlabs (+ platos issue titles) — engineering taste and OSS surfaces
- winsen.ai/blog/what-does-the-future-of-work-look-like — orientation vs direction, and why signatures stay human
- RBI LTV slab norms (90% ≤ ₹30L, 80% ₹30–75L, 75% > ₹75L) — used as the policy's real-world anchor
