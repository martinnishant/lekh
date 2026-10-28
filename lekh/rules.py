"""The checks. Deterministic, pure, and answerable to one clause each.

Design rules this file follows, because the domain demands them:

  * Numbers are recomputed from source documents, never taken from the memo.
    The memo is a claim; the statement and the valuation report are records.
  * Every finding is either `finding`, `explained` (a breach covered by a valid
    and unexpired approval), or `needs_human` (we could not verify it). There is
    no fourth state called "looks fine".
  * A rule that cannot see its inputs abstains. Abstention is a first-class
    outcome with its own metric, not an inconvenient branch.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .extract import Facts, co_verified_income, verified_income, verified_obligations
from .policy import Policy

FOIR_TOLERANCE = 0.01
LTV_TOLERANCE = 0.01
EMI_TOLERANCE = 100.0
INCOME_TOLERANCE = 0.10
VALUATION_TOLERANCE = 0.02
SUMMARY_TOLERANCE = 0.02
BUREAU_MAX_AGE_DAYS = 30


@dataclass
class Finding:
    case_id: str
    rule_id: str
    clause: str
    clause_page: int
    family: str
    status: str                       # finding | explained | needs_human
    severity: str
    claim: str
    detail: str = ""
    derivation: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    deviation_rejected: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        blob = json.dumps({"c": self.case_id, "r": self.rule_id, "f": self.family,
                           "s": self.status, "claim": self.claim}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return _jsonable({
            "id": self.id, "case_id": self.case_id, "rule_id": self.rule_id,
            "clause": self.clause, "clause_page": self.clause_page,
            "family": self.family, "status": self.status, "severity": self.severity,
            "claim": self.claim, "detail": self.detail, "derivation": self.derivation,
            "evidence": self.evidence, "deviation_rejected": self.deviation_rejected,
            "notes": self.notes,
        })


def _jsonable(obj):
    """Dates and enums out, plain JSON in — the ledger stores this verbatim."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    return obj


def _rule(policy: Policy, rule_id: str) -> tuple[str, int, str]:
    r = policy.rule(rule_id)
    return r.clause, r.page, r.severity


# ---------------------------------------------------------------------------- math
def emi(principal: float, rate: float, months: int) -> float:
    r = rate / 1200.0
    if r <= 0:
        return principal / months
    return principal * r * (1 + r) ** months / ((1 + r) ** months - 1)


def ltv_cap_for(loan: float, slabs: list[dict]) -> float:
    for slab in slabs:
        if loan <= slab["up_to"]:
            return slab["cap"]
    return slabs[-1]["cap"]


# ---------------------------------------------------------------------------- rules
def check_presence(facts: Facts, policy: Policy) -> list[Finding]:
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-01")
    if facts.missing_docs:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-01", clause=clause, clause_page=page,
            family="missing_document", status="needs_human", severity="high",
            claim=f"File incomplete: {', '.join(facts.missing_docs)} not present in the credit file",
            detail=("Every check that depends on a missing document is withheld rather than "
                    "passed. The file needs the document before it can be reviewed."),
            derivation={"missing": facts.missing_docs, "size": 1}))
    return out


def check_tamper(facts: Facts, policy: Policy) -> list[Finding]:
    """Two independent detectors, one finding.

    (a) the document's hash no longer matches the intake manifest, and
    (b) the statement's own summary disagrees with the transactions printed on it.

    Either is enough to block a review: a file whose numbers were changed after
    intake cannot be signed off on those numbers. Reporting it twice would be
    noise, so the detectors are merged into one finding that names both.
    """
    clause, page, severity = _rule(policy, "R-11")
    detectors, evidence, details = [], [], []

    if facts.tampered_docs:
        detectors.append("hash")
        details.append(f"hash does not match the intake manifest for "
                       f"{', '.join(facts.tampered_docs)}")
        for name in facts.tampered_docs:
            evidence.append({"doc": name, "page": 1, "kind": "system_record",
                             "quote": f"sha256 for {name} differs from _manifest.json"})

    stated = facts.get("statement_avg_stated")
    income, ev = verified_income(facts)
    if stated and income:
        gap = abs(stated - income) / income
        if gap > SUMMARY_TOLERANCE:
            detectors.append("internal_consistency")
            details.append(f"statement summary says Rs. {stated:,.0f}, the credits printed on the "
                           f"same statement average Rs. {income:,.0f} ({gap*100:.0f}% apart)")
            evidence.extend(ev[:2])
            if facts.ev("statement_avg_stated"):
                evidence.append(facts.ev("statement_avg_stated"))

    if not detectors:
        return []
    return [Finding(
        case_id=facts.loan_id, rule_id="R-11", clause=clause, clause_page=page,
        family="tamper", status="finding", severity=severity,
        claim="Document integrity failure: " + "; ".join(details),
        detail=("The file changed after intake, or the statement does not agree with its own "
                "transactions. Review is blocked on this document until the discrepancy is "
                "explained by a named person."),
        derivation={"detectors": detectors,
                    "documents": facts.tampered_docs,
                    "stated_summary": stated,
                    "recomputed_from_transactions": income},
        evidence=evidence)]


