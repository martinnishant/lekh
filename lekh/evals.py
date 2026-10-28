"""The eval rig: score the reviewer against ground truth, and score the scorer.

Three things this measures that a demo cannot:

  1. **Recall on hidden defects.** The defects a memo-only reviewer cannot see
     (income inflation, valuation drift, edited documents) are the ones that
     matter. They are counted separately.
  2. **False positives on explained breaches.** A breach covered by a valid,
     unexpired L2 deviation must come out `explained`, not `flagged`. A system
     that flags it trains reviewers to click Approve without reading.
  3. **Citation fidelity.** Every claim is checked back against the page it
     cites, by re-opening the PDF. A citation that does not resolve is a
     fabrication, and it is counted as one.

Plus a baseline: the reviewer a bank has today, which trusts the memorandum.
The delta between the baseline and the kernel is the argument for the kernel.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .engine import CaseRecord
from .extract import Facts
from .policy import Policy
from .pdf import load_case


# ---------------------------------------------------------------------------- scoring
def _norm_quote(s: str) -> str:
    return " ".join((s or "").split()).lower()


def citation_report(record: CaseRecord, folder: Path) -> dict:
    """Re-open the cited documents and check every quote is really there."""
    docs = {d.name: d for d in load_case(folder).documents.values()}
    checked = failed = skipped = 0
    failures: list[dict] = []
    for f in record.findings:
        for ev in f.evidence:
            if ev.get("kind") == "system_record":
                skipped += 1
                continue
            doc = docs.get(ev.get("doc", ""))
            if doc is None or not ev.get("quote"):
                failed += 1
                failures.append({"finding": f.family, "evidence": ev, "why": "document or quote absent"})
                continue
            checked += 1
            try:
                page_text = _norm_quote(doc.page(int(ev["page"])))
            except Exception:
                failed += 1
                failures.append({"finding": f.family, "evidence": ev, "why": "page does not exist"})
                continue
            if _norm_quote(ev["quote"]) not in page_text:
                failed += 1
                failures.append({"finding": f.family, "evidence": ev, "why": "quote not on cited page"})
    total = checked + failed
    return {"checked": checked, "failed": failed, "system_records": skipped,
            "validity": 0.0 if total == 0 else round(checked / total, 4),
            "failures": failures[:20]}


def score_case(record: CaseRecord, expected: list[dict]) -> dict:
    exp = [(e["family"], e["status"]) for e in expected]
    exp_needs = [e for e in exp if e[1] == "needs_human"]
    exp_findings = [e for e in exp if e[1] != "needs_human"]

    pred = [(f.family, f.status) for f in record.findings]
    pred_needs = [f for f in record.findings if f.status == "needs_human"]
    pred_claims = [(f.family, f.status) for f in record.findings if f.status != "needs_human"]

    tp, fn = [], []
    for item in exp_findings:
        if item in pred:
            tp.append(item)
        else:
            fn.append(item)

    fp = [p for p in pred_claims if p not in exp]

    # an abstention is scored once per case: any needs_human covers it
    needs_ok = (not exp_needs) or bool(pred_needs)
    unnecessary_abstention = (not exp_needs) and bool(pred_needs)

    return {
        "loan_id": record.loan_id,
        "expected": exp, "predicted": pred,
        "tp": tp, "fn": fn, "fp": fp,
        "needs_human_expected": bool(exp_needs),
        "needs_human_emitted": bool(pred_needs),
        "needs_human_correct": needs_ok,
        "unnecessary_abstention": unnecessary_abstention,
        "exact": set(exp_findings) == set(pred_claims) and needs_ok,
    }


def baseline_predict(record: CaseRecord, policy: Policy) -> list[tuple[str, str]]:
    """The reviewer a bank has today: it believes the memorandum."""
    f = record.facts
    cap = policy.rule("R-05").params["cap"]
    slabs = policy.rule("R-06").params["slabs"]
    loan = f.get("sanction_amount") or 0
    ltv_cap = next(s["cap"] for s in slabs if loan <= s["up_to"])
    out: list[tuple[str, str]] = []
    if (f.get("foir_stated") or 0) > cap:
        out.append(("foir_breach", "finding"))          # never credits a deviation
    if (f.get("ltv_stated") or 0) > ltv_cap:
        out.append(("ltv_breach", "finding"))
    if (f.get("bureau_score") or 999) < 700:
        out.append(("bureau_low", "finding"))
    if (f.get("dpd_max_12m") or 0) >= 30:
        out.append(("dpd_delinquency", "finding"))
    return out


# ---------------------------------------------------------------------------- report
@dataclass
class EvalResult:
    cases: list[dict]
    citations: dict
    by_family: dict
    totals: dict
    baseline: dict
    determinism: dict
    runtime_seconds: float
    policy: dict
    corpus: dict
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cases": self.cases, "citations": self.citations, "by_family": self.by_family,
            "totals": self.totals, "baseline": self.baseline,
            "determinism": self.determinism, "runtime_seconds": self.runtime_seconds,
            "policy": self.policy, "corpus": self.corpus, "notes": self.notes,
        }


def run_eval(corpus: str | Path, records: list[CaseRecord], records_rerun: list[CaseRecord],
             policy: Policy, runtime_seconds: float) -> EvalResult:
    corpus = Path(corpus)
    cases: list[dict] = []
    citations_all = {"checked": 0, "failed": 0, "system_records": 0, "failures": []}
    by_family: dict[str, dict] = {}
    base_tp = base_fp = base_exp = 0

    for rec in records:
        gt = json.loads((corpus / rec.loan_id / "ground_truth.json").read_text(encoding="utf-8"))
        expected = gt["expected"]
        s = score_case(rec, expected)
        cit = citation_report(rec, corpus / rec.loan_id)
        s["citations"] = {"validity": cit["validity"], "failed": cit["failed"]}
        cases.append(s)

        citations_all["checked"] += cit["checked"]
        citations_all["failed"] += cit["failed"]
        citations_all["system_records"] += cit["system_records"]
        citations_all["failures"].extend(cit["failures"])

        for fam, status in [(e["family"], e["status"]) for e in expected if e["status"] != "needs_human"]:
            row = by_family.setdefault(fam, {"expected": 0, "detected": 0, "status_wrong": 0,
                                             "baseline_detected": 0})
            row["expected"] += 1
            if (fam, status) in s["tp"]:
                row["detected"] += 1
            elif (fam, status) in [(p[0], p[1]) for p in s["predicted"]]:
                row["status_wrong"] += 1
        base_pred = baseline_predict(rec, policy)
        exp_pairs = [(e["family"], e["status"]) for e in expected if e["status"] != "needs_human"]
        base_exp += len(exp_pairs)
        base_tp += len([p for p in base_pred if p in exp_pairs])
        base_fp += len([p for p in base_pred if p not in exp_pairs])
        for fam in {f for f, _ in base_pred}:
            if fam in by_family:
                by_family[fam]["baseline_detected"] += 1

    for fam, row in by_family.items():
        row["recall"] = round(row["detected"] / row["expected"], 4) if row["expected"] else None
        row["baseline_recall"] = round(min(row["baseline_detected"], row["expected"]) / row["expected"], 4) \
            if row["expected"] else None

    tp = sum(len(c["tp"]) for c in cases)
    fn = sum(len(c["fn"]) for c in cases)
    fp = sum(len(c["fp"]) for c in cases)
    needs = [c for c in cases if c["needs_human_expected"]]
    totals = {
        "cases": len(cases),
        "exact_case_match": round(sum(1 for c in cases if c["exact"]) / max(len(cases), 1), 4),
        "defects_expected": tp + fn,
        "defects_detected": tp,
        "defects_missed": fn,
        "recall": round(tp / max(tp + fn, 1), 4),
        "false_positives": fp,
        "precision": round(tp / max(tp + fp, 1), 4),
        "clean_files": sum(1 for c in cases if not c["expected"]),
        "false_positives_on_clean_files": sum(
            1 for c in cases if not c["expected"] and c["fp"]),
        "explanations_expected": sum(1 for c in cases for e in c["expected"] if e[1] == "explained"),
        "explanations_credited": sum(
            1 for c in cases for e in c["expected"] if e[1] == "explained" and (e[0], "explained") in c["tp"]),
        "abstention_cases_expected": len(needs),
        "abstention_cases_correct": sum(1 for c in needs if c["needs_human_correct"]),
        "unnecessary_abstentions": sum(1 for c in cases if c["unnecessary_abstention"]),
        "citation_validity": round(citations_all["checked"] /
                                   max(citations_all["checked"] + citations_all["failed"], 1), 4),
        "citations_checked": citations_all["checked"] + citations_all["failed"],
    }
    baseline = {
        "recall": round(base_tp / max(base_exp, 1), 4),
        "precision": round(base_tp / max(base_tp + base_fp, 1), 4),
        "false_positives": base_fp,
        "defects_missed": base_exp - base_tp,
    }
    det = {
        "digests_run1": [r.digest for r in records],
        "identical": [r.digest for r in records] == [r.digest for r in records_rerun],
        "policy_fingerprint": policy.fingerprint,
    }
    return EvalResult(cases=cases, citations=citations_all, by_family=dict(sorted(by_family.items())),
                      totals=totals, baseline=baseline, determinism=det,
                      runtime_seconds=round(runtime_seconds, 2),
                      policy={"name": policy.name, "version": policy.version,
                              "fingerprint": policy.fingerprint, "rules": len(policy.rules)},
                      corpus={"path": str(corpus), "cases": len(records)})


HIDDEN_FAMILIES = {"income_mismatch", "valuation_mismatch", "tamper",
                   "arithmetic_mismatch", "kyc_name_mismatch", "pdd_missing", "stale_bureau"}


def render_markdown(result: EvalResult) -> str:
    t, b = result.totals, result.baseline
    hidden = {k: v for k, v in result.by_family.items() if k in HIDDEN_FAMILIES}
    hidden_expected = sum(v["expected"] for v in hidden.values())
    hidden_detected = sum(v["detected"] for v in hidden.values())
    hidden_base = sum(min(v["baseline_detected"], v["expected"]) for v in hidden.values())

    lines = [
        "# Lekh — evaluation report",
        "",
        f"Policy **{result.policy['name']} v{result.policy['version']}** "
        f"(fingerprint `{result.policy['fingerprint']}`, {result.policy['rules']} rules)  ",
        f"Corpus: `{result.corpus['path']}` — {result.corpus['cases']} files, "
        f"synthetic with construction-based ground truth  ",
        f"Runtime: {result.runtime_seconds}s  ",
        f"Determinism: two independent runs produced "
        f"{'identical' if result.determinism['identical'] else 'DIFFERENT'} finding digests.",
        "",
        "## Headline",
        "",
        "| metric | lekh | memo-trusting baseline |",
        "|---|---|---|",
        f"| defect recall | **{t['recall']*100:.1f}%** ({t['defects_detected']}/{t['defects_expected']}) "
        f"| {b['recall']*100:.1f}% ({t['defects_expected']-b['defects_missed']}/{t['defects_expected']}) |",
        f"| precision | **{t['precision']*100:.1f}%** | {b['precision']*100:.1f}% |",
        f"| false positives | **{t['false_positives']}** | {b['false_positives']} |",
        f"| defects missed | **{t['defects_missed']}** | {b['defects_missed']} |",
        f"| citation validity | **{t['citation_validity']*100:.1f}%** "
        f"({t['citations_checked']} citations re-checked against the page) | n/a — cites nothing |",
        f"| exact case match | {t['exact_case_match']*100:.1f}% of {t['cases']} files | n/a |",
        "",
        f"Defects a memo-only reviewer structurally cannot see "
        f"({', '.join(sorted(hidden))}): **{hidden_detected}/{hidden_expected}** detected, "
        f"against **{hidden_base}/{hidden_expected}** for the baseline.",
        "",
        "## Where the gap is",
        "",
        "| defect family | expected | lekh detected | baseline detected |",
        "|---|---|---|---|",
    ]
    for fam, row in result.by_family.items():
        mark = " ✅" if row["recall"] == 1.0 else ""
        lines.append(f"| {fam}{mark} | {row['expected']} | {row['detected']} "
                     f"| {min(row['baseline_detected'], row['expected'])} |")
    lines += [
        "",
        "## Deviation handling (the false-positive engine)",
        "",
        f"- Breaches covered by a valid, unexpired L2 deviation, expected to be **explained**: "
        f"{t['explanations_expected']}",
        f"- Correctly filed as `explained` rather than flagged: **{t['explanations_credited']}**",
        f"- The baseline flags every one of them, because it does not read the deviation register.",
        "",
        "## Abstention discipline",
        "",
        f"- Files where the correct behaviour is to abstain (document missing): "
        f"{t['abstention_cases_expected']}",
        f"- Correctly abstained: **{t['abstention_cases_correct']}**",
        f"- Unnecessary abstentions on reviewable files: {t['unnecessary_abstentions']}",
        "",
        "## What this evaluation does not prove",
        "",
        "- The corpus is synthetic. It is faithful to the *shape* of Indian retail home-loan",
        "  files, not to any real bank's files. A real pilot runs on historical files the",
        "  team has already reviewed, which is the only ground truth that matters.",
        "- The oracle is construction-based: it knows the numbers because it wrote them. It",
        "  cannot catch a rule that is wrong in the same way in both places. Rule-level",
        "  confidence has to come from a real file sample.",
        "- Extraction assumes a digital, text-bearing PDF. Scanned files need OCR, and OCR",
        "  errors change the failure mode from 'wrong number' to 'no number', which this rig",
        "  has not measured.",
        "- One policy, one product, one lender archetype. Nothing here has been tested",
        "  against a co-lending file, a balance-transfer file, or a restructured account.",
        "",
        "## Citation failures",
        "",
    ]
    if result.citations["failures"]:
        for fail in result.citations["failures"]:
            lines.append(f"- `{fail['finding']}`: {fail['why']} — {fail.get('evidence')}")
    else:
        lines.append("None. Every quote resolved to the page it cited.")
    lines += ["", f"_Generated by `lekh eval`. Runtime {result.runtime_seconds}s._", ""]
    return "\n".join(lines)
