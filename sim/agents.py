from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

from openrouter import OpenRouter


@dataclass
class ModelConfig:
    id: str
    model: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None


class LLMClient:
    def __init__(self, config: ModelConfig):
        self.config = config

    def chat(self, messages: List[Dict[str, str]]) -> str:
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ValueError("OpenRouter API key is missing. Set OPENROUTER_API_KEY.")

        with OpenRouter(api_key=api_key) as client:
            payload: Dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "temperature": self.config.temperature,
            }
            if self.config.max_tokens is not None:
                payload["max_tokens"] = self.config.max_tokens
            response = client.chat.send(**payload)
        return response.choices[0].message.content if response.choices else ""


def load_model_configs(path: str) -> Dict[str, ModelConfig]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    configs: Dict[str, ModelConfig] = {}
    for item in data.get("models", []):
        configs[item["id"]] = ModelConfig(
            id=item["id"],
            model=item.get("model", ""),
            temperature=item.get("temperature", 0.7),
            max_tokens=item.get("max_tokens"),
        )
    return configs


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
