from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QCheckBox
)
from PySide6.QtGui import QTextCharFormat, QColor, QFont, QTextCursor, QFontDatabase
from PySide6.QtCore import Qt, QTimer


class InlineCorrectionEditor(QWidget):
    """Editor de text amb correccions resaltades inline.

    Layout del nav bar (3 files):
      Fila 1: [←]  [2/5 · 3 pend.]  [→]
      Fila 2: "original" → "correcció"  (motiu)
      Fila 3: [□ Mem]  [✓ Acceptar]  [✗ Rebutjar]  "Canvi acceptat / rebutjat"

    Status de cada correcció:
      pending   : pendent de revisió
      accepted  : acceptada (highlight verd sobre 'correccio')
      rejected  : rebutjada (highlight gris sobre 'original')
      manual    : l'usuari ha editat el text i l'original ja no existeix
      not_found : l'original no s'ha trobat en intentar aplicar la correcció

    Colors:
      Actual    : taronja  #FF9800
      Pendent   : groc     #FFE082
      Acceptada : verd     #C8E6C9
      Rebutjada : gris     #EEEEEE
    """

    _COL_CURRENT  = QColor('#FF9800')
    _COL_PENDING  = QColor('#FFE082')
    _COL_ACCEPTED = QColor('white')
    _COL_REJECTED = QColor('white')

    def __init__(self, transcript: str, corrections: list[dict], parent=None):
        super().__init__(parent)
        self._corrections = [dict(c, status='pending') for c in corrections]
        self._memorized: list[dict] = []
        self._current = 0 if corrections else -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if corrections:
            self._build_nav_bar(layout)

        self.editor = QTextEdit()
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setPlainText(transcript)
        layout.addWidget(self.editor)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._update_highlights)

        if corrections:
            self.editor.textChanged.connect(lambda: self._timer.start())
            self._refresh()

    # ── Nav bar (3 files) ────────────────────────────────────────────────────

    def _build_nav_bar(self, parent_layout: QVBoxLayout):
        # Fila 1: navegació
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self.btn_prev = QPushButton("←")
        self.btn_prev.setFixedWidth(32)
        self.btn_prev.setToolTip("Correcció anterior")
        self.btn_prev.clicked.connect(self._go_prev)

        self.lbl_counter = QLabel()
        self.lbl_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_counter.setMinimumWidth(130)

        self.btn_next = QPushButton("→")
        self.btn_next.setFixedWidth(32)
        self.btn_next.setToolTip("Correcció següent")
        self.btn_next.clicked.connect(self._go_next)

        row1.addWidget(self.btn_prev)
        row1.addWidget(self.lbl_counter)
        row1.addWidget(self.btn_next)
        row1.addStretch()
        parent_layout.addLayout(row1)

        # Fila 2: descripció de la correcció (text complet)
        self.lbl_correction = QLabel()
        self.lbl_correction.setWordWrap(True)
        self.lbl_correction.setStyleSheet("padding: 2px 0;")
        parent_layout.addWidget(self.lbl_correction)

        # Fila 3: botons + estat
        row3 = QHBoxLayout()
        row3.setSpacing(6)

        self.chk_mem = QCheckBox("Memoritzar")

        self.btn_accept = QPushButton("✓ Acceptar")
        self.btn_accept.setStyleSheet(
            "background:#4CAF50; color:white; font-weight:bold; padding:4px 10px;"
        )
        self.btn_accept.clicked.connect(self._accept_current)

        self.btn_reject = QPushButton("✗ Rebutjar")
        self.btn_reject.setStyleSheet(
            "background:#F44336; color:white; padding:4px 10px;"
        )
        self.btn_reject.clicked.connect(self._reject_current)

        self.lbl_status = QLabel()

        row3.addWidget(self.chk_mem)
        row3.addWidget(self.btn_accept)
        row3.addWidget(self.btn_reject)
        row3.addWidget(self.lbl_status)
        row3.addStretch()
        parent_layout.addLayout(row3)

    # ── Navegació ────────────────────────────────────────────────────────────

    def _go_prev(self):
        if self._current > 0:
            self._current -= 1
            self._refresh()

    def _go_next(self):
        if self._current < len(self._corrections) - 1:
            self._current += 1
            self._refresh()

    # ── Acceptar / Rebutjar ──────────────────────────────────────────────────

    def _accept_current(self):
        c = self._corrections[self._current]
        was_pending = c['status'] == 'pending'

        if c['status'] == 'accepted':
            return

        if c['status'] == 'rejected':
            # Desfer rebuig: cercar original i substituir per correcció
            cursor = self.editor.document().find(c['original'])
            if not cursor.isNull():
                cursor.insertText(c['correccio'])
        else:  # pending / not_found
            cursor = self.editor.document().find(c['original'])
            if not cursor.isNull():
                cursor.insertText(c['correccio'])
            else:
                c['status'] = 'not_found'
                self._refresh()
                return

        c['status'] = 'accepted'

        if self.chk_mem.isChecked():
            if not any(m['original'] == c['original'] for m in self._memorized):
                self._memorized.append({'original': c['original'], 'correccio': c['correccio']})

        self.chk_mem.setChecked(False)

        if was_pending:
            self._move_to_next_pending()
        else:
            self._refresh()

    def _reject_current(self):
        c = self._corrections[self._current]
        was_pending = c['status'] == 'pending'

        if c['status'] == 'rejected':
            return

        if c['status'] == 'accepted':
            # Desfer acceptació: cercar correcció i restaurar original
            cursor = self.editor.document().find(c['correccio'])
            if not cursor.isNull():
                cursor.insertText(c['original'])

        c['status'] = 'rejected'
        self.chk_mem.setChecked(False)

        if was_pending:
            self._move_to_next_pending()
        else:
            self._refresh()

    def _move_to_next_pending(self):
        n = len(self._corrections)
        for i in range(self._current + 1, n):
            if self._corrections[i]['status'] == 'pending':
                self._current = i
                self._refresh()
                return
        for i in range(0, self._current):
            if self._corrections[i]['status'] == 'pending':
                self._current = i
                self._refresh()
                return
        self._refresh()  # cap pendent

    # ── Actualitzar UI ───────────────────────────────────────────────────────

    def _refresh(self):
        self._update_nav_info()
        self._update_highlights()
        self._scroll_to_current()

    def _update_nav_info(self):
        n = len(self._corrections)
        pending = sum(1 for c in self._corrections if c['status'] == 'pending')
        suffix = f" · {pending} pend." if pending > 0 else " · tot resolt"
        self.lbl_counter.setText(f"{self._current + 1} / {n}{suffix}")

        if 0 <= self._current < n:
            c = self._corrections[self._current]
            motiu = c.get('motiu', '')
            text = f'"{c["original"]}"  →  "{c["correccio"]}"'
            if motiu:
                text += f'  ({motiu})'
            self.lbl_correction.setText(text)

            status = c['status']
            blocked = status in ('manual', 'not_found')
            self.btn_accept.setEnabled(status != 'accepted' and not blocked)
            self.btn_reject.setEnabled(status != 'rejected' and not blocked)
            self.chk_mem.setEnabled(status == 'pending')

            if status == 'accepted':
                self.lbl_status.setText("✓ Canvi acceptat")
                self.lbl_status.setStyleSheet("color:#388E3C; font-style:italic;")
            elif status == 'rejected':
                self.lbl_status.setText("✗ Canvi rebutjat")
                self.lbl_status.setStyleSheet("color:#B71C1C; font-style:italic;")
            elif status == 'manual':
                self.lbl_status.setText("✏ Modificat manualment")
                self.lbl_status.setStyleSheet("color:#1976D2; font-style:italic;")
            elif status == 'not_found':
                self.lbl_status.setText("⚠ No trobat al text")
                self.lbl_status.setStyleSheet("color:#FF9800; font-style:italic;")
            else:
                self.lbl_status.setText("")

        self.btn_prev.setEnabled(self._current > 0)
        self.btn_next.setEnabled(self._current < n - 1)

    def _update_highlights(self):
        doc = self.editor.document()

        # Pas 1: detectar correccions pendents que l'usuari ha editat manualment
        nav_needs_update = False
        for i, c in enumerate(self._corrections):
            if c['status'] == 'pending' and doc.find(c['original']).isNull():
                c['status'] = 'manual'
                if i == self._current:
                    nav_needs_update = True

        if nav_needs_update:
            self._update_nav_info()

        # Pas 2: dibuixar highlights
        #   pending   → cerca 'original'  (groc / taronja si és actual)
        #   accepted  → cerca 'correccio' (verd  / taronja si és actual)
        #   rejected  → cerca 'original'  (gris  / taronja si és actual)
        #   manual / not_found → sense highlight
        selections = []
        for i, c in enumerate(self._corrections):
            status = c['status']
            is_current = (i == self._current)

            if status == 'pending':
                search_text = c['original']
                color = self._COL_CURRENT if is_current else self._COL_PENDING
            elif status == 'accepted':
                search_text = c['correccio']
                color = self._COL_CURRENT if is_current else self._COL_ACCEPTED
            elif status == 'rejected':
                search_text = c['original']
                color = self._COL_CURRENT if is_current else self._COL_REJECTED
            elif status == 'manual':
                # Intentem trobar la correcció suggerida; si l'usuari ha escrit
                # una altra cosa no podem saber on és, i no es ressaltarà res.
                search_text = c['correccio']
                color = self._COL_CURRENT if is_current else self._COL_ACCEPTED
            else:
                continue  # not_found

            fmt = QTextCharFormat()
            fmt.setBackground(color)
            fmt.setForeground(QColor('black'))
            if is_current:
                fmt.setFontWeight(700)

            cursor = doc.find(search_text)
            while not cursor.isNull():
                sel = QTextEdit.ExtraSelection()
                sel.format = fmt
                sel.cursor = cursor
                selections.append(sel)
                cursor = doc.find(search_text, cursor)

        self.editor.setExtraSelections(selections)

    def _scroll_to_current(self):
        if self._current < 0:
            return
        c = self._corrections[self._current]

        if c['status'] in ('accepted', 'manual'):
            search_text = c['correccio']
        elif c['status'] in ('pending', 'rejected'):
            search_text = c['original']
        else:
            return  # not_found: no podem fer scroll

        found = self.editor.document().find(search_text)
        if found.isNull():
            return
        # Cursor sense selecció per no sobreposar al highlight
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(found.anchor())
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    # ── API pública ──────────────────────────────────────────────────────────

    def get_final_text(self) -> str:
        return self.editor.toPlainText()

    def get_memorize_list(self) -> list[dict]:
        return list(self._memorized)
