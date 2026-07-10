"""Preview visual de PairingView. Executar amb:
    uv run python preview_pairing.py
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent  # arrel del repo (script viu a scripts/)
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "gui"))

load_dotenv(ROOT / ".env")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from calendar_matcher import CalendarMatcher  # noqa: E402
from plaud_client import PlaudClient  # noqa: E402
from widgets.pairing_view import PairingView  # noqa: E402


def main():
    app = QApplication(sys.argv)

    print("Inicialitzant CalendarMatcher...")
    calendar = CalendarMatcher()
    plaud = PlaudClient()

    win = QMainWindow()
    win.setWindowTitle("Preview: PairingView")
    win.resize(1200, 750)

    central = QWidget()
    layout = QVBoxLayout(central)

    view = PairingView(calendar, plaud)
    layout.addWidget(view)

    btn = QPushButton("Mostrar estat actual")

    def show_state():
        pairs, unmatched_events, unmatched_recs = view.get_state()
        lines = [f"PARELLS: {len(pairs)}"]
        for p in pairs:
            lines.append(
                f"  [{p.status.value} {p.score:.0%}] "
                f"{p.event.get('title', '?')} ←→ {p.recording.name[:60]}"
            )
        lines.append(f"\nREUNIONS SENSE GRAVACIÓ: {len(unmatched_events)}")
        for e in unmatched_events:
            lines.append(f"  - {e.get('title', '?')}")
        lines.append(f"\nGRAVACIONS SENSE REUNIÓ: {len(unmatched_recs)}")
        for r in unmatched_recs:
            lines.append(f"  - {r.name[:60]}")
        QMessageBox.information(win, "Estat de PairingView", "\n".join(lines))

    btn.clicked.connect(show_state)
    layout.addWidget(btn)

    win.setCentralWidget(central)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
