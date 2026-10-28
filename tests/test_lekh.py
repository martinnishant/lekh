"""Tests. They cover the things that would make the system quietly wrong.

Not "does it run" — "does it refuse to lie". Each test names a failure mode in
the domain, so a regression is visible as a lost promise rather than a red line
someone mutes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lekh.engine import review_case
from lekh.extract import Facts, Field
from lekh.ledger import Ledger
from lekh.memo import draft_finding_template, numeric_fidelity
from lekh.money import ParseError, inr, parse_date, parse_money, parse_pct
from lekh.policy import load_policy, verify_citations
from lekh.pdf import read_pdf_pages
from lekh.rules import Finding, check_foir, check_kyc, emi, ltv_cap_for

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policy" / "retail_home_loan_v3.2.yaml"
CORPUS = ROOT / "data" / "corpus"


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize("text,expected", [
    ("Rs. 52,00,000/-", 5_200_000),
    ("1.40 L", 140_000),
    ("1.4 lakh", 140_000),
    ("₹1,09,700", 109_700),
    ("INR 2.5 Cr", 25_000_000),
    ("45000", 45_000),
])
def test_money_formats_are_the_same_number(text, expected):
    assert parse_money(text) == expected


def test_money_refuses_garbage_instead_of_guessing():
    with pytest.raises(ParseError):
        parse_money("as discussed")


def test_indian_grouping():
    assert inr(5_200_000) == "52,00,000"
    assert inr(1_09_700) == "1,09,700"
    assert inr(999) == "999"


def test_pct_and_dates():
    assert parse_pct("62%") == 0.62
    assert str(parse_date("12 May 2026")) == "2026-05-12"
    assert str(parse_date("12/05/2026")) == "2026-05-12"


# ------------------------------------------------------------------ policy
def test_every_rule_cites_a_page_that_actually_says_it():
    policy = load_policy(POLICY)
    pages = read_pdf_pages(ROOT / "policy" / "retail_home_loan_v3.2.pdf")
    assert verify_citations(policy, pages) == []


def test_a_rule_whose_citation_drifted_fails_loudly():
    policy = load_policy(POLICY)
    pages = ["nothing relevant here"] * 6
    problems = verify_citations(policy, pages)
    assert len(problems) == len(policy.rules)


def test_policy_fingerprint_changes_when_a_rule_changes():
    policy = load_policy(POLICY)
    before = policy.fingerprint
    policy.rules[0].__dict__["quote"] = "a different clause entirely"
    assert policy.fingerprint != before


# ------------------------------------------------------------------ math
def test_emi_matches_amortisation():
    # Rs 50 lakh, 8.75% p.a., 240 months -> about Rs 44,200 a month
    assert 43_000 < emi(5_000_000, 8.75, 240) < 45_000


def test_ltv_slab_boundaries():
    slabs = [{"up_to": 3_000_000, "cap": 0.90},
             {"up_to": 7_500_000, "cap": 0.80},
             {"up_to": 10 ** 12, "cap": 0.75}]
    assert ltv_cap_for(2_900_000, slabs) == 0.90
    assert ltv_cap_for(3_000_000, slabs) == 0.90
    assert ltv_cap_for(3_000_001, slabs) == 0.80
    assert ltv_cap_for(9_000_000, slabs) == 0.75


# ------------------------------------------------------------------ behaviour
def _facts(**kw) -> Facts:
    f = Facts(loan_id="HL-TEST")
    for k, v in kw.items():
        f.fields[k] = Field(k, v, "test.pdf", 1, f"{k}: {v}")
    return f


def test_foir_abstains_when_no_income_is_evidenced():
    policy = load_policy(POLICY)
    facts = _facts(sanction_amount=5_000_000, rate=8.75, tenure_months=240)
    findings = check_foir(facts, policy)
    assert findings and findings[0].status == "needs_human"
    assert "cannot be verified" in findings[0].claim


def test_foir_abstains_rather_than_dropping_an_unparsed_row():
    policy = load_policy(POLICY)
    facts = _facts(sanction_amount=5_000_000, rate=8.75, tenure_months=240,
                   income_memo=150_000, obligations_memo=0)
    facts.salary_credits = [Field("c", 150_000, "bank_statement.pdf", 1, "row")]
    facts.unparsed_rows = [Field("row_ambiguous", None, "bank_statement.pdf", 1, "1,O9,700")]
    assert check_foir(facts, policy) == []


def test_a_lapsed_deviation_gives_no_cover():
    """The deviation gate: a covered breach is `explained`, an expired one is not."""
    import datetime as dt
    policy = load_policy(POLICY)
    facts = _facts(sanction_amount=5_000_000, rate=8.75, tenure_months=240,
                   income_memo=70_000, obligations_memo=0,
                   sanction_date=dt.date(2026, 5, 12))
    facts.salary_credits = [Field("c", 70_000, "bank_statement.pdf", 1, "row") for _ in range(3)]
    base = {"deviation_id": "D-1", "loan_id": "HL-TEST", "clause": "FOIR cap",
            "approved_by": "L2 - Credit Head", "doc": "deviation_register.pdf",
            "page": 1, "quote": "row"}

    facts.deviations = [{**base, "valid_till": dt.date(2026, 8, 1), "status": "Approved"}]
    assert check_foir(facts, policy)[0].status == "explained"

    facts.deviations = [{**base, "valid_till": dt.date(2026, 5, 11), "status": "Approved"}]
    f = check_foir(facts, policy)[0]
    assert f.status == "finding" and f.deviation_rejected is True

    facts.deviations = [{**base, "valid_till": dt.date(2026, 8, 1), "status": "Approved",
                         "approved_by": "L1 - Branch Credit Manager"}]
    assert check_foir(facts, policy)[0].status == "finding"

    facts.deviations = [{**base, "valid_till": dt.date(2026, 8, 1), "status": "Approved",
                         "loan_id": "HL-SOMEONE-ELSE"}]
    assert check_foir(facts, policy)[0].status == "finding"


def test_kyc_mismatch_on_surname():
    policy = load_policy(POLICY)
    facts = _facts(aadhaar_name="Neha C Sharma", pan_name="Neha C Verma")
    assert check_kyc(facts, policy)[0].family == "kyc_name_mismatch"


def test_kyc_same_name_passes():
    policy = load_policy(POLICY)
    facts = _facts(aadhaar_name="Neha C Sharma", pan_name="Neha C Sharma")
    assert check_kyc(facts, policy) == []


# ------------------------------------------------------------------ memo guard
def test_memo_guard_catches_an_invented_number():
    f = Finding(case_id="c", rule_id="R-05", clause="5.2", clause_page=3,
                family="foir_breach", status="finding", severity="high",
                claim="FOIR 61.2% breaches the 55% cap",
                derivation={"foir": 0.612, "cap": 0.55})
    ok = numeric_fidelity("The ratio is 61.2% against a cap of 55%.", f)
    bad = numeric_fidelity("The ratio is 61.2% against a cap of 55%, a gap of 12 lakh.", f)
    assert ok["ok"] is True
    assert bad["ok"] is False and bad["invented"]


def test_template_memo_always_passes_its_own_guard():
    f = Finding(case_id="c", rule_id="R-05", clause="5.2", clause_page=3,
                family="foir_breach", status="finding", severity="high",
                claim="FOIR 61.2% breaches the 55% cap",
                detail="EMI Rs. 44,200 and obligations Rs. 12,000 on income Rs. 91,800.",
                derivation={"foir": 0.612, "cap": 0.55, "income_verified": 91800},
                evidence=[{"doc": "bank_statement.pdf", "page": 1, "quote": "SALARY CREDIT 91,800"}])
    assert numeric_fidelity(draft_finding_template(f, None), f)["ok"] is True


# ------------------------------------------------------------------ ledger
def test_ledger_chain_detects_an_edited_event(tmp_path):
    p = tmp_path / "ledger.jsonl"
    led = Ledger(p)
    led.append("case_opened", {"loan_id": "HL-1"}, "2026-01-01T00:00:00Z")
    led.append("finding_proposed", {"loan_id": "HL-1", "finding_id": "f1", "family": "x",
                                    "status": "finding", "severity": "high", "claim": "c"},
               "2026-01-01T00:00:01Z")
    assert led.verify() == []

    lines = p.read_text().splitlines()
    tampered = lines[1].replace('"status":"finding"', '"status":"explained"')
    p.write_text("\n".join([lines[0], tampered]) + "\n")
    assert Ledger(p).verify() != []


def test_replay_rebuilds_the_book_from_events(tmp_path):
    p = tmp_path / "ledger.jsonl"
    led = Ledger(p)
    led.append("case_opened", {"loan_id": "HL-1"}, "2026-01-01T00:00:00Z")
    led.append("finding_proposed", {"loan_id": "HL-1", "finding_id": "f1", "family": "foir_breach",
                                    "status": "finding", "severity": "high", "claim": "c"},
               "2026-01-01T00:00:01Z")
    led.append("decision", {"loan_id": "HL-1", "finding_id": "f1", "action": "approve",
                            "reviewer": "A. Mehta"}, "2026-01-01T00:00:02Z")
    state = Ledger(p).replay()
    assert state["HL-1"]["findings"]["f1"]["decision"] == "approve"


def test_replay_after_a_real_review_run(tmp_path):
    """A decision must be recoverable from the ledger of an actual review, not a stub."""
    from lekh.engine import review_case
    policy = load_policy(POLICY)
    folder = next(f for f in sorted(CORPUS.iterdir()) if f.is_dir())
    ledger_path = tmp_path / "ledger.jsonl"
    led = Ledger(ledger_path)
    rec = review_case(folder, policy, run_id="t", ledger=led)
    assert rec.findings, "pick a case that produces a finding"

    target = rec.findings[0]
    led.append("decision", {"loan_id": rec.loan_id, "finding_id": target.id,
                            "action": "approve", "reviewer": "A. Mehta"},
               "2026-01-01T00:00:00Z")
    replayed = Ledger(ledger_path).replay()
    assert getattr(Ledger(ledger_path), "replay_skipped", []) == []
    assert replayed[rec.loan_id]["findings"][target.id]["decision"] == "approve"
    assert Ledger(ledger_path).verify() == []


# ------------------------------------------------------------------ regression gate
@pytest.mark.skipif(not CORPUS.exists(), reason="run `lekh generate` first")
def test_corpus_regression_is_green():
    """The eval is the regression suite: no finding may silently change."""
    policy = load_policy(POLICY)
    failures = []
    for folder in sorted(CORPUS.iterdir()):
        if not folder.is_dir():
            continue
        gt = json.loads((folder / "ground_truth.json").read_text())
        expected = {(e["family"], e["status"]) for e in gt["expected"] if e["status"] != "needs_human"}
        rec = review_case(folder, policy, run_id="test")
        got = {(f.family, f.status) for f in rec.findings if f.status != "needs_human"}
        if expected != got:
            failures.append((folder.name, expected - got, got - expected))
        if any(e["status"] == "needs_human" for e in gt["expected"]) and not rec.needs_human:
            failures.append((folder.name, "expected an abstention", "none emitted"))
    assert failures == []


@pytest.mark.skipif(not CORPUS.exists(), reason="run `lekh generate` first")
def test_every_emitted_citation_resolves_to_its_page():
    from lekh.evals import citation_report
    policy = load_policy(POLICY)
    bad = []
    for folder in sorted(CORPUS.iterdir())[:25]:
        if not folder.is_dir():
            continue
        rec = review_case(folder, policy, run_id="test")
        report = citation_report(rec, folder)
        if report["failed"]:
            bad.append((folder.name, report["failures"][:2]))
    assert bad == []


@pytest.mark.skipif(not CORPUS.exists(), reason="run `lekh generate` first")
def test_reviews_are_deterministic():
    policy = load_policy(POLICY)
    folder = next(f for f in sorted(CORPUS.iterdir()) if f.is_dir())
    a = review_case(folder, policy, run_id="a")
    b = review_case(folder, policy, run_id="b")
    assert a.digest == b.digest
