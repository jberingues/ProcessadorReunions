"""Tests per a la heurística d'adjunts inline (logos de signatura)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gmail_fetcher import is_inline_attachment


class TestIsInlineAttachment(unittest.TestCase):
    def test_inline_image_with_cid_is_filtered(self):
        # Cas típic d'un logo de firma.
        headers = {
            'content-type': 'image/png; name="logo.png"',
            'content-disposition': 'inline; filename="logo.png"',
            'content-id': '<image001@example.com>',
        }
        self.assertTrue(is_inline_attachment(headers, 'image/png'))

    def test_attachment_image_not_filtered(self):
        # Imatge adjuntada explícitament (no inline).
        headers = {
            'content-type': 'image/jpeg',
            'content-disposition': 'attachment; filename="foto.jpg"',
        }
        self.assertFalse(is_inline_attachment(headers, 'image/jpeg'))

    def test_inline_image_without_cid_not_filtered(self):
        # Inline però sense Content-ID — no és segur que sigui un logo.
        headers = {
            'content-type': 'image/png',
            'content-disposition': 'inline; filename="foto.png"',
        }
        self.assertFalse(is_inline_attachment(headers, 'image/png'))

    def test_pdf_with_cid_not_filtered(self):
        # PDF amb Content-ID (cas rar) NO és un logo.
        headers = {
            'content-type': 'application/pdf',
            'content-disposition': 'inline',
            'content-id': '<doc1@example.com>',
        }
        self.assertFalse(is_inline_attachment(headers, 'application/pdf'))

    def test_docx_attachment_not_filtered(self):
        headers = {
            'content-disposition': 'attachment; filename="informe.docx"',
        }
        self.assertFalse(is_inline_attachment(
            headers,
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        ))

    def test_image_without_disposition_not_filtered(self):
        # Sense Content-Disposition (cas rar) — conservador: no filtrar.
        headers = {'content-type': 'image/png'}
        self.assertFalse(is_inline_attachment(headers, 'image/png'))

    def test_case_insensitive_disposition_value(self):
        headers = {
            'content-disposition': 'INLINE; filename="x.png"',
            'content-id': '<x@example.com>',
        }
        self.assertTrue(is_inline_attachment(headers, 'image/png'))


if __name__ == "__main__":
    unittest.main()
