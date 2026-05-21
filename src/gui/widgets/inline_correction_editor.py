from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QRadioButton, QButtonGroup, QLineEdit
)
from PySide6.QtGui import QTextCharFormat, QColor, QFont, QTextCursor, QTextDocument, QFontDatabase
from PySide6.QtCore import Qt, QTimer, QRegularExpression
import re as _re


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
      validated : l'usuari ha confirmat que la paraula original és correcta
                  (s'afegirà al Vocabulari com a terme principal, no és error)
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

    _FIND_FLAGS = (
        QTextDocument.FindFlag.FindCaseSensitively
        | QTextDocument.FindFlag.FindWholeWords
    )

    def __init__(self, transcript: str, corrections: list[dict], parent=None,
                 threshold_auto: float = 1.1):
        super().__init__(parent)
        # scope per correcció: 'none' (no memoritzar) | 'series' (semantic_memory.json local)
        # | 'global' (alias al Vocabulari.md). Per defecte 'none' per evitar acumulació
        # de brossa per inèrcia — l'usuari ha de triar conscientment.
        self._corrections = [dict(c, status='pending', scope='none') for c in corrections]
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
            self._auto_accept_high_confidence(threshold_auto)
            # Posicionar-se a la primera pendent
            first_pending = next(
                (i for i, c in enumerate(self._corrections) if c['status'] == 'pending'),
                -1 if not self._corrections else 0
            )
            self._current = first_pending
            self.editor.textChanged.connect(lambda: self._timer.start())
            self._refresh()

    # ── Auto-acceptació ──────────────────────────────────────────────────────

    def _auto_accept_high_confidence(self, threshold: float):
        """Accepta automàticament les correccions amb confiança >= threshold i les elimina de la llista."""
        remaining = []
        for c in self._corrections:
            if c.get('confiança', 0) >= threshold:
                self._replace_all_whole_word(c['original'], c['correccio'])
                # no s'afegeix a remaining: desapareix de la llista
            else:
                remaining.append(c)
        self._corrections = remaining

    # ── Reemplaçament global ─────────────────────────────────────────────────

    def _replace_all_whole_word(self, find_text: str, replace_text: str) -> int:
        """Reemplaça totes les ocurrències de find_text (paraula sencera,
        case-sensitive) per replace_text al document. Retorna el nombre de canvis.

        Per a frases multi-paraula usa regex amb word boundaries als extrems,
        perquè QTextDocument.FindWholeWords no funciona bé amb cadenes que
        contenen espais.
        """
        if not find_text:
            return 0
        doc = self.editor.document()
        cursor = self._find_in_doc(doc, find_text, 0)
        count = 0
        while not cursor.isNull():
            cursor.insertText(replace_text)
            count += 1
            cursor = self._find_in_doc(doc, find_text, cursor)
        return count

    def _find_in_doc(self, doc, find_text: str, start):
        """Cerca find_text al document respectant word boundaries. Funciona
        tant per a paraules soles com per a frases multi-paraula."""
        if ' ' not in find_text:
            return doc.find(find_text, start, self._FIND_FLAGS)
        # Frase amb espais: regex amb límits de paraula als extrems
        pattern = r'(?<!\w)' + _re.escape(find_text) + r'(?!\w)'
        qre = QRegularExpression(pattern)
        return doc.find(qre, start)

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

        # Fila 2: descripció de la correcció amb el target editable
        # L'usuari pot modificar la proposta del LLM abans d'acceptar (només en
        # estat 'pending'). En altres estats el camp és read-only.
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        self.lbl_original = QLabel()
        self.lbl_original.setStyleSheet("padding: 2px 0;")

        self.edit_correccio = QLineEdit()
        self.edit_correccio.setMinimumWidth(150)
        self.edit_correccio.setMaximumWidth(280)
        self.edit_correccio.textEdited.connect(self._on_correccio_edited)

        self.lbl_meta = QLabel()
        self.lbl_meta.setStyleSheet("color:#666; padding: 2px 0;")

        row2.addWidget(self.lbl_original)
        row2.addWidget(self.edit_correccio)
        row2.addWidget(self.lbl_meta)
        row2.addStretch()
        parent_layout.addLayout(row2)

        # Fila 3: botons + estat
        row3 = QHBoxLayout()
        row3.setSpacing(6)

        self.btn_accept = QPushButton("✓ Acceptar")
        self.btn_accept.setStyleSheet(
            "background:#4CAF50; color:white; font-weight:bold; padding:4px 10px;"
        )
        self.btn_accept.clicked.connect(self._accept_current)

        self.btn_validate = QPushButton("★ És correcta")
        self.btn_validate.setStyleSheet(
            "background:#1976D2; color:white; padding:4px 10px;"
        )
        self.btn_validate.setToolTip(
            "La paraula original ja és correcta. No la canviïs al text però "
            "afegeix-la al Vocabulari perquè no es torni a proposar."
        )
        self.btn_validate.clicked.connect(self._validate_current)

        self.btn_reject = QPushButton("✗ Rebutjar")
        self.btn_reject.setStyleSheet(
            "background:#F44336; color:white; padding:4px 10px;"
        )
        self.btn_reject.clicked.connect(self._reject_current)

        self.lbl_status = QLabel()

        # Memoritzar: 3 opcions de scope. Per defecte 'Cap' (no acumular brossa).
        self.lbl_mem_prefix = QLabel("Memoritzar:")
        self.lbl_mem_prefix.setStyleSheet("color:#555;")

        self.rb_none = QRadioButton("Cap")
        self.rb_series = QRadioButton("Aquesta sèrie")
        self.rb_global = QRadioButton("Sempre")
        self.rb_none.setToolTip("Aplica només a aquesta transcripció (default)")
        self.rb_series.setToolTip("Recordar al semantic_memory.json d'aquesta sèrie")
        self.rb_global.setToolTip("Recordar al Vocabulari.md global (totes les reunions)")

        self._scope_group = QButtonGroup(self)
        self._scope_group.addButton(self.rb_none)
        self._scope_group.addButton(self.rb_series)
        self._scope_group.addButton(self.rb_global)
        self.rb_none.setChecked(True)
        self._scope_group.buttonClicked.connect(self._on_scope_changed)

        row3.addWidget(self.btn_accept)
        row3.addWidget(self.btn_validate)
        row3.addWidget(self.btn_reject)
        row3.addWidget(self.lbl_status)
        row3.addStretch()
        row3.addWidget(self.lbl_mem_prefix)
        row3.addWidget(self.rb_none)
        row3.addWidget(self.rb_series)
        row3.addWidget(self.rb_global)
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
            # Desfer rebuig: substituir original per correcció a totes les ocurrències
            self._replace_all_whole_word(c['original'], c['correccio'])
        else:  # pending / not_found
            replaced = self._replace_all_whole_word(c['original'], c['correccio'])
            if replaced == 0:
                c['status'] = 'not_found'
                self._refresh()
                return

        c['status'] = 'accepted'
        # L'scope decidit es preserva (es llegirà al desar la revisió)

        if was_pending:
            self._move_to_next_pending()
        else:
            self._refresh()

    def _validate_current(self):
        """Marca l'`original` com a terme correcte del vocabulari.

        No toca el text (la paraula ja és correcta tal com és).
        S'afegirà a Vocabulari.md en desar la revisió.
        Si la correcció ja s'havia acceptat, primer cal desfer la substitució.
        """
        c = self._corrections[self._current]
        was_pending = c['status'] == 'pending'

        if c['status'] == 'validated':
            return

        if c['status'] == 'accepted':
            # Desfer acceptació: restaurar original a totes les ocurrències
            self._replace_all_whole_word(c['correccio'], c['original'])

        c['status'] = 'validated'
        c['scope'] = 'none'  # validated sempre va a Vocabulari, no usa scope

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
            # Desfer acceptació: restaurar original a totes les ocurrències
            self._replace_all_whole_word(c['correccio'], c['original'])

        c['status'] = 'rejected'
        c['scope'] = 'none'  # rebutjar implica no memoritzar

        if was_pending:
            self._move_to_next_pending()
        else:
            self._refresh()

    def _on_correccio_edited(self, text: str):
        """L'usuari ha modificat la proposta de correcció (QLineEdit)."""
        if 0 <= self._current < len(self._corrections):
            c = self._corrections[self._current]
            # Permetem edició mentre no sigui un estat tancat
            if c['status'] not in ('accepted', 'rejected', 'validated'):
                c['correccio'] = text
                # El text de memorització fa referència al target → actualitzar
                self.lbl_mem_prefix.setText(
                    f'Memoritzar "{c["original"]}" → "{text}":'
                )

    def _on_scope_changed(self, button):
        if 0 <= self._current < len(self._corrections):
            if button is self.rb_global:
                self._corrections[self._current]['scope'] = 'global'
            elif button is self.rb_series:
                self._corrections[self._current]['scope'] = 'series'
            else:
                self._corrections[self._current]['scope'] = 'none'

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
            confiança = c.get('confiança')

            self.lbl_original.setText(f'"{c["original"]}"  →')

            # Camp editable amb el target. blockSignals per evitar el handler
            # quan és canvi programàtic (navegació entre correccions).
            self.edit_correccio.blockSignals(True)
            if self.edit_correccio.text() != c['correccio']:
                self.edit_correccio.setText(c['correccio'])
            # Editable si encara es pot acceptar (no és definitivament accepted/
            # rejected/validated). Inclou 'manual' i 'not_found' perquè l'usuari
            # pugui retallar la proposta i tornar a intentar acceptar-la.
            self.edit_correccio.setReadOnly(c['status'] in ('accepted', 'rejected', 'validated'))
            self.edit_correccio.blockSignals(False)

            parts = []
            if confiança is not None:
                parts.append(f'confiança: {confiança:.0%}')
            if motiu:
                parts.append(motiu)
            self.lbl_meta.setText(f'({", ".join(parts)})' if parts else '')

            status = c['status']
            # No deshabilitem els botons en `manual`/`not_found` perquè l'usuari
            # sempre ha de poder avançar: rebutjar la proposta o validar la
            # paraula original com a correcta. Si intenta Acceptar i no s'ha
            # pogut substituir, el handler ja marca `not_found` informativament.
            self.btn_accept.setEnabled(status != 'accepted')
            self.btn_validate.setEnabled(status != 'validated')
            self.btn_reject.setEnabled(status != 'rejected')

            # Memorització: visible quan la correcció pot acabar acceptada com a
            # alias (pending o accepted). 'validated' sempre va al Vocabulari
            # sense scope. 'manual'/'not_found' també permeten scope perquè
            # potser sí que es pot acceptar (lletra correcta al text).
            scope_visible = status in ('pending', 'accepted', 'manual', 'not_found')
            self.lbl_mem_prefix.setVisible(scope_visible)
            self.rb_none.setVisible(scope_visible)
            self.rb_series.setVisible(scope_visible)
            self.rb_global.setVisible(scope_visible)
            if scope_visible:
                self.lbl_mem_prefix.setText(f'Memoritzar "{c["original"]}" → "{c["correccio"]}":')
                self._scope_group.blockSignals(True)
                scope = c.get('scope', 'none')
                if scope == 'global':
                    self.rb_global.setChecked(True)
                elif scope == 'series':
                    self.rb_series.setChecked(True)
                else:
                    self.rb_none.setChecked(True)
                self._scope_group.blockSignals(False)

            if status == 'accepted':
                self.lbl_status.setText("✓ Canvi acceptat")
                self.lbl_status.setStyleSheet("color:#388E3C; font-style:italic;")
            elif status == 'validated':
                self.lbl_status.setText("★ Validada com a correcta")
                self.lbl_status.setStyleSheet("color:#1976D2; font-style:italic;")
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
            if c['status'] == 'pending' and self._find_in_doc(doc, c['original'], 0).isNull():
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
            elif status == 'validated':
                # Highlight blau suau sobre la paraula original validada
                search_text = c['original']
                color = self._COL_CURRENT if is_current else QColor('#BBDEFB')
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

            cursor = self._find_in_doc(doc, search_text, 0)
            while not cursor.isNull():
                sel = QTextEdit.ExtraSelection()
                sel.format = fmt
                sel.cursor = cursor
                selections.append(sel)
                cursor = self._find_in_doc(doc, search_text, cursor)

        self.editor.setExtraSelections(selections)

    def _scroll_to_current(self):
        if self._current < 0:
            return
        c = self._corrections[self._current]

        if c['status'] in ('accepted', 'manual'):
            search_text = c['correccio']
        elif c['status'] in ('pending', 'rejected', 'validated'):
            search_text = c['original']
        else:
            return  # not_found: no podem fer scroll

        found = self._find_in_doc(self.editor.document(), search_text, 0)
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

    def get_memorize_global(self) -> list[dict]:
        """Correccions a memoritzar al Vocabulari.md (alias global)."""
        return [
            {'original': c['original'], 'correccio': c['correccio']}
            for c in self._corrections
            if c['status'] == 'accepted' and c.get('scope') == 'global'
        ]

    def get_memorize_series(self) -> list[dict]:
        """Correccions a memoritzar al semantic_memory.json local d'aquesta sèrie."""
        return [
            {'original': c['original'], 'correccio': c['correccio']}
            for c in self._corrections
            if c['status'] == 'accepted' and c.get('scope') == 'series'
        ]

    def get_accepted_words(self) -> list[str]:
        """Retorna les paraules corregides de correccions acceptades."""
        return [c['correccio'] for c in self._corrections if c['status'] == 'accepted']

    def get_correct_words(self) -> list[str]:
        """Paraules originals marcades com a correctes (validades).

        Es desaran al Vocabulari.md com a termes principals (no com a aliases)
        perquè el sistema deixi de proposar-les com a errònies.
        """
        return [c['original'] for c in self._corrections if c['status'] == 'validated']
