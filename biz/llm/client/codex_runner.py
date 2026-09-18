import os

import requests

from biz.llm.client.base import BaseClient
from biz.llm.types import NotGiven, NOT_GIVEN


class CodexRunnerClient(BaseClient):
    """Call a host-side Codex Runner over HTTP."""

    def __init__(self):
        self.url = os.getenv("CODEX_RUNNER_URL", "").rstrip("/")
        self.token = os.getenv("CODEX_RUNNER_TOKEN", "")
        self.timeout = float(os.getenv("CODEX_RUNNER_TIMEOUT_SECONDS", "900"))
        if not self.url:
            raise ValueError("CODEX_RUNNER_URL is required when LLM_PROVIDER=codex_runner")

    def completions(
        self,
        messages: list[dict[str, str]],
        model: str | NotGiven = NOT_GIVEN,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = {"messages": messages}
        if model is not NOT_GIVEN:
            payload["model"] = model

        response = requests.post(
            self.url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Codex Runner response does not contain non-empty content")
        return content