def check_bureau(facts: Facts, policy: Policy) -> list[Finding]:
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-02")
    score = facts.get("bureau_score")
    floor = policy.rule("R-02").params["floor"]
    if score is None:
        return out
    if score < floor:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-02", clause=clause, clause_page=page,
            family="bureau_low", status="finding", severity=severity,
            claim=f"Bureau score {score} is below the policy floor of {floor}",
            detail=f"The report on file scores {score}. Policy requires {floor} or better at sanction.",
            derivation={"score": score, "floor": floor, "shortfall": floor - score},
            evidence=[facts.ev("bureau_score")]))
    return out


def check_dpd(facts: Facts, policy: Policy) -> list[Finding]:
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-03")
    dpd = facts.get("dpd_max_12m")
    limit = policy.rule("R-03").params["max_dpd"]
    if dpd is None:
        return out
    if dpd >= limit:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-03", clause=clause, clause_page=page,
            family="dpd_delinquency", status="finding", severity=severity,
            claim=f"Delinquency on file: {dpd} days past due in the last 12 months",
            detail=f"Policy permits no account with {limit}+ DPD in the trailing twelve months.",
            derivation={"dpd": dpd, "limit": limit},
            evidence=[facts.ev("dpd_max_12m")]))
    return out


def check_bureau_age(facts: Facts, policy: Policy) -> list[Finding]:
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-04")
    report_date = facts.get("bureau_report_date")
    sanction_date = facts.get("sanction_date")
    if not (report_date and sanction_date):
        return out
    age = (sanction_date - report_date).days
    if age > BUREAU_MAX_AGE_DAYS:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-04", clause=clause, clause_page=page,
            family="stale_bureau", status="finding", severity=severity,
            claim=(f"Bureau report was {age} days old at sanction "
                   f"(report {report_date:%d %b %Y}, sanctioned {sanction_date:%d %b %Y})"),
            detail=f"Policy requires a report no older than {BUREAU_MAX_AGE_DAYS} days at sanction.",
            derivation={"report_date": str(report_date), "sanction_date": str(sanction_date),
                        "age_days": age, "limit_days": BUREAU_MAX_AGE_DAYS},
            evidence=[facts.ev("bureau_report_date"), facts.ev("sanction_date")]))
    return out


def _resolve_deviation(facts: Facts, clause_name: str, sanction_date: dt.date) -> tuple[dict | None, list[dict]]:
    """Return (valid deviation, rejected candidates with reasons)."""
    valid, rejected = None, []
    for d in facts.deviations:
        if d["clause"] != clause_name:
            continue
        reasons = []
        if d["loan_id"] != facts.loan_id:
            reasons.append(f"registered against {d['loan_id']}, not this file")
        if d["status"].lower() != "approved":
            reasons.append(f"status is {d['status']}")
        if not d["approved_by"].startswith("L2"):
            reasons.append(f"signed at {d['approved_by'].split(' - ')[0]}, policy needs L2")
        if d["valid_till"] < sanction_date:
            reasons.append(f"lapsed on {d['valid_till']:%d %b %Y}, before sanction")
        if reasons:
            rejected.append({**d, "reasons": reasons})
        else:
            valid = d
    return valid, rejected


def _dev_note(facts: Facts, clause_name: str, sanction_date: dt.date) -> tuple[dict | None, list[dict]]:
    if not sanction_date:
        return None, []
    return _resolve_deviation(facts, clause_name, sanction_date)


