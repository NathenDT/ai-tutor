import io
import logging
import re


logger = logging.getLogger(__name__)


def extract_pdf_pages(content):
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError(
            "PDF extraction dependency is missing. Install requirements.txt, including pypdf."
        ) from error

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as error:
        raise RuntimeError("Could not read the uploaded PDF.") from error

    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            logger.warning("Could not extract text from PDF page %s", page_number)
            text = ""

        normalized_text = normalize_extracted_text(text)
        if normalized_text:
            pages.append({"page_number": page_number, "text": normalized_text})

    return pages


def normalize_extracted_text(text):
    return re.sub(r"\s+", " ", text).strip()
