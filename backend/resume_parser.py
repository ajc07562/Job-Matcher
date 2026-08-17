"""
PDF resume text extraction. Uses pdfplumber, which handles real-world resume
layouts (columns, tables, varied fonts) more reliably than a bare low-level PDF
text extractor — it's built specifically around preserving reading order.

Deliberately a separate endpoint from /match rather than accepting a PDF directly
there: extraction and matching are different concerns, and keeping them separate
means the extracted text lands back in the resume textarea for the user to review
and edit before matching — extraction is rarely perfect (headers/footers, unusual
layouts, tables can come out garbled), so a silent direct-to-match pipeline would
hide failures instead of surfacing them.
"""
import io

import pdfplumber

MAX_PDF_SIZE_BYTES = 5 * 1024 * 1024  # 5MB — resumes are small; this mostly catches mistakes


class PdfParseError(Exception):
    """Raised for any PDF that can't be turned into usable resume text — the message
    is written to be shown directly to the user, not just logged."""


def extract_text_from_pdf(file_bytes: bytes) -> str:
    if len(file_bytes) > MAX_PDF_SIZE_BYTES:
        raise PdfParseError(f"That PDF is too large (max {MAX_PDF_SIZE_BYTES // (1024 * 1024)}MB).")

    if not file_bytes.startswith(b"%PDF-"):
        raise PdfParseError("That doesn't look like a valid PDF file.")

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page_texts = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    page_texts.append(page_text.strip())
            text = "\n\n".join(page_texts).strip()
    except PdfParseError:
        raise
    except Exception as e:
        # pdfplumber/pdfminer can raise a range of exception types on malformed
        # or encrypted PDFs — normalize all of them into one user-facing error.
        raise PdfParseError(f"Couldn't read that PDF ({type(e).__name__}). "
                             f"Try re-saving it or pasting the text directly instead.")

    if not text:
        raise PdfParseError(
            "No text could be extracted — this is likely a scanned image rather "
            "than a real text PDF. Try pasting the resume text directly instead."
        )
    return text