def check_foir(facts: Facts, policy: Policy) -> list[Finding]:
    """FOIR on verified income and contractual EMI, with the deviation gate."""
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-05")
    spec = policy.rule("R-05").params
    cap = spec["cap"]

    if "bank_statement.pdf" in facts.missing_docs:
        return out          # R-01 already recorded the file-level abstention
    if facts.unparsed_rows:
        return out          # R-13 already withheld the numbers
    loan = facts.get("sanction_amount")
    rate = facts.get("rate")
    tenure = facts.get("tenure_months")
    income, income_ev = verified_income(facts)
    oblig, oblig_ev = verified_obligations(facts)
    if loan is None or rate is None or tenure is None:
        return out
    if income is None:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-05", clause=clause, clause_page=page,
            family="foir_breach", status="needs_human", severity="high",
            claim="FOIR cannot be verified: no salary credits evidenced on a statement",
            detail=("The FOIR check needs verified income. Without a statement in the file, "
                    "the ratio cannot be computed and is not assumed to pass."),
            derivation={"income_verified": None}))
        return out

    instal = emi(loan, rate, tenure)
    co_income, co_ev = co_verified_income(facts)
    notes = []
    co_stated = facts.get("co_income_memo")
    if co_income:
        income = income + co_income
        notes.append(f"Co-applicant income of Rs. {co_income:,.0f} is included because a "
                     f"statement in the file evidences it (policy 5.5).")
    elif co_stated:
        notes.append(f"Co-applicant income of Rs. {co_stated:,.0f} is stated but not evidenced "
                     f"by a statement in the file, so it is excluded from the ratio.")
    foir = (instal + oblig) / income

    if foir > cap + 1e-9:
        valid, rejected = _dev_note(facts, "FOIR cap", facts.get("sanction_date"))
        ev = [e for e in income_ev[:2] + oblig_ev[:1] + [facts.ev("sanction_amount"),
              facts.ev("emi_stated")] if e]
        if valid:
            out.append(Finding(
                case_id=facts.loan_id, rule_id="R-05", clause=clause, clause_page=page,
                family="foir_breach", status="explained", severity=severity,
                claim=(f"FOIR {foir*100:.1f}% exceeds the {cap*100:.0f}% cap, covered by "
                       f"deviation {valid['deviation_id']}"),
                detail=(f"Contractual EMI Rs. {instal:,.0f} + existing obligations "
                        f"Rs. {oblig:,.0f} against verified income Rs. {income:,.0f}. "
                        f"{valid['approved_by']} approved {valid['clause']} deviation "
                        f"{valid['deviation_id']} valid to {valid['valid_till']:%d %b %Y}."),
                derivation={"foir": round(foir, 4), "cap": cap, "emi_contractual": round(instal, 2),
                            "obligations_verified": oblig, "income_verified": income,
                            "co_applicant_income": co_income,
                            "deviation": valid, "deviation_rejected": rejected},
                evidence=ev + co_ev[:1] + [{"doc": valid["doc"], "page": valid["page"],
                                            "quote": valid["quote"]}],
                notes=notes))
        else:
            out.append(Finding(
                case_id=facts.loan_id, rule_id="R-05", clause=clause, clause_page=page,
                family="foir_breach", status="finding", severity=severity,
                claim=f"FOIR {foir*100:.1f}% breaches the {cap*100:.0f}% cap with no valid approval",
                detail=("; ".join(f"{d['deviation_id']}: {', '.join(d['reasons'])}"
                                  for d in rejected) or
                        "No deviation approval on the file covers this breach.")
                       + f" Contractual EMI Rs. {instal:,.0f} + obligations Rs. {oblig:,.0f} "
                         f"against verified income Rs. {income:,.0f}.",
                derivation={"foir": round(foir, 4), "cap": cap, "emi_contractual": round(instal, 2),
                            "obligations_verified": oblig, "income_verified": income,
                            "co_applicant_income": co_income,
                            "deviation_rejected": rejected},
                evidence=ev + co_ev[:1], deviation_rejected=bool(rejected), notes=notes))
    return out


