"""
Light-Footprint In-Memory Parser.

Parses PDF and DOCX files directly from BytesIO buffers (never touching disk).
Uses PyMuPDF (fitz) for PDFs and python-docx for DOCX files.
"""

from __future__ import annotations

import io
import logging
import mimetypes
from typing import Optional

import fitz  # PyMuPDF
from docx import Document as DocxDocument

logger = logging.getLogger(__name__)


class InMemoryDocumentParser:
    """Parses PDF/DOCX documents entirely from in-memory byte streams.

    Supports:
        - PDF: via PyMuPDF (fitz) with spatial block and plain text extraction.
        - DOCX: via python-docx for paragraph-level text extraction.

    Resources are cleaned up immediately after parsing (context-manager safe).
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc"}

    @staticmethod
    def _detect_filetype(url: str, buffer: io.BytesIO) -> str:
        """Detect file type from URL or buffer magic bytes."""
        # Try URL extension first
        _, ext = mimetypes.guess_type(url)
        if ext:
            ext = ext.lower()
            if ext == ".pdf" or "pdf" in ext:
                return "pdf"
            if ext in (".docx", ".doc") or "word" in ext:
                return "docx"

        # Fallback: check magic bytes
        magic = buffer.getbuffer()[:8]
        if magic[:4] == b"%PDF":
            return "pdf"
        if magic[:2] in (b"PK",):  # DOCX files are ZIP archives (PK\x03\x04)
            return "docx"

        # Last resort: check URL string
        url_lower = url.lower()
        if ".pdf" in url_lower:
            return "pdf"
        if ".docx" in url_lower or ".doc" in url_lower:
            return "docx"

        logger.warning("Could not detect filetype for %s; assuming PDF.", url)
        return "pdf"

    def extract_text(
        self, buffer: io.BytesIO, url: str, max_pages: int = 3
    ) -> Optional[str]:
        """Extract plain text from an in-memory document.

        Args:
            buffer: BytesIO buffer containing the document bytes.
            url: Original URL (used for filetype detection).
            max_pages: Maximum number of pages to parse (PDF only).

        Returns:
            Extracted text as a single string, or None on failure.
        """
        filetype = self._detect_filetype(url, buffer)
        logger.info("Detected filetype: %s; max_pages=%d", filetype, max_pages)

        if filetype == "pdf":
            return self._extract_pdf_text(buffer, max_pages)
        elif filetype == "docx":
            return self._extract_docx_text(buffer)
        else:
            logger.error("Unsupported filetype: %s", filetype)
            return None

    def extract_text_with_blocks(
        self, buffer: io.BytesIO, url: str, max_pages: int = 3
    ) -> Optional[dict]:
        """Extract text with spatial block information (PDF only).

        Returns a dict with 'text' (full plain text) and 'blocks' (list of
        spatial text blocks), or None on failure.
        """
        filetype = self._detect_filetype(url, buffer)
        if filetype != "pdf":
            text = self.extract_text(buffer, url, max_pages)
            return {"text": text, "blocks": []} if text else None

        doc: Optional[fitz.Document] = None
        try:
            buffer.seek(0)
            doc = fitz.open(stream=buffer, filetype="pdf")

            all_text = []
            all_blocks = []
            for page_num in range(min(len(doc), max_pages)):
                page = doc[page_num]
                all_text.append(page.get_text())
                blocks = page.get_text("blocks")
                for b in blocks:
                    all_blocks.append(
                        {
                            "page": page_num,
                            "x0": b[0],
                            "y0": b[1],
                            "x1": b[2],
                            "y1": b[3],
                            "text": b[4],
                            "block_type": b[6],
                        }
                    )

            return {"text": "\n".join(all_text), "blocks": all_blocks}

        except Exception as e:
            logger.exception("Failed to extract PDF blocks: %s", e)
            return None
        finally:
            if doc is not None:
                doc.close()

    def _extract_pdf_text(self, buffer: io.BytesIO, max_pages: int) -> Optional[str]:
        """Extract plain text from a PDF in-memory."""
        doc: Optional[fitz.Document] = None
        try:
            buffer.seek(0)
            doc = fitz.open(stream=buffer, filetype="pdf")
            total_pages = len(doc)
            pages_to_read = min(total_pages, max_pages)
            logger.info("PDF has %d pages; reading first %d", total_pages, pages_to_read)

            text_parts = []
            for page_num in range(pages_to_read):
                page = doc[page_num]
                text_parts.append(page.get_text())

            return "\n".join(text_parts)

        except Exception as e:
            logger.exception("Failed to extract PDF text: %s", e)
            return None
        finally:
            if doc is not None:
                doc.close()

    def _extract_docx_text(self, buffer: io.BytesIO) -> Optional[str]:
        """Extract plain text from a DOCX in-memory."""
        try:
            buffer.seek(0)
            doc = DocxDocument(buffer)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            logger.info("Extracted %d paragraphs from DOCX.", len(paragraphs))
            return "\n".join(paragraphs)

        except Exception as e:
            logger.exception("Failed to extract DOCX text: %s", e)
            return None

