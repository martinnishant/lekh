"""Command line. Everything the project does, reachable from here.

    python -m lekh.cli generate          # build the synthetic corpus
    python -m lekh.cli check             # verify the policy's citations resolve
    python -m lekh.cli run               # review every file, write the ledger
    python -m lekh.cli eval              # score the reviewer, write the report
    python -m lekh.cli memo HL-20014     # one review memorandum
    python -m lekh.cli decide ...        # record a human decision
    python -m lekh.cli html              # self-contained console for a preview
    python -m lekh.cli serve             # live console on :8000
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lekh.engine import review_case, review_corpus  # noqa: E402
from lekh.evals import render_markdown, run_eval  # noqa: E402
from lekh.ledger import Ledger  # noqa: E402
from lekh.memo import draft_case_memo  # noqa: E402
from lekh.pdf import read_pdf_pages  # noqa: E402
from lekh.policy import load_policy, verify_citations  # noqa: E402

CORPUS = ROOT / "data" / "corpus"
POLICY = ROOT / "policy" / "retail_home_loan_v3.2.yaml"
POLICY_PDF = ROOT / "policy" / "retail_home_loan_v3.2.pdf"
LEDGER = ROOT / "state" / "ledger.jsonl"
REPORTS = ROOT / "reports"


def _run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")


def cmd_generate(args) -> None:
    subprocess.run([sys.executable, str(ROOT / "synth" / "generate.py"),
                    "--out", args.out, "--cases", str(args.cases),
                    "--seed", str(args.seed)], check=True)
    subprocess.run([sys.executable, str(ROOT / "synth" / "make_policy_pdf.py")], check=True)


def cmd_check(args) -> None:
    policy = load_policy(args.policy)
    pages = read_pdf_pages(POLICY_PDF)
    problems = verify_citations(policy, pages)
    print(f"policy {policy.name} v{policy.version} fingerprint {policy.fingerprint}")
    print(f"{len(policy.rules)} rules, {len(pages)} pages in {POLICY_PDF.name}")
    if problems:
        for p in problems:
            print("  UNRESOLVED CITATION:", p)
        sys.exit(1)
    print("every rule's clause quote resolves to the page it cites")


def cmd_run(args) -> None:
    run_id = args.run_id or _run_id()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    records = review_corpus(args.corpus, args.policy, args.ledger, run_id)
    elapsed = time.time() - t0
    out = REPORTS / "records"
    out.mkdir(parents=True, exist_ok=True)
    for rec in records:
        (out / f"{rec.loan_id}.json").write_text(json.dumps(rec.to_dict(), indent=2,
                                                            default=str), encoding="utf-8")
    ledger = Ledger(args.ledger)
    flagged = sum(len(r.flagged) for r in records)
    explained = sum(len(r.explained) for r in records)
    abstained = sum(len(r.needs_human) for r in records)
    print(f"{len(records)} files in {elapsed:.1f}s  |  {flagged} findings, "
          f"{explained} explained, {abstained} abstained")
    print(f"ledger: {args.ledger} ({len(ledger.events)} events, tail {ledger.tail_hash()[:16]})")
    problems = ledger.verify()
    print("chain:", "intact" if not problems else problems)


def cmd_eval(args) -> None:
    run_id = args.run_id or _run_id()
    policy = load_policy(args.policy)
    t0 = time.time()
    records = review_corpus(args.corpus, args.policy, None, run_id + "-a")
    rerun = review_corpus(args.corpus, args.policy, None, run_id + "-b")
    elapsed = time.time() - t0
    result = run_eval(args.corpus, records, rerun, policy, elapsed)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "eval-report.json").write_text(json.dumps(result.to_dict(), indent=2,
                                                         default=str), encoding="utf-8")
    md = render_markdown(result)
    (REPORTS / "eval-report.md").write_text(md, encoding="utf-8")
    (REPORTS / "console-data.json").write_text(json.dumps({
        "records": [r.to_dict() for r in records],
        "eval": result.to_dict(),
    }, default=str), encoding="utf-8")
    t = result.totals
    print(f"recall {t['recall']*100:.1f}%  precision {t['precision']*100:.1f}%  "
          f"exact {t['exact_case_match']*100:.1f}%  citations {t['citation_validity']*100:.1f}%")
    print(f"baseline recall {result.baseline['recall']*100:.1f}%  "
          f"baseline false positives {result.baseline['false_positives']}")
    print(f"determinism: {'identical' if result.determinism['identical'] else 'DIFFERENT'} digests")
    print(f"wrote {REPORTS/'eval-report.md'}")


def cmd_memo(args) -> None:
    policy = load_policy(args.policy)
    rec = review_case(args.corpus / args.loan_id, policy, args.run_id or "memo")
    draft = draft_case_memo(rec, provider=args.draft_with)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"memo-{args.loan_id}.md"
    out.write_text(draft.markdown, encoding="utf-8")
    print(draft.markdown[:2000])
    print(f"\n...\nwrote {out}")
    for g in draft.guards:
        print("guard:", g)


def cmd_decide(args) -> None:
    ledger = Ledger(args.ledger)
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    ledger.append("decision", {
        "loan_id": args.loan_id, "finding_id": args.finding_id, "action": args.action,
        "reviewer": args.reviewer, "note": args.note or "",
    }, ts)
    print(f"recorded {args.action} on {args.finding_id} by {args.reviewer}; "
          f"tail {ledger.tail_hash()[:16]}; chain "
          f"{'intact' if not ledger.verify() else 'BROKEN'}")


def cmd_html(args) -> None:
    """Render the console to one self-contained file (works with no network)."""
    data_path = REPORTS / "console-data.json"
    if not data_path.exists():
        print("run `python -m lekh.cli eval` first", file=sys.stderr)
        sys.exit(1)
    data = data_path.read_text(encoding="utf-8")
    template = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", data)
    out = REPORTS / "console.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")


def cmd_serve(args) -> None:
    import uvicorn
    uvicorn.run("lekh.api:app", host="0.0.0.0", port=args.port, reload=False)


def main() -> None:
    ap = argparse.ArgumentParser(prog="lekh")
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--policy", default=str(POLICY))
    ap.add_argument("--ledger", default=str(LEDGER))
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate"); g.add_argument("--out", default=str(CORPUS))
    g.add_argument("--cases", type=int, default=72); g.add_argument("--seed", type=int, default=7)
    g.set_defaults(fn=cmd_generate)

    c = sub.add_parser("check"); c.set_defaults(fn=cmd_check)
    r = sub.add_parser("run"); r.add_argument("--run-id", default=None); r.set_defaults(fn=cmd_run)
    e = sub.add_parser("eval"); e.add_argument("--run-id", default=None); e.set_defaults(fn=cmd_eval)
    m = sub.add_parser("memo"); m.add_argument("loan_id")
    m.add_argument("--draft-with", default="template", choices=["template", "ollama", "groq"])
    m.add_argument("--run-id", default=None); m.set_defaults(fn=cmd_memo)
    d = sub.add_parser("decide"); d.add_argument("loan_id"); d.add_argument("finding_id")
    d.add_argument("action", choices=["approve", "edit", "reject", "explain"])
    d.add_argument("--reviewer", default="R. Mehta, Senior Credit Officer")
    d.add_argument("--note", default=None); d.set_defaults(fn=cmd_decide)
    h = sub.add_parser("html"); h.set_defaults(fn=cmd_html)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    args = ap.parse_args()
    args.corpus = Path(args.corpus)
    args.policy = Path(args.policy)
    args.ledger = Path(args.ledger)
    args.fn(args)


if __name__ == "__main__":
    main()