def check_ltv(facts: Facts, policy: Policy) -> list[Finding]:
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-06")
    slabs = policy.rule("R-06").params["slabs"]
    if "appraisal_report.pdf" in facts.missing_docs:
        return out
    loan = facts.get("sanction_amount")
    value = facts.get("appraisal_value")
    if loan is None:
        return out
    if value is None:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-06", clause=clause, clause_page=page,
            family="ltv_breach", status="needs_human", severity="high",
            claim="LTV cannot be verified: no valuation report in the file",
            detail="The cap is applied to the valuation report value, which is absent.",
            derivation={"ltv": None}))
        return out
    cap = ltv_cap_for(loan, slabs)
    ltv = loan / value
    if ltv > cap + 1e-9:
        valid, rejected = _dev_note(facts, "LTV cap", facts.get("sanction_date"))
        ev = [facts.ev("sanction_amount"), facts.ev("appraisal_value")]
        if valid:
            out.append(Finding(
                case_id=facts.loan_id, rule_id="R-06", clause=clause, clause_page=page,
                family="ltv_breach", status="explained", severity=severity,
                claim=f"LTV {ltv*100:.1f}% exceeds the {cap*100:.0f}% slab cap, covered by {valid['deviation_id']}",
                detail=(f"Loan Rs. {loan:,.0f} on a report value of Rs. {value:,.0f}. "
                        f"Deviation {valid['deviation_id']} approved by {valid['approved_by']} "
                        f"is valid to {valid['valid_till']:%d %b %Y}."),
                derivation={"ltv": round(ltv, 4), "cap": cap, "loan": loan, "value": value,
                            "deviation": valid},
                evidence=ev + [{"doc": valid["doc"], "page": valid["page"], "quote": valid["quote"]}]))
        else:
            out.append(Finding(
                case_id=facts.loan_id, rule_id="R-06", clause=clause, clause_page=page,
                family="ltv_breach", status="finding", severity=severity,
                claim=f"LTV {ltv*100:.1f}% breaches the {cap*100:.0f}% slab cap for this ticket size",
                detail=(f"Loan Rs. {loan:,.0f} on a report value of Rs. {value:,.0f}. "
                        + ("; ".join(f"{d['deviation_id']}: {', '.join(d['reasons'])}"
                                     for d in rejected) or "No deviation on file.")),
                derivation={"ltv": round(ltv, 4), "cap": cap, "loan": loan, "value": value,
                            "deviation_rejected": rejected},
                evidence=ev, deviation_rejected=bool(rejected)))
    return out


def check_income(facts: Facts, policy: Policy) -> list[Finding]:
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-07")
    if "bank_statement.pdf" in facts.missing_docs:
        return out
    memo = facts.get("income_memo")
    income, ev = verified_income(facts)
    if memo is None and income is not None:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-07", clause=clause, clause_page=page,
            family="income_mismatch", status="needs_human", severity=severity,
            claim="The memorandum's income line could not be located, so it cannot be reconciled",
            detail=("The statement gives a verified income, but the figure the memorandum "
                    "actually relied on was not found under any label this reviewer reads. "
                    "Label drift between branches is a real cause and a person should look."),
            derivation={"income_verified": income, "memo_income": None},
            evidence=ev[:2]))
        return out
    if memo is None or income is None:
        return out
    gap = (memo - income) / income
    if abs(gap) > INCOME_TOLERANCE:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-07", clause=clause, clause_page=page,
            family="income_mismatch", status="finding", severity=severity,
            claim=(f"Stated income Rs. {memo:,.0f} against verified Rs. {income:,.0f} "
                   f"({gap*100:+.1f}%)"),
            detail=("The memorandum's income line does not reconcile to the salary credits on the "
                    "statement. The verified figure is the one the ratio was tested on."),
            derivation={"income_stated": memo, "income_verified": income, "gap": round(gap, 4),
                        "tolerance": INCOME_TOLERANCE},
            evidence=[facts.ev("income_memo")] + ev[:2]))
    return out


