"""The review run: documents in, cited findings out, everything on the ledger.

A `CaseRecord` is what the console and the evals both read. It is deliberately
boring data: no live objects, no lazy properties, so a record can be written to
disk, replayed a year later, and diffed against the next run.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .extract import extract_case, verified_income, verified_obligations
from .ledger import Ledger
from .pdf import load_case
from .policy import Policy, load_policy
from .rules import CHECKS, Finding

DEFAULTS = Path(__file__).resolve().parents[1]


@dataclass
class CaseRecord:
    loan_id: str
    run_id: str
    policy_version: str
    policy_fingerprint: str
    findings: list[Finding]
    facts: dict
    documents: list[dict]
    digest: str = ""
    started_at: str = ""

    def __post_init__(self) -> None:
        if not self.digest:
            blob = json.dumps([f.id for f in self.findings], sort_keys=False)
            self.digest = hashlib.sha256(blob.encode()).hexdigest()[:16]

    @property
    def needs_human(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "needs_human"]

    @property
    def flagged(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "finding"]

    @property
    def explained(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "explained"]

    def to_dict(self) -> dict:
        return {
            "loan_id": self.loan_id, "run_id": self.run_id,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "started_at": self.started_at, "digest": self.digest,
            "findings": [f.to_dict() for f in self.findings],
            "facts": self.facts, "documents": self.documents,
            "summary": {"flagged": len(self.flagged), "explained": len(self.explained),
                        "needs_human": len(self.needs_human)},
        }


def _facts_summary(facts) -> dict:
    income, _ = verified_income(facts)
    oblig, _ = verified_obligations(facts)
    return {
        "borrower": facts.get("applicant"),
        "branch": facts.get("branch"),
        "sanction_date": str(facts.get("sanction_date")),
        "sanction_amount": facts.get("sanction_amount"),
        "appraisal_value": facts.get("appraisal_value"),
        "memo_valuation": facts.get("memo_valuation"),
        "income_stated": facts.get("income_memo"),
        "income_verified": income,
        "obligations_verified": oblig,
        "bureau_score": facts.get("bureau_score"),
        "dpd_max_12m": facts.get("dpd_max_12m"),
        "foir_stated": facts.get("foir_stated"),
        "ltv_stated": facts.get("ltv_stated"),
        "absent_fields": facts.absent,
        "missing_docs": facts.missing_docs,
        "tampered_docs": facts.tampered_docs,
        "deviations_on_file": [
            {k: (str(v) if isinstance(v, dt.date) else v) for k, v in d.items()}
            for d in facts.deviations
        ],
    }


def review_case(folder: str | Path, policy: Policy, run_id: str,
                ts: str | None = None, ledger: Ledger | None = None) -> CaseRecord:
    case = load_case(folder)
    facts = extract_case(case)
    findings: list[Finding] = []
    for check in CHECKS:
        try:
            findings.extend(check(facts, policy))
        except Exception as exc:  # a broken rule must never look like a pass
            findings.append(Finding(
                case_id=facts.loan_id, rule_id=getattr(check, "__name__", "unknown"),
                clause="engine", clause_page=0, family="rule_error", status="needs_human",
                severity="high",
                claim=f"Check failed to run: {check.__name__}: {exc}",
                derivation={"error": repr(exc)}))

    record = CaseRecord(
        loan_id=facts.loan_id, run_id=run_id, policy_version=policy.version,
        policy_fingerprint=policy.fingerprint, findings=findings,
        facts=_facts_summary(facts),
        documents=[{"name": d.name, "pages": d.page_count,
                    "sha256": d.sha256[:16],
                    "tampered": d.name in case.tampered}
                   for d in case.documents.values()],
        started_at=ts or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))

    if ledger is not None:
        stamp = record.started_at
        ledger.append("case_opened", {
            "loan_id": record.loan_id, "run_id": run_id,
            "policy": record.policy_version,
            "policy_fingerprint": record.policy_fingerprint,
            "documents": record.documents,
        }, stamp)
        for f in findings:
            ledger.append("finding_proposed",
                          {**f.to_dict(), "finding_id": f.id, "loan_id": record.loan_id},
                          stamp)
    return record


def review_corpus(corpus: str | Path, policy_path: str | Path, ledger_path: str | Path | None,
                  run_id: str) -> list[CaseRecord]:
    policy = load_policy(policy_path)
    ledger = Ledger(ledger_path) if ledger_path else Ledger()
    out: list[CaseRecord] = []
    for folder in sorted(Path(corpus).iterdir()):
        if folder.is_dir():
            out.append(review_case(folder, policy, run_id, ledger=ledger))
    if ledger_path:
        ledger.export(Path(ledger_path).with_suffix(".pack.json"))
    return out
