"""Tests per a ObsidianWriter.create_email_thread_note."""
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter


def _msg(message_id, when: str, frm: str, subject: str, body: str,
         attachments=None) -> dict:
    return {
        'message_id': message_id,
        'date': datetime.fromisoformat(when),
        'from': frm,
        'to': '',
        'cc': '',
        'subject': subject,
        'body_text': body,
        'attachments': attachments or [],
    }


class TestCreateEmailThreadNote(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "Reunions" / "Seguiment" / "Joan").mkdir(parents=True)
        self.dest = self.tmp / "Reunions" / "Seguiment" / "Joan"
        self.writer = ObsidianWriter(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_single_message_no_attachments(self):
        thread = {
            'thread_id': 'th-1',
            'label_names': ['Seguiment/Joan'],
            'messages': [
                _msg('m1', '2026-05-20T09:15:00',
                     '"Jordi Beringues" <j@x.com>',
                     'Hola Joan', 'Tema important.'),
            ],
        }
        note_path, atts = self.writer.create_email_thread_note(
            thread, self.dest, primary_label='Seguiment/Joan'
        )
        self.assertEqual(atts, [])
        self.assertTrue(note_path.exists())
        self.assertEqual(note_path.name, "260520_Hola_Joan.md")
        content = note_path.read_text(encoding='utf-8')
        self.assertIn("type: correu", content)
        self.assertIn("thread_id: th-1", content)
        self.assertIn("data: 2026-05-20", content)
        self.assertIn('assumpte: "Hola Joan"', content)
        self.assertIn('labels:\n  - "Seguiment/Joan"', content)
        self.assertIn("tags: []", content)
        self.assertIn("## 2026-05-20 09:15 — Jordi Beringues <j@x.com>", content)
        self.assertIn("Tema important.", content)
        self.assertNotIn("(resposta)", content)

    def test_multi_message_marks_reply(self):
        thread = {
            'thread_id': 'th-2',
            'label_names': ['Seguiment/Joan'],
            'messages': [
                _msg('m1', '2026-05-20T09:00:00', 'Jordi <j@x.com>',
                     'Re: assumpte', 'primera'),
                _msg('m2', '2026-05-20T14:30:00', 'Joan <joan@x.com>',
                     'Re: assumpte', 'segona'),
            ],
        }
        note_path, _ = self.writer.create_email_thread_note(
            thread, self.dest, primary_label='Seguiment/Joan'
        )
        content = note_path.read_text(encoding='utf-8')
        self.assertEqual(note_path.name, "260520_assumpte.md")
        # Primer NO té (resposta), segon sí.
        self.assertIn("## 2026-05-20 09:00 — Jordi <j@x.com>\n", content)
        self.assertIn("## 2026-05-20 14:30 — Joan <joan@x.com> (resposta)", content)
        # Assumpte al frontmatter preserva l'original (amb Re:).
        self.assertIn('assumpte: "Re: assumpte"', content)

    def test_attachments_written_and_linked(self):
        thread = {
            'thread_id': 'th-3',
            'label_names': ['Seguiment/Joan'],
            'messages': [
                _msg('m1', '2026-05-20T09:00:00', 'a <a@x.com>',
                     'amb adjunts', 'Veure adjunt.',
                     attachments=[
                         {'filename': 'informe.pdf', 'mime': 'application/pdf', 'data': b'PDFDATA'},
                     ]),
            ],
        }
        note_path, atts = self.writer.create_email_thread_note(
            thread, self.dest, primary_label='Seguiment/Joan'
        )
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts[0].name, "260520_informe.pdf")
        self.assertEqual(atts[0].read_bytes(), b"PDFDATA")
        content = note_path.read_text(encoding='utf-8')
        self.assertIn("**Adjunts:**", content)
        self.assertIn("[[Fitxers/260520_informe.pdf]]", content)

    def test_regenerate_does_not_duplicate_attachments(self):
        # Primer fil
        thread1 = {
            'thread_id': 'th-4',
            'label_names': ['Seguiment/Joan'],
            'messages': [
                _msg('m1', '2026-05-20T09:00:00', 'a <a@x.com>',
                     'creixent', 'msg1',
                     attachments=[{'filename': 'x.pdf', 'mime': 'application/pdf', 'data': b'XX'}]),
            ],
        }
        self.writer.create_email_thread_note(thread1, self.dest, 'Seguiment/Joan')
        # Regenera amb un missatge més (mateix adjunt al m1).
        thread2 = {
            'thread_id': 'th-4',
            'label_names': ['Seguiment/Joan'],
            'messages': [
                _msg('m1', '2026-05-20T09:00:00', 'a <a@x.com>',
                     'creixent', 'msg1',
                     attachments=[{'filename': 'x.pdf', 'mime': 'application/pdf', 'data': b'XX'}]),
                _msg('m2', '2026-05-20T10:00:00', 'b <b@x.com>',
                     'Re: creixent', 'resposta'),
            ],
        }
        _, atts2 = self.writer.create_email_thread_note(thread2, self.dest, 'Seguiment/Joan')
        files = list((self.dest / "Fitxers").iterdir())
        self.assertEqual(len(files), 1)  # No s'ha duplicat
        self.assertEqual(files[0].name, "260520_x.pdf")
        self.assertEqual(atts2[0].name, "260520_x.pdf")

    def test_extra_labels_go_to_tags(self):
        thread = {
            'thread_id': 'th-5',
            'label_names': ['Projectes/X', 'Seguiment/Joan'],
            'messages': [
                _msg('m1', '2026-05-20T09:00:00', 'a <a@x.com>', 'multi', 'body'),
            ],
        }
        note_path, _ = self.writer.create_email_thread_note(
            thread, self.dest,
            primary_label='Projectes/X',
            extra_labels=['Seguiment/Joan'],
        )
        content = note_path.read_text(encoding='utf-8')
        self.assertIn('labels:\n  - "Projectes/X"', content)
        self.assertIn('tags:\n  - "Seguiment/Joan"', content)

    def test_overwrites_existing_note(self):
        thread1 = {
            'thread_id': 'th-6',
            'label_names': ['Seguiment/Joan'],
            'messages': [_msg('m1', '2026-05-20T09:00:00', 'a <a@x.com>', 'iter', 'v1')],
        }
        self.writer.create_email_thread_note(thread1, self.dest, 'Seguiment/Joan')
        thread2 = {
            **thread1,
            'messages': [
                _msg('m1', '2026-05-20T09:00:00', 'a <a@x.com>', 'iter', 'v1'),
                _msg('m2', '2026-05-21T09:00:00', 'b <b@x.com>', 'Re: iter', 'v2'),
            ],
        }
        note_path, _ = self.writer.create_email_thread_note(thread2, self.dest, 'Seguiment/Joan')
        content = note_path.read_text(encoding='utf-8')
        # Tots dos missatges presents.
        self.assertIn("v1", content)
        self.assertIn("v2", content)

    def test_empty_thread_raises(self):
        thread = {'thread_id': 't', 'label_names': [], 'messages': []}
        with self.assertRaises(ValueError):
            self.writer.create_email_thread_note(thread, self.dest, 'X')

    def test_subject_with_double_quote_escaped(self):
        thread = {
            'thread_id': 'th-7',
            'label_names': ['Seguiment/Joan'],
            'messages': [_msg('m1', '2026-05-20T09:00:00', 'a <a@x.com>',
                              'amb "quotes"', 'body')],
        }
        note_path, _ = self.writer.create_email_thread_note(thread, self.dest, 'Seguiment/Joan')
        content = note_path.read_text(encoding='utf-8')
        self.assertIn(r'assumpte: "amb \"quotes\""', content)


if __name__ == "__main__":
    unittest.main()