def check_valuation(facts: Facts, policy: Policy) -> list[Finding]:
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-08")
    memo = facts.get("memo_valuation")
    report = facts.get("appraisal_value")
    if memo is None or report is None:
        return out
    gap = (memo - report) / report
    if abs(gap) > VALUATION_TOLERANCE:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-08", clause=clause, clause_page=page,
            family="valuation_mismatch", status="finding", severity=severity,
            claim=(f"Memo carries Rs. {memo:,.0f} as value; the valuation report says "
                   f"Rs. {report:,.0f} ({gap*100:+.1f}%)"),
            detail=("The LTV stated in the memorandum is computed on a value the valuer did not "
                    "give. Recomputed on the report, the ratio is different."),
            derivation={"memo_valuation": memo, "report_valuation": report, "gap": round(gap, 4),
                        "tolerance": VALUATION_TOLERANCE,
                        "ltv_on_memo": round(facts.get("sanction_amount") / memo, 4),
                        "ltv_on_report": round(facts.get("sanction_amount") / report, 4)},
            evidence=[facts.ev("memo_valuation"), facts.ev("appraisal_value")]))
    return out


def check_arithmetic(facts: Facts, policy: Policy) -> list[Finding]:
    """The memo's own arithmetic, recomputed. Cheap, and it finds real files."""
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-09")
    loan, rate, tenure = facts.get("sanction_amount"), facts.get("rate"), facts.get("tenure_months")
    if not (loan and rate and tenure):
        return out
    problems, deriv = [], {}
    true_emi = emi(loan, rate, tenure)
    stated_emi = facts.get("emi_stated")
    if stated_emi and abs(stated_emi - true_emi) > EMI_TOLERANCE:
        problems.append(f"EMI stated Rs. {stated_emi:,.0f}, amortisation gives Rs. {true_emi:,.0f}")
        deriv["emi_stated"] = stated_emi
        deriv["emi_recomputed"] = round(true_emi, 2)

    income_memo, oblig_memo = facts.get("income_memo"), facts.get("obligations_memo")
    stated_foir = facts.get("foir_stated")
    if income_memo and stated_foir is not None:
        foir_memo = (true_emi + (oblig_memo or 0)) / income_memo
        if abs(foir_memo - stated_foir) > FOIR_TOLERANCE:
            problems.append(f"FOIR stated {stated_foir*100:.1f}%, memo's own inputs give "
                            f"{foir_memo*100:.1f}%")
            deriv["foir_stated"] = stated_foir
            deriv["foir_recomputed"] = round(foir_memo, 4)

    stated_ltv, memo_val = facts.get("ltv_stated"), facts.get("memo_valuation")
    if stated_ltv is not None and memo_val:
        ltv_memo = loan / memo_val
        if abs(ltv_memo - stated_ltv) > LTV_TOLERANCE:
            problems.append(f"LTV stated {stated_ltv*100:.1f}%, loan over memo value gives "
                            f"{ltv_memo*100:.1f}%")
            deriv["ltv_stated"] = stated_ltv
            deriv["ltv_recomputed"] = round(ltv_memo, 4)

    if problems:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-09", clause=clause, clause_page=page,
            family="arithmetic_mismatch", status="finding", severity=severity,
            claim="The memorandum's own ratios do not reproduce from its own inputs",
            detail="; ".join(problems),
            derivation=deriv,
            evidence=[facts.ev("emi_stated"), facts.ev("foir_stated"), facts.ev("ltv_stated")]))
    return out


def _tokens(name: str) -> list[str]:
    return [t.lower() for t in name.replace(".", " ").split() if len(t) > 1]


def check_kyc(facts: Facts, policy: Policy) -> list[Finding]:
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-10")
    aadhaar, pan, memo = facts.get("aadhaar_name"), facts.get("pan_name"), facts.get("applicant")
    if not (aadhaar and pan):
        return out
    ta, tp = set(_tokens(aadhaar)), set(_tokens(pan))
    tm = set(_tokens(memo)) if memo else set()
    surname_a, surname_p = (_tokens(aadhaar) or [""])[-1], (_tokens(pan) or [""])[-1]
    differing = (ta ^ tp)
    if surname_a != surname_p or len(differing) >= 4:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-10", clause=clause, clause_page=page,
            family="kyc_name_mismatch", status="finding", severity=severity,
            claim=f"Name on PAN ({pan}) does not match the name on Aadhaar ({aadhaar})",
            detail=("Identity documents in the file disagree. A name change is acceptable only "
                    "with the supporting instrument on record; none is in the file."),
            derivation={"aadhaar": aadhaar, "pan": pan, "memo": memo,
                        "differing_tokens": sorted(differing)},
            evidence=[facts.ev("aadhaar_name"), facts.ev("pan_name")]))
        return out
    if tm and (tm ^ ta):
        # memorandum name drift alone is a low-severity documentation finding
        pass
    return out


