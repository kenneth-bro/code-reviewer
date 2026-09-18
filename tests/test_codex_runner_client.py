import unittest
from unittest.mock import Mock, patch

from biz.llm.client.codex_runner import CodexRunnerClient


class CodexRunnerClientTest(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "CODEX_RUNNER_URL": "http://host.docker.internal:8790/review",
            "CODEX_RUNNER_TOKEN": "runner-token",
            "CODEX_RUNNER_TIMEOUT_SECONDS": "12",
        },
        clear=False,
    )
    @patch("biz.llm.client.codex_runner.requests.post")
    def test_posts_messages_to_runner(self, post):
        response = Mock()
        response.json.return_value = {"content": "{\"score\": 95}"}
        post.return_value = response

        result = CodexRunnerClient().completions(
            [{"role": "user", "content": "review this"}]
        )

        self.assertEqual(result, '{"score": 95}')
        post.assert_called_once_with(
            "http://host.docker.internal:8790/review",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer runner-token",
            },
            json={"messages": [{"role": "user", "content": "review this"}]},
            timeout=12.0,
        )
        response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
