import io
from typing import List, Optional
from pydantic import BaseModel, Field
from app.core.config import settings
from app.core.logger import logger


class PageContent(BaseModel):
    page_number: int
    text: str
    char_count: int


class ExtractedDocument(BaseModel):
    filename: str
    file_size_bytes: int
    total_pages: int
    total_chars: int
    pages: List[PageContent]
    full_text: str


class TextExtractor:
    """
    High-capacity document text extraction with page mapping.
    Supports DOCX up to 50 MB without arbitrary truncation.
    """

    @classmethod
    def validate_file_size(cls, file_bytes: bytes) -> None:
        size_mb = len(file_bytes) / (1024 * 1024)
        if size_mb > settings.MAX_FILE_SIZE_MB:
            raise ValueError(
                f"File size {size_mb:.2f} MB exceeds the configured maximum limit of {settings.MAX_FILE_SIZE_MB} MB."
            )

    @classmethod
    def extract_document(cls, file_bytes: bytes, filename: str = "") -> ExtractedDocument:
        """
        Extracts full document content (DOCX or PDF) with page-level mapping.
        """
        if not file_bytes:
            raise ValueError("Empty file byte stream provided")

        cls.validate_file_size(file_bytes)
        fname_lower = (filename or "").lower()
        if fname_lower.endswith(".pdf"):
            return cls._extract_pdf_document(file_bytes, filename)
        return cls._extract_docx_document(file_bytes, filename)

    @classmethod
    def _extract_pdf_document(cls, pdf_bytes: bytes, filename: str) -> ExtractedDocument:
        import pymupdf

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count > settings.MAX_PDF_PAGES:
            raise ValueError(
                f"PDF has {doc.page_count} pages, which exceeds the maximum limit of {settings.MAX_PDF_PAGES} pages."
            )

        pages: List[PageContent] = []
        all_text_parts = []

        for page_idx in range(doc.page_count):
            page = doc[page_idx]
            page_text = page.get_text().strip()
            pages.append(
                PageContent(
                    page_number=page_idx + 1,
                    text=page_text,
                    char_count=len(page_text)
                )
            )
            if page_text:
                all_text_parts.append(page_text)

        full_text = "\n\n".join(all_text_parts).strip()
        total_pages = max(1, len(pages))

        logger.info(
            f"[PDF Extraction] Processed {len(pdf_bytes) / 1024:.1f} KB, "
            f"mapped {total_pages} pages, {len(full_text)} characters."
        )

        return ExtractedDocument(
            filename=filename or "document.pdf",
            file_size_bytes=len(pdf_bytes),
            total_pages=total_pages,
            total_chars=len(full_text),
            pages=pages,
            full_text=full_text
        )

    @classmethod
    def _extract_docx_document(cls, docx_bytes: bytes, filename: str) -> ExtractedDocument:
        import docx
        from docx.text.paragraph import Paragraph
        from docx.table import Table

        doc = docx.Document(io.BytesIO(docx_bytes))
        pages: List[PageContent] = []
        current_page_num = 1
        current_page_parts = []
        current_page_chars = 0
        all_text_parts = []

        # Average characters per page for Word documents without explicit hard breaks
        ESTIMATED_PAGE_CHARS = 3000

        for el in doc.element.body:
            element_text = ""
            has_page_break = False

            if el.tag.endswith("p"):
                p = Paragraph(el, doc)
                txt = p.text.strip()
                if txt:
                    element_text = txt
                # Check for explicit page breaks in paragraph XML
                if "w:br" in el.xml and ('w:type="page"' in el.xml or "lastRenderedPageBreak" in el.xml):
                    has_page_break = True

            elif el.tag.endswith("tbl"):
                table = Table(el, doc)
                table_lines = []
                for row in table.rows:
                    row_cells = [c.text.strip().replace("\n", " ") for c in row.cells if c.text.strip()]
                    if row_cells:
                        table_lines.append("| " + " | ".join(row_cells) + " |")
                if table_lines:
                    element_text = "\n".join(table_lines)

            if element_text:
                all_text_parts.append(element_text)
                current_page_parts.append(element_text)
                current_page_chars += len(element_text) + 2

            if has_page_break or current_page_chars >= ESTIMATED_PAGE_CHARS:
                page_str = "\n\n".join(current_page_parts).strip()
                if page_str:
                    pages.append(
                        PageContent(
                            page_number=current_page_num,
                            text=page_str,
                            char_count=len(page_str)
                        )
                    )
                    current_page_num += 1
                    current_page_parts = []
                    current_page_chars = 0

        # Residual page
        if current_page_parts:
            page_str = "\n\n".join(current_page_parts).strip()
            if page_str:
                pages.append(
                    PageContent(
                        page_number=current_page_num,
                        text=page_str,
                        char_count=len(page_str)
                    )
                )

        full_text = "\n\n".join(all_text_parts).strip()
        total_pages = max(1, len(pages))

        logger.info(
            f"[DOCX Extraction] Processed {len(docx_bytes) / 1024:.1f} KB, "
            f"mapped {total_pages} pages, {len(full_text)} characters."
        )

        return ExtractedDocument(
            filename=filename or "document.docx",
            file_size_bytes=len(docx_bytes),
            total_pages=total_pages,
            total_chars=len(full_text),
            pages=pages,
            full_text=full_text
        )

    @classmethod
    def extract_from_bytes(cls, file_bytes: bytes, filename: str = "") -> str:
        """Backward-compatible string extraction without artificial limits."""
        doc = cls.extract_document(file_bytes, filename)
        return doc.full_text

    @classmethod
    def extract_from_docx_bytes(cls, docx_bytes: bytes) -> str:
        """Backward-compatible docx string extraction."""
        doc = cls._extract_docx_document(docx_bytes, "document.docx")
        return doc.full_text