def check_pdd(facts: Facts, policy: Policy) -> list[Finding]:
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-12")
    missing = [k for k, v in facts.pdd.items() if str(v).upper() == "MISSING"]
    if not facts.pdd:
        return out
    if missing:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-12", clause=clause, clause_page=page,
            family="pdd_missing", status="finding", severity=severity,
            claim=f"{len(missing)} post-disbursement document(s) not on file: {', '.join(missing)}",
            detail="Disbursement condition not satisfied by the documents in the credit file.",
            derivation={"missing": missing},
            evidence=[{"doc": "kyc_annexure.pdf", "page": 1,
                       "quote": f"{m} : MISSING"} for m in missing]))
    return out


def check_extraction_integrity(facts: Facts, policy: Policy) -> list[Finding]:
    """A row that would not parse is a gap, not a zero.

    This is the cheapest guard in the whole system and the one that matters most:
    extraction that silently drops what it cannot read produces a confident,
    wrong review. One unparsed salary credit is enough to withhold the ratio.
    """
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-13")
    if facts.unparsed_rows:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-13", clause=clause, clause_page=page,
            family="extraction_gap", status="needs_human", severity="high",
            claim=f"{len(facts.unparsed_rows)} transaction row(s) could not be parsed with confidence",
            detail=("The statement contains rows that look like credits but did not parse. "
                    "Income and every ratio built on it are withheld until a person reads "
                    "the statement, because dropping the row would change the answer."),
            derivation={"rows": len(facts.unparsed_rows),
                        "sample": facts.unparsed_rows[0].quote},
            evidence=[f.evidence() for f in facts.unparsed_rows[:3]]))
    return out


def check_document_text(facts: Facts, policy: Policy) -> list[Finding]:
    """A document that yields no machine-readable text is unread, not clean.

    Indian credit files are full of scanned pages. An extractor that returns
    nothing must not look like a document that had nothing wrong with it.
    """
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-15")
    if facts.unreadable_docs:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-15", clause=clause, clause_page=page,
            family="unreadable_document", status="needs_human", severity="high",
            claim=f"No machine-readable text in: {', '.join(facts.unreadable_docs)}",
            detail=("The document is on file but produced no text, which means it was scanned "
                    "or printed to image. It has not been read. OCR is not part of this build, "
                    "so the file waits for a person rather than passing by default."),
            derivation={"documents": facts.unreadable_docs},
            evidence=[{"doc": n, "page": 1, "kind": "system_record",
                       "quote": f"{n}: 0 characters of extractable text"} for n in facts.unreadable_docs]))
    return out


def check_valuation_conflict(facts: Facts, policy: Policy) -> list[Finding]:
    """Two valuations in one file is not a number to average; it is a question."""
    out: list[Finding] = []
    clause, page, severity = _rule(policy, "R-14")
    report = facts.get("appraisal_value")
    conflicts = {k: v for k, v in facts.valuation_values.items()
                 if report and abs(v - report) / report > VALUATION_TOLERANCE}
    if conflicts:
        out.append(Finding(
            case_id=facts.loan_id, rule_id="R-14", clause=clause, clause_page=page,
            family="valuation_conflict", status="needs_human", severity="high",
            claim=("File carries two valuations: report Rs. "
                   f"{report:,.0f} and " + ", ".join(f"{k} Rs. {v:,.0f}"
                                                     for k, v in conflicts.items())),
            detail=("LTV depends on which valuation is adopted. The system does not choose; "
                    "a named person decides which valuation governs, and the choice is logged."),
            derivation={"report_value": report, "other_values": conflicts},
            evidence=[facts.ev("appraisal_value")]))
    return out


CHECKS = [check_presence, check_tamper, check_extraction_integrity,
          check_document_text, check_valuation_conflict, check_bureau, check_dpd, check_bureau_age,
          check_foir, check_ltv, check_income, check_valuation, check_arithmetic,
          check_kyc, check_pdd]
