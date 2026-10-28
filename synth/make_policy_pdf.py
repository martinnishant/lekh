"""Lay out the retail credit policy PDF that the rules cite.

The policy text is authored here, independently of the rule file. The rules
carry a `quote` and a `page`, and `lekh.policy.verify_citations` re-reads this
PDF to prove the quote is really on that page. If someone edits the policy and
forgets the rules, the build fails instead of reviewing files against a clause
that no longer exists.
"""
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from synth.generate import build_pdf  # noqa: E402

PAGES: list[list[str]] = [
    ["##MERIDIAN HOUSING FINANCE LIMITED",
     "##RETAIL CREDIT POLICY - HOME LOANS",
     "Version 3.2   |   Effective 01 April 2026   |   Approved by the Credit Policy Committee",
     "",
     "##Clause 3 - Documentation and file completeness",
     "",
     "3.1 The credit file must contain the sanction memorandum, the technical valuation",
     "    report, the bureau report, the deviation register and the KYC annexure before",
     "    a credit decision is recorded.",
     "3.2 A file missing any document listed in 3.1 is returned to the branch and is not",
     "    reviewed until the document is placed on file.",
     "3.3 No document may be altered after intake. Every document is hashed at receipt",
     "    and the hash is retained with the file. A document whose hash no longer agrees",
     "    with the intake record is treated as unreliable, and every conclusion drawn",
     "    from it is withdrawn pending explanation.",
     "3.4 The bank statement is a record, not a claim: balances and summaries printed on",
     "    it are checked against the transactions on the same statement."],
    ["##Clause 4 - Bureau and conduct",
     "",
     "4.1 A bureau score below 700 at the date of sanction requires the file to be",
     "    declined, or escalated to the Credit Head with the reasons recorded.",
     "4.2 An account with 30 or more days past due in the trailing twelve months is not",
     "    eligible under this policy.",
     "4.3 The bureau report relied upon must be no older than 30 days at the date of",
     "    sanction. A report older than 30 days is not a valid basis for the decision.",
     "4.4 Bureau findings are recorded against the report on file, with the report date",
     "    and the score stated in the review memorandum."],
    ["##Clause 5 - Income and FOIR",
     "",
     "5.1 FOIR is the contractual instalment on the proposed facility plus all existing",
     "    monthly obligations, divided by verified net monthly income.",
     "5.2 FOIR shall not exceed 55% of verified net monthly income.",
     "5.3 Verified net monthly income is the average of the salary credits evidenced in",
     "    the bank statement over the statement period.",
     "5.4 Income stated in the sanction memorandum must reconcile to the verified figure",
     "    within 10%.",
     "5.5 Co-applicant income may be counted only where it is independently evidenced by",
     "    a statement on file; otherwise it is excluded from the ratio and the exclusion",
     "    is recorded in the note."],
    ["##Clause 6 - Security and LTV",
     "",
     "6.1 LTV is computed on the value stated in the technical valuation report, and not",
     "    on the consideration stated in the agreement to sell.",
     "6.2 LTV shall not exceed 90% where the loan is up to Rs. 30 lakh, 80% where the",
     "    loan is above Rs. 30 lakh and up to Rs. 75 lakh, and 75% where the loan is",
     "    above Rs. 75 lakh.",
     "6.3 The value adopted in the sanction memorandum must agree with the technical",
     "    valuation report within 2%.",
     "6.4 A valuation relied upon for LTV purposes must be dated within 90 days of the",
     "    sanction date."],
    ["##Clause 7 - Accuracy and identity",
     "",
     "7.1 Every ratio stated in the sanction memorandum must reproduce from the inputs",
     "    stated in the same memorandum.",
     "7.2 The name on the PAN must match the name on the Aadhaar. A difference is",
     "    acceptable only where the supporting instrument of change is on file.",
     "7.3 Post-disbursement documents listed in the annexure must be received within 90",
     "    days of disbursement; until received, the file remains open."],
    ["##Clause 8 - Deviations",
     "",
     "8.1 Any breach of the FOIR cap in 5.2 or the LTV cap in 6.2 requires a deviation",
     "    approved at L2, registered against the same loan, with a stated validity date.",
     "8.2 A deviation that has lapsed, is registered against another file, or is",
     "    approved below L2 provides no cover for the breach. The breach is reported on",
     "    its merits and the deviation is reported alongside it.",
     "8.3 A deviation does not convert a breach into a pass. It converts a breach into",
     "    an explained breach, which a named person signs off with the evidence."],
]


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "policy" / "retail_home_loan_v3.2.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(out, PAGES)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
