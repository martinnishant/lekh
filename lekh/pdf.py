"""Document intake: page-level text, hashes, and the intake manifest check.

Two things every regulated reviewer needs before it reads a word:

  1. the page a claim came from, so a human can look at it; and
  2. proof the document has not changed since it entered the file.

`Document.pages` is the only surface the rest of the system reads. Nothing
downstream keeps a whole-document string, because "somewhere in this PDF" is
not evidence.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


@dataclass
class Document:
    name: str
    pages: list[str]
    sha256: str
    page_count: int = 0

    def __post_init__(self) -> None:
        self.page_count = len(self.pages)

    def page(self, n: int) -> str:
        """1-indexed page text. Raises rather than returning ''."""
        if not 1 <= n <= len(self.pages):
            raise IndexError(f"{self.name}: no page {n} (has {len(self.pages)})")
        return self.pages[n - 1]

    def find(self, needle: str) -> tuple[int, str] | None:
        """First (page, line) containing needle, whitespace-normalised."""
        ndl = " ".join(needle.split()).lower()
        for i, text in enumerate(self.pages, start=1):
            for line in text.splitlines():
                if ndl in " ".join(line.split()).lower():
                    return i, line
        return None

    @property
    def fingerprint(self) -> str:
        return self.sha256[:16]


@dataclass
class CaseFile:
    loan_id: str
    folder: Path
    documents: dict[str, Document] = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    tampered: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)

    def get(self, name: str) -> Document | None:
        return self.documents.get(name)


REQUIRED = ["sanction_memo.pdf", "bank_statement.pdf", "appraisal_report.pdf",
            "bureau_report.pdf", "deviation_register.pdf", "kyc_annexure.pdf"]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_pdf_pages(path: Path) -> list[str]:
    with pdfplumber.open(str(path)) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def load_case(folder: str | Path) -> CaseFile:
    folder = Path(folder)
    case = CaseFile(loan_id=folder.name, folder=folder)
    manifest_path = folder / "_manifest.json"
    if manifest_path.exists():
        case.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = case.manifest.get("documents", {})

    for path in sorted(folder.glob("*.pdf")):
        doc = Document(name=path.name, pages=read_pdf_pages(path),
                       sha256=sha256_file(path))
        case.documents[doc.name] = doc
        if doc.name in expected and expected[doc.name] != doc.sha256:
            case.tampered.append(doc.name)

    case.missing = [n for n in REQUIRED if n not in case.documents]
    case.unexpected = [n for n in case.documents if expected and n not in expected]
    return case
