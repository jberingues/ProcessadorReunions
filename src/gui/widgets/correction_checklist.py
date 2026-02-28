from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QCheckBox, QLabel, QPushButton, QLineEdit
)
from PySide6.QtCore import Qt


class CorrectionItem(QFrame):
    def __init__(self, correction: dict, parent=None):
        super().__init__(parent)
        self.correction = correction
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setStyleSheet("CorrectionItem { border: 1px solid #ccc; border-radius: 4px; padding: 6px; margin: 2px; }")

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Fila superior: checkbox aprovació + text correcció
        top_row = QHBoxLayout()
        self.approve_cb = QCheckBox()
        self.approve_cb.setChecked(True)
        top_row.addWidget(self.approve_cb)

        change_text = f'"{correction["original"]}" \u2192 "{correction["correccio"]}"'
        reason = correction.get("motiu", "")
        if reason:
            change_text += f"  ({reason})"
        change_label = QLabel(change_text)
        change_label.setWordWrap(True)
        top_row.addWidget(change_label, 1)
        layout.addLayout(top_row)

        # Context
        frase = correction.get("frase", "")
        if frase:
            highlighted = frase.replace(
                correction["original"],
                f'<b style="color:#2196F3">{correction["original"]}</b>',
                1
            )
            context_label = QLabel(f'<span style="color:#666">...{highlighted}...</span>')
            context_label.setWordWrap(True)
            context_label.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(context_label)

        # Fila inferior: botó editar + checkbox memoritzar
        bottom_row = QHBoxLayout()

        self.edit_btn = QPushButton("Editar")
        self.edit_btn.setFixedWidth(60)
        self.edit_btn.clicked.connect(self._toggle_edit)
        bottom_row.addWidget(self.edit_btn)

        self.edit_field = QLineEdit(correction["correccio"])
        self.edit_field.setVisible(False)
        self.edit_field.returnPressed.connect(self._confirm_edit)
        bottom_row.addWidget(self.edit_field, 1)

        self.memorize_cb = QCheckBox("Memoritzar")
        bottom_row.addWidget(self.memorize_cb)

        layout.addLayout(bottom_row)

    def _toggle_edit(self):
        visible = not self.edit_field.isVisible()
        self.edit_field.setVisible(visible)
        if visible:
            self.edit_field.setFocus()
            self.edit_btn.setText("OK")
        else:
            self._confirm_edit()

    def _confirm_edit(self):
        new_text = self.edit_field.text().strip()
        if new_text:
            self.correction["correccio"] = new_text
        self.edit_field.setVisible(False)
        self.edit_btn.setText("Editar")

    def is_approved(self) -> bool:
        return self.approve_cb.isChecked()

    def should_memorize(self) -> bool:
        return self.memorize_cb.isChecked()

    def get_correction(self) -> dict:
        return self.correction


class CorrectionChecklist(QWidget):
    def __init__(self, corrections: list[dict], parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Botons seleccionar/deseleccionar
        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Seleccionar tot")
        select_all_btn.clicked.connect(self.select_all)
        deselect_all_btn = QPushButton("Deseleccionar tot")
        deselect_all_btn.clicked.connect(self.deselect_all)
        btn_row.addWidget(select_all_btn)
        btn_row.addWidget(deselect_all_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Scroll area amb els items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        self.items_layout = QVBoxLayout(scroll_widget)
        self.items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.items: list[CorrectionItem] = []
        for c in corrections:
            item = CorrectionItem(c)
            self.items.append(item)
            self.items_layout.addWidget(item)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def select_all(self):
        for item in self.items:
            item.approve_cb.setChecked(True)

    def deselect_all(self):
        for item in self.items:
            item.approve_cb.setChecked(False)

    def get_approved_corrections(self) -> list[dict]:
        """Retorna les correccions aprovades amb info de memorització."""
        result = []
        for item in self.items:
            if item.is_approved():
                c = item.get_correction().copy()
                c["memorize"] = item.should_memorize()
                result.append(c)
        return result
