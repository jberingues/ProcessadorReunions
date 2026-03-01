from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QLabel
from PySide6.QtGui import QFont, QFontDatabase


class TranscriptEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setPlaceholderText("Enganxa la transcripció aquí...")
        self.editor.textChanged.connect(self._update_count)

        self.count_label = QLabel("0 línies")

        layout.addWidget(self.editor)
        layout.addWidget(self.count_label)

    def _update_count(self):
        text = self.editor.toPlainText()
        n = len(text.splitlines()) if text.strip() else 0
        self.count_label.setText(f"{n} línies")

    def get_text(self) -> str:
        return self.editor.toPlainText().strip()

    def clear(self):
        self.editor.clear()
