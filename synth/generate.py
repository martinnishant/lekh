"""Generate a synthetic but faithful corpus of Indian retail home-loan files.

Why synthetic: a student cannot get real bank files, and the companies we want
to work for cannot hand them over. So the corpus is built to be *hard in the
ways real files are hard*:

  * amounts in lakh notation, Indian digit grouping, "Rs." / "-/" noise
  * income stated in the memo that does not match the salary credits
  * a valuation in the memo that disagrees with the valuation report
  * deviation approvals that are expired, for the wrong file, or at the wrong
    sign-off level
  * one document per case whose hash does not match the intake manifest
  * label wording that changes between branches (so extraction cannot be one
    lucky regex)

After each case is written, an independent oracle computes the expected
findings from the *construction parameters* (not from the checker). That is the
whole point of the benchmark: the facts are known, the documents are the only
thing the checker sees.

    python synth/generate.py --out data/corpus --cases 40 --seed 7
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lekh.money import inr  # noqa: E402

# ----------------------------------------------------------------------------- policy constants
# RBI-style LTV ceiling by ticket size (₹30L / ₹30-75L / above ₹75L -> 90 / 80 / 75).
LTV_SLABS = [(3_000_000, 0.90), (7_500_000, 0.80), (float("inf"), 0.75)]
FOIR_CAP = 0.55
BUREAU_FLOOR = 700
INCOME_TOLERANCE = 0.10
VALUATION_TOLERANCE = 0.02
BUREAU_MAX_AGE_DAYS = 30
FOIR_TOLERANCE = 0.01        # stated vs recomputed
LTV_TOLERANCE = 0.01

BRANCHES = ["Pune", "Thane", "Indore", "Nashik", "Nagpur", "Surat", "Jaipur", "Kochi"]
FIRST = ["Rohan", "Neha", "Arjun", "Priya", "Vikram", "Sneha", "Imran", "Kavya",
         "Aditya", "Meera", "Rahul", "Divya", "Suresh", "Anjali", "Farhan", "Pooja"]
LAST = ["Mehta", "Sharma", "Iyer", "Patel", "Reddy", "Nair", "Kulkarni", "Bose",
        "Shetty", "Gupta", "Joshi", "Menon", "Chauhan", "Verma"]
VALUERS = ["Sanjiv Rao & Associates", "Deccan Valuation Services", "Anand Technical Consultancy"]
BANKS = ["Meridian Housing Finance Limited"]

# label variants per branch, so no single regex carries the corpus
LABELS = {
    "sanction_amount": ["Sanction amount", "Loan amount sanctioned", "Sanctioned amount"],
    "income": ["Net monthly income (applicant)", "Net take-home (applicant)",
               "NMI - applicant", "Net salary credit (applicant)"],
    "obligations": ["Existing monthly obligations", "Current EMI outgo",
                    "Existing EMI commitments"],
    "appraised": ["Appraised value (technical)", "Technical valuation",
                  "Value as per valuation report"],
    "purchase": ["Property purchase price", "Agreement value", "Consideration value"],
    "emi": ["EMI at sanction", "Instalment (PMT)", "Monthly instalment"],
    "bureau": ["Bureau score", "CIBIL score", "Commercial bureau score"],
}

PDD_ITEMS = ["Registered sale deed", "Property insurance policy", "Occupancy certificate",
             "Post-dated cheques (12)", "Legal opinion - title", "Tax receipt - current year"]


def ltv_cap(loan: float) -> float:
    for limit, cap in LTV_SLABS:
        if loan <= limit:
            return cap
    return 0.75


def emi_for(principal: float, rate: float, months: int) -> float:
    r = rate / 1200.0
    if r == 0:
        return principal / months
    return principal * r * (1 + r) ** months / ((1 + r) ** months - 1)


def build_pdf(path: Path, pages: list[list[str]]) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    for page in pages:
        if len(page) > 42:
            raise ValueError(f"{path.name}: page too long ({len(page)} lines)")
        y = 795
        for line in page:
            bold = line.startswith("##")
            text = line[2:] if bold else line
            c.setFont("Helvetica-Bold" if bold else "Helvetica", 8.5)
            c.drawString(48, y, text.strip()[:110])
            y -= 15
        c.showPage()
    c.save()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- one case
class CaseBuilder:
    def __init__(self, seed: int, idx: int):
        self.rng = random.Random(seed * 1000 + idx)
        self.seed = seed
        self.idx = idx
        self.loan_id = f"HL-{20000 + idx * 7 + seed}"
        self.branch = self.rng.choice(BRANCHES)
        self.defects: list[str] = []
        self.notes: list[str] = []
        self.tamper = False
        self.docs: dict[str, list[list[str]]] = {}
        self.truth: dict = {}

    # -- fact construction ---------------------------------------------------
    def construct(self, wanted: set[str]) -> None:
        r = self.rng
        if not wanted:
            # a clean file: everything comfortably inside policy
            self.loan = r.choice([2_450_000, 4_150_000, 6_200_000])
            self.purchase = round(self.loan / r.uniform(0.62, 0.70), -3)
            self.appraised = round(self.purchase * r.uniform(1.02, 1.10), -3)
            self.memo_valuation = self.appraised
            self.income_memo = r.choice([95_000, 128_000, 165_000])
            self.income_stmt = round(self.income_memo * r.uniform(0.98, 1.00), -2)
            self.oblig_memo = r.choice([0, 6_500, 11_000])
            self.oblig_stmt = self.oblig_memo
            self.bureau = r.randint(735, 790)
            self.dpd = 0
            self.bureau_lag = r.randint(4, 22)
            self.kyc_ok = True
            self.pdd_missing_items = []
            self.deviations = []
            self.stated_foir_override = None
            self.stated_ltv_override = None
            self.emi_override = None
            self.missing_doc = None
            self.ocr_noise = False
            self.ambiguous_label = False
            self.conflicting_valuation = False
            self.co_applicant_verified = False
            self.scanned = False
        else:
            self.loan = r.choice([2_350_000, 3_100_000, 4_800_000, 5_200_000,
                                  6_400_000, 7_200_000, 8_100_000])
            cap = ltv_cap(self.loan)
            # aim either inside or outside the LTV cap
            if {"ltv_breach", "ltv_explained", "deviation_invalid"} & wanted:
                target = cap + r.uniform(0.03, 0.09)
            else:
                target = cap - r.uniform(0.06, 0.18)
            self.appraised = round(self.loan / target, -3)
            self.purchase = round(self.appraised * r.uniform(0.86, 0.99), -3)
            self.memo_valuation = self.appraised
            self.income_stmt = r.choice([78_000, 92_000, 110_000, 135_000, 158_000])
            self.income_memo = round(self.income_stmt * r.uniform(0.99, 1.01), -2)
            self.oblig_stmt = r.choice([0, 4_500, 9_000, 14_500, 21_000])
            self.oblig_memo = self.oblig_stmt
            self.bureau = r.randint(720, 785)
            self.dpd = 0
            self.bureau_lag = r.randint(5, 25)
            self.kyc_ok = True
            self.pdd_missing_items = []
            self.deviations = []
            self.stated_foir_override = None
            self.stated_ltv_override = None
            self.emi_override = None
            self.missing_doc = None
            self.ocr_noise = False
            self.ambiguous_label = False
            self.conflicting_valuation = False
            self.co_applicant_verified = False
            self.scanned = False

        self.rate = r.choice([8.5, 8.65, 8.75, 9.0, 9.25])
        self.tenure = r.choice([180, 240, 300])
        self.emi = emi_for(self.loan, self.rate, self.tenure)

    def true_ltv(self) -> float:
        return self.loan / self.appraised

    def true_foir(self, income: float | None = None, oblig: float | None = None) -> float:
        return (self.emi + (oblig if oblig is not None else self.oblig_stmt)) / (
            income if income is not None else self.income_stmt)

    # -- defect injection ----------------------------------------------------
    def inject(self, wanted: set[str]) -> None:
        r = self.rng
        if "income_mismatch" in wanted:
            self.income_memo = round(self.income_stmt * r.uniform(1.16, 1.28), -2)
            self.defects.append("income_mismatch")
        if "valuation_mismatch" in wanted:
            # memo carries a stale, inflated valuation; the report says otherwise
            self.memo_valuation = round(self.appraised * r.uniform(1.05, 1.12), -3)
            if self.loan / self.memo_valuation <= ltv_cap(self.loan):
                self.notes.append("memo valuation pushed the LTV under the cap on paper only")
            self.defects.append("valuation_mismatch")
        if "bureau_low" in wanted:
            self.bureau = r.randint(612, 688)
            self.defects.append("bureau_low")
        if "dpd_delinquency" in wanted:
            self.dpd = r.choice([30, 35, 60, 90])
            self.defects.append("dpd_delinquency")
        if "stale_bureau" in wanted:
            self.bureau_lag = r.randint(45, 120)
            self.defects.append("stale_bureau")
        if "kyc_name_mismatch" in wanted:
            self.kyc_ok = False
            self.defects.append("kyc_name_mismatch")
        if "pdd_missing" in wanted:
            self.pdd_missing_items = r.sample(PDD_ITEMS, r.choice([1, 2]))
            self.defects.append("pdd_missing")
        if "arithmetic_mismatch" in wanted:
            self.emi_override = round(self.emi * r.uniform(0.93, 0.97), 0)
            self.stated_foir_override = round(self.true_foir(self.income_memo, self.oblig_memo)
                                             - r.uniform(0.06, 0.10), 3)
            self.defects.append("arithmetic_mismatch")

        # FOIR: decide after income/obligations are fixed
        if "foir_breach" in wanted or "foir_explained" in wanted or "deviation_invalid" in wanted:
            # raise obligations until FOIR clearly breaches on verified income
            target = FOIR_CAP + r.uniform(0.05, 0.14)
            need = target * self.income_stmt - self.emi
            if need > 0:
                self.oblig_stmt = round(need / 500) * 500
                self.oblig_memo = self.oblig_stmt
            else:  # EMI alone already breaches; shrink income
                self.income_stmt = round(self.emi / (target - 0.02) / 500) * 500
                self.income_memo = min(self.income_memo, self.income_stmt)
        if "ltv_breach" in wanted or "ltv_explained" in wanted:
            # force a real breach measured on the valuation report
            cap = ltv_cap(self.loan)
            self.appraised = round(self.loan / (cap + r.uniform(0.04, 0.10)), -3)
            self.purchase = round(self.appraised * r.uniform(0.88, 0.98), -3)
            self.memo_valuation = self.appraised

        # deviations
        sanction_date = dt.date(2026, 5, 12) + dt.timedelta(days=3 * self.idx)
        self.sanction_date = sanction_date
        valid = {
            "deviation_id": f"D-{2200 + self.idx}",
            "loan_id": self.loan_id,
            "clause": "FOIR cap" if "foir" in " ".join(wanted) else "LTV cap",
            "approved_by": "L2 - Credit Head",
            "valid_till": (sanction_date + dt.timedelta(days=90)).strftime("%d %b %Y"),
            "status": "Approved",
        }
        if "foir_explained" in wanted:
            self.defects.append("foir_explained")
            self.deviations.append({**valid, "clause": "FOIR cap",
                                    "deviation_id": f"D-{2300 + self.idx}"})
        if "ltv_explained" in wanted:
            self.defects.append("ltv_explained")
            self.deviations.append({**valid, "clause": "LTV cap",
                                    "deviation_id": f"D-{2400 + self.idx}"})
        if "deviation_invalid" in wanted:
            bad = dict(valid)
            bad["clause"] = "FOIR cap"
            flavour = r.choice(["expired", "wrong_file", "wrong_level", "wrong_clause"])
            bad["deviation_id"] = f"D-{2500 + self.idx}"
            if flavour == "expired":
                bad["valid_till"] = (sanction_date - dt.timedelta(days=20)).strftime("%d %b %Y")
            elif flavour == "wrong_file":
                bad["loan_id"] = f"HL-{90000 + self.idx}"
            elif flavour == "wrong_level":
                bad["approved_by"] = "L1 - Branch Credit Manager"
            else:
                bad["clause"] = "Documentation"
            self.deviations.append(bad)
            self.invalid_deviation_flavour = flavour
            # an invalid deviation gives no cover, so this is a surfaced breach
            self.defects.append("deviation_invalid")
            if "foir_breach" not in self.defects:
                self.defects.append("foir_breach")

        if "ocr_noise" in wanted:
            self.ocr_noise = True
            self.defects.append("ocr_noise")
        if "ambiguous_label" in wanted:
            self.ambiguous_label = True
            self.defects.append("ambiguous_label")
        if "conflicting_valuation" in wanted:
            self.conflicting_valuation = True
            self.defects.append("conflicting_valuation")
        if "deviation_boundary" in wanted:
            target = FOIR_CAP + r.uniform(0.04, 0.08)
            need = target * self.income_stmt - self.emi
            if need > 0:
                self.oblig_stmt = round(need / 500) * 500
                self.oblig_memo = self.oblig_stmt
            edge = {**valid, "clause": "FOIR cap",
                    "deviation_id": f"D-{2600 + self.idx}",
                    "valid_till": (sanction_date - dt.timedelta(days=1)).strftime("%d %b %Y")}
            self.deviations.append(edge)
            self.defects.append("deviation_boundary")
        if "co_applicant_verified" in wanted:
            # Policy 5.5: co-applicant income counts when a statement evidences it.
            # The file breaches on the applicant's income alone and passes on the
            # household's. Excluding the co-applicant produces a false positive here.
            self.co_income_verified = round(self.income_stmt * r.uniform(0.40, 0.55), -2)
            target = FOIR_CAP + r.uniform(0.06, 0.10)
            self.oblig_stmt = max(0, round((target * self.income_stmt - self.emi) / 500) * 500)
            self.oblig_memo = self.oblig_stmt
            self.co_applicant_verified = True
            self.defects.append("co_applicant_verified")
        if "scanned_document" in wanted:
            self.scanned = True
            self.defects.append("scanned_document")
        if "missing_document" in wanted:
            self.missing_doc = "bank_statement.pdf"
            self.defects.append("missing_document")
        if "tamper" in wanted:
            self.tamper = True
            self.defects.append("tamper")

        # Benchmark hygiene: a file either breaches clearly or passes clearly.
        # Near-threshold files belong in a separate "judgment" slice, not here.
        wants_foir = bool({"foir_breach", "foir_explained", "deviation_invalid"} & set(self.defects))
        if not wants_foir:
            guard = 0
            while self.true_foir(self.income_memo, self.oblig_memo) > FOIR_CAP - 0.03 and guard < 50:
                if self.oblig_memo >= 1000:
                    self.oblig_memo = max(0, self.oblig_memo - 1000)
                    self.oblig_stmt = max(0, self.oblig_stmt - 1000)
                else:
                    self.income_stmt = round(self.income_stmt * 1.06, -2)
                    self.income_memo = self.income_stmt
                guard += 1
        wants_ltv = bool({"ltv_breach", "ltv_explained"} & set(self.defects))
        if not wants_ltv:
            guard = 0
            while self.loan / self.appraised > ltv_cap(self.loan) - 0.03 and guard < 50:
                self.appraised = round(self.appraised * 1.04, -3)
                self.memo_valuation = self.appraised
                guard += 1

        # A breach must be a breach on verified income too
        self.truth.update({
            "loan_id": self.loan_id,
            "branch": self.branch,
            "sanction_amount": self.loan,
            "purchase_price": self.purchase,
            "appraised_value": self.appraised,
            "memo_valuation": self.memo_valuation,
            "income_memo": self.income_memo,
            "income_statement": self.income_stmt,
            "obligations_memo": self.oblig_memo,
            "obligations_statement": self.oblig_stmt,
            "bureau_score": self.bureau,
            "dpd_max_12m": self.dpd,
            "bureau_lag_days": self.bureau_lag,
            "rate": self.rate,
            "tenure_months": self.tenure,
            "emi_true": round(self.emi, 2),
            "foir_true": round(self.true_foir(), 4),
            "ltv_true": round(self.true_ltv(), 4),
            "ltv_cap": ltv_cap(self.loan),
            "deviations": self.deviations,
            "seeded": sorted(self.defects),
        })

    # -- oracle --------------------------------------------------------------
    def oracle(self) -> list[dict]:
        """Expected findings, computed from construction parameters.

        Deliberately a second implementation of the policy math. It shares the
        constants and nothing else; it never sees an extracted field.
        """
        t = self.truth
        out: list[dict] = []

        def add(family, status="finding"):
            out.append({"family": family, "status": status})

        combined = t["income_statement"] + (self.co_income_verified
                                            if self.co_applicant_verified else 0)
        fl = (t["emi_true"] + t["obligations_statement"]) / max(combined, 1)
        if fl > FOIR_CAP + 0.005:
            dev = [d for d in t["deviations"] if d["clause"] == "FOIR cap"]
            covered = any(
                d["loan_id"] == t["loan_id"]
                and d["status"] == "Approved"
                and d["approved_by"].startswith("L2")
                and dt.datetime.strptime(d["valid_till"], "%d %b %Y").date() >= self.sanction_date
                for d in dev)
            add("foir_breach", "explained" if covered else "finding")

        if t["ltv_true"] > t["ltv_cap"] + 0.005:
            dev = [d for d in t["deviations"] if d["clause"] == "LTV cap"]
            covered = any(
                d["loan_id"] == t["loan_id"]
                and d["status"] == "Approved"
                and d["approved_by"].startswith("L2")
                and dt.datetime.strptime(d["valid_till"], "%d %b %Y").date() >= self.sanction_date
                for d in dev)
            add("ltv_breach", "explained" if covered else "finding")

        gap = abs(t["income_memo"] - t["income_statement"]) / max(t["income_statement"], 1)
        if gap > INCOME_TOLERANCE + 0.01:
            add("income_mismatch")

        vgap = abs(t["memo_valuation"] - t["appraised_value"]) / t["appraised_value"]
        if vgap > VALUATION_TOLERANCE + 0.005:
            add("valuation_mismatch")

        if self.emi_override and abs(self.emi_override - t["emi_true"]) > 100:
            add("arithmetic_mismatch")

        if t["bureau_score"] < BUREAU_FLOOR:
            add("bureau_low")
        if t["dpd_max_12m"] >= 30:
            add("dpd_delinquency")
        if t["bureau_lag_days"] > BUREAU_MAX_AGE_DAYS + 2:
            add("stale_bureau")
        if not self.kyc_ok:
            add("kyc_name_mismatch")
        if self.pdd_missing_items:
            add("pdd_missing")
        if self.tamper:
            add("tamper")
        if self.missing_doc:
            out.append({"family": "missing_document", "status": "needs_human"})

        for fam in ("ocr_noise", "ambiguous_label", "conflicting_valuation", "scanned_document"):
            if fam in self.defects:
                out.append({"family": fam, "status": "needs_human"})

        if self.missing_doc:
            out = [f for f in out if f["family"] not in
                   ("foir_breach", "income_mismatch", "arithmetic_mismatch")]

        # de-dup, keep first status priority finding > explained
        seen: dict[str, str] = {}
        for f in out:
            if f["family"] not in seen or f["status"] == "finding":
                seen[f["family"]] = f["status"]
        return [{"family": k, "status": v} for k, v in sorted(seen.items())]

    # -- documents -----------------------------------------------------------
    def build_docs(self) -> None:
        r, t = self.rng, self.truth
        sd = self.sanction_date
        applicant = f"{r.choice(FIRST)} {r.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')} {r.choice(LAST)}"
        co = f"{r.choice(FIRST)} {r.choice(LAST)}"
        self.applicant = applicant
        L = {k: r.choice(v) for k, v in LABELS.items()}

        stated_foir = self.stated_foir_override if self.stated_foir_override is not None else \
            round((self.emi + self.oblig_memo) / self.income_memo, 3)
        stated_ltv = self.stated_ltv_override if self.stated_ltv_override is not None else \
            round(self.loan / self.memo_valuation, 3)
        emi_shown = self.emi_override if self.emi_override else round(self.emi, 0)

        memo = [
            [f"##{BANKS[0]}", "Credit Administration Department", "",
             "##CREDIT SANCTION MEMORANDUM", "",
             f"Loan ID                  : {self.loan_id}",
             f"Branch                   : {self.branch}",
             f"Product                  : Retail Home Loan",
             f"Sanction date            : {sd.strftime('%d %b %Y')}",
             f"Applicant                : {applicant}",
             f"Co-applicant             : {co}",
             "",
             "##A. Facility",
             f"{L['sanction_amount']:<32}: Rs. {inr(self.loan)}/-",
             f"Tenure                   : {self.tenure} months",
             f"Interest rate            : {self.rate:.2f}% p.a. (floating)",
             f"{L['emi']:<32}: Rs. {inr(emi_shown)}/-",
             "",
             "##B. Security",
             f"{L['purchase']:<32}: Rs. {inr(self.purchase)}/-",
             f"{L['appraised']:<32}: Rs. {inr(self.memo_valuation)}/-",
             f"Valuer                   : {r.choice(VALUERS)}",
             f"Valuation date           : {(sd - dt.timedelta(days=r.randint(20, 70))).strftime('%d %b %Y')}",
             "",
             "This memorandum is prepared for internal credit approval and is",
             "subject to the retail credit policy in force on the sanction date."],
            ["##C. Income and obligations",
             f"{L['income']:<40}: Rs. {inr(self.income_memo)}/-",
             f"Net monthly income (co-applicant)        : Rs. {inr(round(self.income_memo*0.32, -2))}/-",
             f"{L['obligations']:<40}: Rs. {inr(self.oblig_memo)}/-",
             "",
             "##D. Ratios as computed by the credit team",
             f"FOIR (stated)            : {stated_foir*100:.1f}%",
             f"LTV (stated)             : {stated_ltv*100:.1f}% on {L['appraised'].split('(')[0].strip().lower()}",
             "",
             "##E. Notes",
             "1. Bureau and income documents are held in the credit file.",
             "2. Deviation, where applicable, is recorded in the deviation register.",
             "3. Disbursement subject to completion of post-disbursement documents.",
             "",
             f"Prepared by : Credit Officer, {self.branch}",
             f"Recommended : Branch Credit Manager, {self.branch}"],
        ]

        # bank statement: salary credits averaging income_stmt
        n_months = 6
        sal_lines = []
        total = 0
        for m in range(n_months):
            amt = round(self.income_stmt * r.uniform(0.96, 1.04), -2)
            total += amt
            sal_lines.append((m, amt))
        stmt_avg = round(total / n_months, 2)
        # nudge so the average matches the intended statement income closely
        self.income_stmt_actual = stmt_avg
        t["income_statement"] = stmt_avg
        pages_bs: list[list[str]] = [[
            f"##MERIDIAN HOUSING FINANCE LIMITED",
            f"Account statement - salary account",
            f"Account holder : {applicant}",
            f"Account number : XXXXXXXX{r.randint(1000, 9999)}",
            f"Statement period : {sd.strftime('%b %Y')} (last 6 months)",
            "",
            "Date        Narration                         Debit        Credit       Balance",
            "-" * 92,
        ]]
        bal = 145_000
        for i, (m, amt) in enumerate(sal_lines):
            d = sd - dt.timedelta(days=30 * (n_months - m))
            bal += amt
            pages_bs[0].append(
                f"{d.strftime('%d/%m/%Y')}  SALARY CREDIT - NEFT                  "
                f"         {inr(amt):>12}   {inr(bal):>12}")
            if i == 2:
                pages_bs.append([
                    f"Account statement (continued) - {applicant}",
                    "",
                    "Date        Narration                         Debit        Credit       Balance",
                    "-" * 92])
        pages_bs.append([
            "Account statement (continued) - obligations",
            "",
            "Date        Narration                         Debit        Credit       Balance",
            "-" * 92,
            f"{(sd - dt.timedelta(days=15)).strftime('%d/%m/%Y')}  "
            f"ACH DEBIT - LOAN EMI                  {inr(self.oblig_stmt):>12}            ",
            "",
            f"Average monthly salary credit over period : Rs. {inr(stmt_avg)}/-",
            f"Standing instructions observed            : {1 if self.oblig_stmt else 0}",
        ])

        val_date = sd - dt.timedelta(days=r.randint(20, 70))
        appraisal = [[
            "##" + r.choice(VALUERS),
            "Registered valuers - technical report",
            "",
            f"Report reference     : VAL/{sd.year}/{r.randint(1000, 9999)}",
            f"Property             : Flat {r.randint(2, 14)}{r.choice('ABC')}, "
            f"{r.choice(['Sunrise','Green Meadows','Palm Grove','Lake View'])} Residency, {self.branch}",
            f"Borrower             : {applicant}",
            f"Date of inspection   : {val_date.strftime('%d %b %Y')}",
            "",
            "##Valuation",
            f"{L['appraised']:<40}: Rs. {inr(self.appraised)}/-",
            f"Distress value (90 days)                 : Rs. {inr(round(self.appraised*0.82, -3))}/-",
            f"Method                                   : Sales comparison",
            f"Built-up area                            : {r.randint(640, 1180)} sq ft",
            "",
            "We certify that the property was inspected and valued on the date",
            "stated above. This figure is the value relied upon for LTV purposes",
            "under clause 5 of the retail credit policy.",
        ]]

        rep_date = sd - dt.timedelta(days=self.bureau_lag)
        bureau = [[
            "##TRANSUNION CIBIL - CREDIT INFORMATION REPORT",
            "",
            f"Consumer name        : {applicant}",
            f"Report date          : {rep_date.strftime('%d %b %Y')}",
            f"Enquiry purpose      : Home loan",
            "",
            f"{L['bureau']:<40}: {self.bureau}",
            f"DPD (max, last 12 months)                : {self.dpd}",
            f"Accounts active                          : {r.randint(2, 6)}",
            f"Written-off / settled                    : 0" if self.dpd == 0 else
            f"Written-off / settled                    : 1",
            "",
            "The score above is generated on the data held on the report date.",
            "This report is valid for 30 days from the report date for the purpose",
            "of a fresh credit assessment.",
        ]]

        dev_rows = ["##DEVIATION REGISTER (extract)", "",
                    "Deviation ID  Loan ID      Clause        Approved by                 Valid till      Status",
                    "-" * 100]
        if self.deviations:
            for d in self.deviations:
                dev_rows.append(f"{d['deviation_id']:<13} {d['loan_id']:<12} "
                                f"{d['clause']:<13} {d['approved_by']:<27} "
                                f"{d['valid_till']:<15} {d['status']}")
        else:
            dev_rows.append("(no open deviations for this branch in the period)")
        dev_rows += ["", "Deviations lapse on the valid-till date. L2 approval is required",
                     "for any breach of the FOIR or LTV cap."]

        aadhaar_name = applicant
        pan_name = applicant if self.kyc_ok else f"{applicant.split()[0]} {r.choice(LAST)}"
        kyc = [[
            "##KYC ANNEXURE",
            "",
            f"Loan ID              : {self.loan_id}",
            f"Aadhaar name         : {aadhaar_name}",
            f"PAN name             : {pan_name}",
            f"PAN                  : {r.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}XYZ"
            f"P{r.randint(1000, 9999)}{r.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}",
            f"Address verification : Completed {(sd - dt.timedelta(days=9)).strftime('%d %b %Y')}",
            "",
            "##Post-disbursement documents (PDD)",
        ]]
        for item in PDD_ITEMS:
            mark = "MISSING" if item in self.pdd_missing_items else "received"
            kyc[0].append(f"  {item:<40} : {mark}")

        if self.ocr_noise:
            # an OCR pass turned the leading digit of one salary credit into 'O'
            for i, line in enumerate(pages_bs[0]):
                if "SALARY CREDIT" in line:
                    pages_bs[0][i] = re.sub(r"(SALARY CREDIT - NEFT\s+)(\d)", r"\1O",
                                            line, count=1)
                    break
        if self.ambiguous_label:
            # this branch's memo says "gross", not "net": not the same number
            memo[1] = [ln.replace(L["income"], "Monthly gross salary (applicant)")
                       if ln.startswith(L["income"]) else ln for ln in memo[1]]
        self.docs = {
            "sanction_memo.pdf": memo,
            "bank_statement.pdf": pages_bs,
            "appraisal_report.pdf": appraisal,
            "bureau_report.pdf": bureau,
            "deviation_register.pdf": dev_rows if isinstance(dev_rows[0], list) else [dev_rows],
            "kyc_annexure.pdf": kyc,
        }
        if self.co_applicant_verified:
            co_lines = []
            co_bal = 90_000
            for m in range(n_months):
                amt = round(self.co_income_verified * r.uniform(0.97, 1.03), -2)
                co_bal += amt
                d = sd - dt.timedelta(days=30 * (n_months - m))
                co_lines.append(f"{d.strftime('%d/%m/%Y')}  SALARY CREDIT - NEFT"
                                f"                  {inr(amt):>12}   {inr(co_bal):>12}")
            self.docs["co_applicant_statement.pdf"] = [[
                "##Account statement - co-applicant",
                f"Account holder : {co}",
                f"Statement period : {sd.strftime('%b %Y')} (last 6 months)",
                "",
                "Date        Narration                         Debit        Credit",
                "-" * 80] + co_lines + ["", "Co-applicant is a co-borrower on this facility."]]


        if self.conflicting_valuation:
            # a revised opinion lands after the original report. Two numbers,
            # one decision: the file is not ready for an automatic LTV.
            self.docs["valuation_revised.pdf"] = [[
                "##Anand Technical Consultancy - revised opinion",
                f"Borrower : {applicant}",
                f"Date      : {(sd - dt.timedelta(days=3)).strftime('%d %b %Y')}",
                "",
                "##Revised valuation",
                f"Market value                             : Rs. "
                f"{inr(round(self.appraised * 1.09, -3))}/-",
                "",
                "This opinion revises an earlier report for the same property.",
            ]]

    # -- write ---------------------------------------------------------------
    def write(self, out_root: Path) -> None:
        d = out_root / self.loan_id
        d.mkdir(parents=True, exist_ok=True)
        hashes: dict[str, str] = {}
        for name, pages in self.docs.items():
            if name == self.missing_doc:
                continue  # the document is genuinely absent from the file
            p = d / name
            build_pdf(p, pages)
            hashes[name] = sha256_file(p)

        if self.scanned:
            # the branch scanned the bureau report instead of exporting it:
            # the file is present, and yields no machine-readable text
            c = canvas.Canvas(str(d / "bureau_report.pdf"), pagesize=A4)
            c.rect(60, 600, 480, 180, stroke=1, fill=0)
            c.rect(60, 300, 480, 240, stroke=1, fill=0)
            c.showPage()
            c.save()
            hashes["bureau_report.pdf"] = sha256_file(d / "bureau_report.pdf")

        if self.scanned:
            # the branch scanned the bureau report instead of exporting it:
            # the file is present, and yields no machine-readable text
            c = canvas.Canvas(str(d / "bureau_report.pdf"), pagesize=A4)
            c.rect(60, 600, 480, 180, stroke=1, fill=0)
            c.rect(60, 300, 480, 240, stroke=1, fill=0)
            c.showPage()
            c.save()
            hashes["bureau_report.pdf"] = sha256_file(d / "bureau_report.pdf")

        if self.tamper:
            # someone replaced a page in the bank statement after intake:
            # the manifest keeps the hash the file had when it was received.
            pages = self.docs["bank_statement.pdf"]
            tampered = [list(pg) for pg in pages]
            for i, line in enumerate(tampered[-1]):
                if "Average monthly salary credit" in line:
                    tampered[-1][i] = ("Average monthly salary credit over period : Rs. "
                                       + inr(round(self.income_stmt_actual * 1.18, -2)) + "/-")
            build_pdf(d / "bank_statement.pdf", tampered)

        (d / "_manifest.json").write_text(json.dumps({
            "loan_id": self.loan_id,
            "documents": hashes,
            "captured_at": "2026-06-01T09:00:00+05:30",
        }, indent=2), encoding="utf-8")

        truth = {**self.truth,
                 "applicant": self.applicant,
                 "pdd_missing": self.pdd_missing_items,
                 "expected": self.oracle(),
                 "notes": self.notes}
        (d / "ground_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")


FAMILIES = ["foir_breach", "foir_explained", "income_mismatch", "ltv_breach",
            "ltv_explained", "valuation_mismatch", "arithmetic_mismatch",
            "bureau_low", "dpd_delinquency", "stale_bureau", "kyc_name_mismatch",
            "pdd_missing", "deviation_invalid", "missing_document", "tamper",
            "ocr_noise", "ambiguous_label", "conflicting_valuation", "deviation_boundary",
            "co_applicant_verified", "scanned_document"]


def plan_cases(n: int, seed: int) -> list[set[str]]:
    """Every family appears at least three times, plus mixed files and clean files.

    Clean files are in the benchmark on purpose: a reviewer that flags nothing
    is useless, and a reviewer that flags everything must not be able to win.
    """
    r = random.Random(seed)
    rounds = max(3, n // (len(FAMILIES) + 2))
    singles: list[str] = FAMILIES * rounds
    r.shuffle(singles)
    plan: list[set[str]] = [{f} for f in singles]
    while len(plan) < n - max(3, n // 8):
        plan.append(set(r.sample(FAMILIES, r.choice([1, 2, 2, 3]))))
    clean = max(3, n // 8)
    plan = plan[: n - clean] + [set() for _ in range(clean)]
    r.shuffle(plan)
    return plan


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/corpus")
    ap.add_argument("--cases", type=int, default=48)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        import shutil
        shutil.rmtree(out)          # stale files would silently join the corpus
    out.mkdir(parents=True, exist_ok=True)
    plan = plan_cases(args.cases, args.seed)
    for idx, wanted in enumerate(plan):
        cb = CaseBuilder(args.seed, idx)
        cb.construct(wanted)
        cb.inject(wanted)
        cb.build_docs()
        cb.write(out)
    print(f"wrote {len(plan)} cases to {out}")


if __name__ == "__main__":
    main()
