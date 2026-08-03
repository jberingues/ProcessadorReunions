"""Fa que una finestra de nivell superior es pugui arrossegar amb el ratolí
des de qualsevol zona buida del cos, no només des de la barra de títol.

Motiu: en alguns entorns macOS l'arrossegament natiu de la barra de títol no
respon i la finestra queda "enganxada". `QWidget.move()` reposiciona la finestra
incondicionalment, així que capturem el drag a nivell de Qt i la movem nosaltres.

`install_window_drag(window)` embolcalla els gestors de ratolí del top-level.
Com que els widgets fills consumeixen els seus propis esdeveniments de ratolí,
aquests gestors només s'activen quan es clica en una zona buida de la finestra
(marges i separacions dels layouts) — no interfereix amb botons, taules ni text.
No toca la barra de títol nativa: si ja funciona, això només afegeix una via
extra per moure la finestra.
"""
from PySide6.QtCore import Qt


def install_window_drag(window) -> None:
    window._drag_offset = None

    _orig_press = window.mousePressEvent
    _orig_move = window.mouseMoveEvent
    _orig_release = window.mouseReleaseEvent

    def press(event):
        if event.button() == Qt.LeftButton:
            window._drag_offset = (
                event.globalPosition().toPoint()
                - window.frameGeometry().topLeft()
            )
        _orig_press(event)

    def move(event):
        if window._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            window.move(event.globalPosition().toPoint() - window._drag_offset)
            event.accept()
            return
        _orig_move(event)

    def release(event):
        window._drag_offset = None
        _orig_release(event)

    window.mousePressEvent = press
    window.mouseMoveEvent = move
    window.mouseReleaseEvent = release
