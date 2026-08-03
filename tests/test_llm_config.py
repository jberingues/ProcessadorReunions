"""Tests de llm_config (tiering de models, reasoning effort, log de consum).

Executar amb: uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import llm_config
from llm_config import (
    log_completion_usage, log_crew_usage, model_hard, model_light, reasoning_effort,
)


class TestModelTiering(unittest.TestCase):
    def test_light_uses_modell_when_set(self):
        with patch.dict('os.environ', {'LLM_MODELL': 'mini', 'LLM_MODELH': 'gran'}):
            self.assertEqual(model_light(), 'mini')
            self.assertEqual(model_hard(), 'gran')

    def test_light_falls_back_to_modelh(self):
        with patch.dict('os.environ', {'LLM_MODELH': 'gran'}, clear=False):
            with patch.dict('os.environ'):
                import os
                os.environ.pop('LLM_MODELL', None)
                self.assertEqual(model_light(), 'gran')

    def test_light_empty_string_falls_back(self):
        with patch.dict('os.environ', {'LLM_MODELL': '', 'LLM_MODELH': 'gran'}):
            self.assertEqual(model_light(), 'gran')


class TestReasoningEffort(unittest.TestCase):
    def test_default_is_low(self):
        with patch.dict('os.environ'):
            import os
            os.environ.pop('LLM_REASONING_EFFORT', None)
            self.assertEqual(reasoning_effort(), 'low')

    def test_env_override(self):
        with patch.dict('os.environ', {'LLM_REASONING_EFFORT': 'high'}):
            self.assertEqual(reasoning_effort(), 'high')

    def test_empty_disables(self):
        # Valor buit → None (no s'envia el paràmetre; default del proveïdor).
        with patch.dict('os.environ', {'LLM_REASONING_EFFORT': ''}):
            self.assertIsNone(reasoning_effort())


class TestUsageLogging(unittest.TestCase):
    def test_log_crew_usage_emits_info(self):
        crew = SimpleNamespace(usage_metrics=SimpleNamespace(
            prompt_tokens=100, cached_prompt_tokens=20, completion_tokens=50,
            total_tokens=150, successful_requests=1,
        ))
        with self.assertLogs(llm_config.logger, level='INFO') as cm:
            log_crew_usage('prova', crew)
        self.assertIn('prompt=100', cm.output[0])
        self.assertIn('cache=20', cm.output[0])
        self.assertIn('[prova]', cm.output[0])

    def test_log_crew_usage_without_metrics_is_noop(self):
        log_crew_usage('prova', SimpleNamespace())  # no ha de petar

    def test_log_completion_usage_with_reasoning(self):
        response = SimpleNamespace(usage=SimpleNamespace(
            prompt_tokens=200, completion_tokens=80, total_tokens=280,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=30),
        ))
        with self.assertLogs(llm_config.logger, level='INFO') as cm:
            log_completion_usage('prova', response)
        self.assertIn('raonament=30', cm.output[0])
        self.assertIn('total=280', cm.output[0])

    def test_log_completion_usage_without_usage_is_noop(self):
        log_completion_usage('prova', SimpleNamespace(usage=None))  # no ha de petar


if __name__ == "__main__":
    unittest.main()
