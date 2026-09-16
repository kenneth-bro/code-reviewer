import unittest
from unittest.mock import Mock, patch

from biz.llm.client.openai import OpenAIClient


class OpenAIClientTest(unittest.TestCase):
    @patch("biz.llm.client.openai.OpenAI")
    @patch.dict(
        "os.environ",
        {
            "OPENAI_API_KEY": "test",
            "OPENAI_API_MODEL": "gpt-5.6-luna",
            "OPENAI_REASONING_EFFORT": "max",
        },
        clear=True,
    )
    def test_passes_configured_reasoning_effort(self, openai):
        completion = Mock()
        completion.choices = [Mock(message=Mock(content="ok"))]
        openai.return_value.chat.completions.create.return_value = completion

        OpenAIClient().completions([{"role": "user", "content": "hello"}])

        openai.return_value.chat.completions.create.assert_called_once_with(
            model="gpt-5.6-luna",
            messages=[{"role": "user", "content": "hello"}],
            reasoning_effort="max",
        )


if __name__ == "__main__":
    unittest.main()
