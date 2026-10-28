"""Field extraction with provenance.

Every extracted value carries the document, the page and the exact line it came
from. If a value cannot be found, the field is absent (None) and the rules that
need it abstain. There is no default, no zero, no interpolation: a missing
number is a missing number, and the file gets sent to a human.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .money import ParseError, parse_date, parse_money, parse_pct
from .pdf import CaseFile, Document


@dataclass
class Field:
    name: str
    value: Any
    doc: str
    page: int
    quote: str

    def evidence(self) -> dict:
        return {"doc": self.doc, "page": self.page, "quote": self.quote}


@dataclass
class Facts:
    loan_id: str
    fields: dict[str, Field] = field(default_factory=dict)
    salary_credits: list[Field] = field(default_factory=list)
    co_salary_credits: list[Field] = field(default_factory=list)
    obligations: list[Field] = field(default_factory=list)
    deviations: list[dict] = field(default_factory=list)
    unparsed_rows: list[Field] = field(default_factory=list)
    valuation_values: dict[str, float] = field(default_factory=dict)
    pdd: dict[str, str] = field(default_factory=dict)
    absent: list[str] = field(default_factory=list)
    missing_docs: list[str] = field(default_factory=list)
    unreadable_docs: list[str] = field(default_factory=list)
    tampered_docs: list[str] = field(default_factory=list)

    def get(self, name: str) -> Any:
        f = self.fields.get(name)
        return None if f is None else f.value

    def ev(self, name: str) -> dict | None:
        f = self.fields.get(name)
        return None if f is None else f.evidence()

    def require(self, *names: str) -> list[str]:
        return [n for n in names if n not in self.fields]


# ---------------------------------------------------------------------------- patterns
# Label variants differ by branch and by originating system, so each field
# accepts several. A pattern that fails here is a *visible* failure: the field
# goes absent and the dependent rule abstains.
_MONEY = r"(?P<v>(?:Rs\.?|INR|₹)?\s*[\d,]+(?:\.\d+)?\s*(?:crores?|lakhs?|lacs?|lakh|lac|l|k)?)(?:\s*/-)?"

PATTERNS: dict[str, list[str]] = {
    "loan_id": [r"^Loan ID\s*:\s*(?P<v>HL-[\dA-Z]+)"],
    "branch": [r"^Branch\s*:\s*(?P<v>[A-Za-z]+)"],
    "sanction_date": [r"^Sanction date\s*:\s*(?P<v>[\d]{1,2} \w{3} \d{4})"],
    "applicant": [r"^Applicant\s*:\s*(?P<v>[A-Za-z .]+)$"],
    "co_applicant": [r"^Co-applicant\s*:\s*(?P<v>[A-Za-z .]+)$"],
    "sanction_amount": [
        r"^Sanction amount\s*:\s*" + _MONEY,
        r"^Loan amount sanctioned\s*:\s*" + _MONEY,
        r"^Sanctioned amount\s*:\s*" + _MONEY,
    ],
    "tenure_months": [r"^Tenure\s*:\s*(?P<v>\d{2,3})\s*months"],
    "rate": [r"^Interest rate\s*:\s*(?P<v>\d{1,2}\.\d{1,2})\s*%\s*p\.a\."],
    "emi_stated": [
        r"^EMI at sanction\s*:\s*" + _MONEY,
        r"^Instalment \(PMT\)\s*:\s*" + _MONEY,
        r"^Monthly instalment\s*:\s*" + _MONEY,
    ],
    "purchase_price": [
        r"^Property purchase price\s*:\s*" + _MONEY,
        r"^Agreement value\s*:\s*" + _MONEY,
        r"^Consideration value\s*:\s*" + _MONEY,
    ],
    "memo_valuation": [
        r"^Appraised value \(technical\)\s*:\s*" + _MONEY,
        r"^Technical valuation\s*:\s*" + _MONEY,
        r"^Value as per valuation report\s*:\s*" + _MONEY,
    ],
    "income_memo": [
        r"^Net monthly income \(applicant\)\s*:\s*" + _MONEY,
        r"^Net take-home \(applicant\)\s*:\s*" + _MONEY,
        r"^NMI - applicant\s*:\s*" + _MONEY,
        r"^Net salary credit \(applicant\)\s*:\s*" + _MONEY,
    ],
    "co_income_memo": [r"^Net monthly income \(co-applicant\)\s*:\s*" + _MONEY],
    "obligations_memo": [
        r"^Existing monthly obligations\s*:\s*" + _MONEY,
        r"^Current EMI outgo\s*:\s*" + _MONEY,
        r"^Existing EMI commitments\s*:\s*" + _MONEY,
    ],
    "foir_stated": [r"^FOIR \(stated\)\s*:\s*(?P<v>\d{1,3}(?:\.\d)?)\s*%"],
    "ltv_stated": [r"^LTV \(stated\)\s*:\s*(?P<v>\d{1,3}(?:\.\d)?)\s*%\s*on\s*(?P<basis>.+)$"],
    "appraisal_value": [
        r"^Appraised value \(technical\)\s*:\s*" + _MONEY,
        r"^Technical valuation\s*:\s*" + _MONEY,
        r"^Value as per valuation report\s*:\s*" + _MONEY,
        r"^Market value\s*:\s*" + _MONEY,
    ],
    "bureau_score": [
        r"^Bureau score\s*:\s*(?P<v>\d{3})",
        r"^CIBIL score\s*:\s*(?P<v>\d{3})",
        r"^Commercial bureau score\s*:\s*(?P<v>\d{3})",
    ],
    "dpd_max_12m": [r"^DPD \(max, last 12 months\)\s*:\s*(?P<v>\d{1,3})"],
    "bureau_report_date": [r"^Report date\s*:\s*(?P<v>\d{1,2} \w{3} \d{4})"],
    "aadhaar_name": [r"^Aadhaar name\s*:\s*(?P<v>[A-Za-z .]+)$"],
    "pan_name": [r"^PAN name\s*:\s*(?P<v>[A-Za-z .]+)$"],
}

# which document each field should come from, and the parser to apply
FIELD_SPEC: dict[str, tuple[list[str], Callable[[str], Any]]] = {
    "loan_id": (["sanction_memo.pdf"], str),
    "branch": (["sanction_memo.pdf"], str),
    "sanction_date": (["sanction_memo.pdf"], parse_date),
    "applicant": (["sanction_memo.pdf"], str),
    "co_applicant": (["sanction_memo.pdf"], str),
    "sanction_amount": (["sanction_memo.pdf"], parse_money),
    "tenure_months": (["sanction_memo.pdf"], lambda s: int(s)),
    "rate": (["sanction_memo.pdf"], float),
    "emi_stated": (["sanction_memo.pdf"], parse_money),
    "purchase_price": (["sanction_memo.pdf"], parse_money),
    "memo_valuation": (["sanction_memo.pdf"], parse_money),
    "income_memo": (["sanction_memo.pdf"], parse_money),
    "co_income_memo": (["sanction_memo.pdf"], parse_money),
    "obligations_memo": (["sanction_memo.pdf"], parse_money),
    "foir_stated": (["sanction_memo.pdf"], lambda s: float(s) / 100.0),
    "ltv_stated": (["sanction_memo.pdf"], lambda s: float(s) / 100.0),
    "appraisal_value": (["appraisal_report.pdf"], parse_money),
    "bureau_score": (["bureau_report.pdf"], lambda s: int(s)),
    "dpd_max_12m": (["bureau_report.pdf"], lambda s: int(s)),
    "bureau_report_date": (["bureau_report.pdf"], parse_date),
    "aadhaar_name": (["kyc_annexure.pdf"], str),
    "pan_name": (["kyc_annexure.pdf"], str),
}


def _search(doc: Document, patterns: list[str]) -> Field | None:
    for page_no, page in enumerate(doc.pages, start=1):
        for line in page.splitlines():
            raw = line.strip()
            for pat in patterns:
                m = re.match(pat, raw, re.IGNORECASE)
                if not m:
                    continue
                return Field(name="", value=None, doc=doc.name, page=page_no,
                             quote=raw), m
    return None


def _extract_field(facts: Facts, name: str, docs: dict[str, Document]) -> None:
    doc_names, parser = FIELD_SPEC[name]
    for doc_name in doc_names:
        doc = docs.get(doc_name)
        if doc is None:
            continue
        found = _search(doc, PATTERNS[name])
        if not found:
            continue
        holder, m = found
        raw_value = m.group("v").strip()
        value = parser(raw_value)
        # basis of the LTV computation is part of the claim, not decoration
        if name == "ltv_stated" and "basis" in m.groupdict():
            basis = m.group("basis").strip()
            facts.fields["ltv_basis"] = Field("ltv_basis", basis, doc.name,
                                              holder.page, holder.quote)
        facts.fields[name] = Field(name, value, doc.name, holder.page, holder.quote)
        return
    facts.absent.append(name)


# ---------------------------------------------------------------------------- tables
_SALARY_RE = re.compile(
    r"^(?P<d>\d{2}/\d{2}/\d{4})\s+SALARY CREDIT.*?(?P<v>[\d,]{5,})\s+(?P<bal>[\d,]{3,})\s*$",
    re.IGNORECASE)
_OBLIG_RE = re.compile(
    r"^(?P<d>\d{2}/\d{2}/\d{4})\s+ACH DEBIT - LOAN EMI\s+(?P<v>[\d,]{1,})\s*$")
_TXN_ROW_RE = re.compile(r"^\d{2}/\d{2}/\d{4}\b")
# Characters an OCR pass confuses with digits. A "1,O9,700" is not Rs. 9,700.
_OCR_AMBIG = re.compile(r"\d[OoIlSs](?=[,,\d])|[OoIlSs](?=[,.]?\d)")
_STMT_AVG_RE = re.compile(r"^Average monthly salary credit over period\s*:\s*Rs\.\s*(?P<v>[\d,]+)/-")
_DEV_RE = re.compile(
    r"^(?P<id>D-\d+)\s+(?P<loan>HL-\d+)\s+(?P<clause>FOIR cap|LTV cap|Documentation)\s+"
    r"(?P<by>L[12] - [A-Za-z ]+?)\s+(?P<till>\d{2} \w{3} \d{4})\s+(?P<status>\w+)$")
_PDD_RE = re.compile(r"^\s*(?P<item>[A-Za-z \-\(\)0-9]+?)\s*:\s*(?P<status>received|MISSING)$")


def _extract_statement(facts: Facts, doc: Document, bucket: str = "salary") -> None:
    for page_no, page in enumerate(doc.pages, start=1):
        for line in page.splitlines():
            raw = line.strip()
            is_txn_row = bool(_TXN_ROW_RE.match(raw))
            if is_txn_row and _OCR_AMBIG.search(raw):
                # A digit was read as a letter (or the other way round). The row is
                # carried forward as a gap: a partially-matched "1,O9,700" would
                # parse as Rs. 9,700 and poison every ratio built on it.
                facts.unparsed_rows.append(Field("row_ambiguous", None, doc.name,
                                                 page_no, raw))
                continue
            m = _SALARY_RE.match(raw)
            if m is None and is_txn_row and "SALARY" in raw.upper():
                facts.unparsed_rows.append(Field("salary_unparsed", None, doc.name,
                                                 page_no, raw))
                continue
            if m:
                target = facts.salary_credits if bucket == "salary" else facts.co_salary_credits
                target.append(Field("salary_credit", parse_money(m.group("v")),
                                    doc.name, page_no, raw))
                continue
            m = _OBLIG_RE.match(raw)
            if m:
                facts.obligations.append(
                    Field("obligation", parse_money(m.group("v")), doc.name, page_no, raw))
                continue
            m = _STMT_AVG_RE.match(raw)
            if m:
                facts.fields["statement_avg_stated"] = Field(
                    "statement_avg_stated", parse_money(m.group("v")), doc.name, page_no, raw)


def _extract_deviations(facts: Facts, doc: Document) -> None:
    for page_no, page in enumerate(doc.pages, start=1):
        for line in page.splitlines():
            raw = line.strip()
            m = _DEV_RE.match(raw)
            if not m:
                continue
            facts.deviations.append({
                "deviation_id": m.group("id"),
                "loan_id": m.group("loan"),
                "clause": m.group("clause").strip(),
                "approved_by": m.group("by").strip(),
                "valid_till": parse_date(m.group("till")),
                "status": m.group("status"),
                "doc": doc.name,
                "page": page_no,
                "quote": raw,
            })


def _extract_pdd(facts: Facts, doc: Document) -> None:
    for page_no, page in enumerate(doc.pages, start=1):
        for line in page.splitlines():
            m = _PDD_RE.match(line)
            if m and m.group("item").strip().lower() not in ("aadhaar name", "pan name"):
                facts.pdd[m.group("item").strip()] = m.group("status")


def extract_case(case: CaseFile) -> Facts:
    facts = Facts(loan_id=case.loan_id)
    facts.missing_docs = list(case.missing)
    facts.tampered_docs = list(case.tampered)
    for name in FIELD_SPEC:
        _extract_field(facts, name, case.documents)
    stmt = case.get("bank_statement.pdf")
    if stmt:
        _extract_statement(facts, stmt)
    co_stmt = case.get("co_applicant_statement.pdf")
    if co_stmt:
        _extract_statement(facts, co_stmt, bucket="co")
    dev = case.get("deviation_register.pdf")
    if dev:
        _extract_deviations(facts, dev)
    facts.unreadable_docs = [
        name for name, doc in case.documents.items()
        if len("".join(doc.pages).strip()) < 40 and name != "valuation_revised.pdf"
    ]
    kyc = case.get("kyc_annexure.pdf")
    if kyc:
        _extract_pdd(facts, kyc)
    # any *additional* valuation document in the file, e.g. a revised opinion
    for name, doc in case.documents.items():
        if name in ("appraisal_report.pdf", "sanction_memo.pdf"):
            continue
        if not ("valuation" in name or "appraisal" in name):
            continue
        for page_no, page in enumerate(doc.pages, start=1):
            for line in page.splitlines():
                for pat in PATTERNS["appraisal_value"]:
                    m = re.match(pat, line.strip(), re.IGNORECASE)
                    if m:
                        facts.valuation_values[name] = parse_money(m.group("v"))
    return facts


def verified_income(facts: Facts) -> tuple[float | None, list[dict]]:
    """Mean of the salary credits evidenced on the statement, with evidence.

    Uses the *transactions*, never the statement's own summary line, because a
    summary is a claim and a transaction is a record.
    """
    if not facts.salary_credits:
        return None, []
    amounts = [f.value for f in facts.salary_credits]
    return round(sum(amounts) / len(amounts), 2), [f.evidence() for f in facts.salary_credits]


def co_verified_income(facts: Facts) -> tuple[float | None, list[dict]]:
    """Co-applicant income, counted only because a statement evidences it."""
    if not facts.co_salary_credits:
        return None, []
    amounts = [f.value for f in facts.co_salary_credits]
    return round(sum(amounts) / len(amounts), 2), [f.evidence() for f in facts.co_salary_credits]


def verified_obligations(facts: Facts) -> tuple[float, list[dict]]:
    if not facts.obligations:
        return 0.0, []
    return round(sum(f.value for f in facts.obligations), 2), [f.evidence() for f in facts.obligations]
