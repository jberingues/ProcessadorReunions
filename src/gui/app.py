#!/usr/bin/env python3
import os
import sys

# Afegeix src/ al sys.path per mantenir els imports existents
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import litellm
from dotenv import load_dotenv

litellm.drop_params = True

# Patch CrewAI LLM per eliminar el paràmetre 'stop' que alguns models no suporten
from crewai import LLM as CrewLLM
_orig_prepare = CrewLLM._prepare_completion_params
def _patched_prepare(self, messages, tools=None):
    params = _orig_prepare(self, messages, tools)
    params.pop('stop', None)
    return params
CrewLLM._prepare_completion_params = _patched_prepare

# Carregar .env des de l'arrel del projecte (2 nivells amunt de src/gui/)
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_project_root, '.env'))

from PySide6.QtWidgets import QApplication
from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Processador de Reunions")

    vault = os.getenv('OBSIDIAN_VAULT_PATH')
    if not vault:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Error", "OBSIDIAN_VAULT_PATH no configurat al .env")
        sys.exit(1)

    window = MainWindow(vault)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
