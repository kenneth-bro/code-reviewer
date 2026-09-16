import os
from typing import Dict, List, Optional

from openai import OpenAI

from biz.llm.client.base import BaseClient
from biz.llm.types import NotGiven, NOT_GIVEN


class OpenAIClient(BaseClient):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com")
        if not self.api_key:
            raise ValueError(
                "API key is required. Please provide it or set it in the environment variables."
            )

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.default_model = os.getenv("OPENAI_API_MODEL", "gpt-4o-mini")
        self.reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT")

    def completions(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] | NotGiven = NOT_GIVEN,
    ) -> str:
        model = model or self.default_model
        kwargs = {"model": model, "messages": messages}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        completion = self.client.chat.completions.create(**kwargs)
        return completion.choices[0].message.content
