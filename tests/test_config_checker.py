import os
import unittest
from unittest.mock import patch

from biz.utils.config_checker import check_llm_provider


class ConfigCheckerTest(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"LLM_PROVIDER": "codex_runner", "CODEX_RUNNER_URL": "http://runner/review"},
        clear=False,
    )
    def test_accepts_codex_runner_provider(self):
        self.assertTrue(check_llm_provider())


if __name__ == "__main__":
    unittest.main()
