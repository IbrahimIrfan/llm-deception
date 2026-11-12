from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

import httpx


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_ATTEMPTS = 4
TIMEOUT_SECONDS = 300


def load_dotenv() -> None:
    """Read KEY=VALUE lines from the repo's .env file (if any) into the environment."""
    path = os.path.join(REPO_ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            os.environ.setdefault(key, value.strip().strip("'\""))


load_dotenv()


@dataclass
class ModelConfig:
    id: str
    model: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    label: str = ""
    reasoning: Optional[Dict[str, Any]] = None


def log_usage(entry: Dict[str, Any]) -> None:
    """Append one line per API call to SIM_USAGE_PATH so runs can be costed afterwards."""
    path = os.getenv("SIM_USAGE_PATH", "")
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class LLMClient:
    def __init__(self, config: ModelConfig):
        self.config = config

    def chat(self, messages: List[Dict[str, str]]) -> str:
        if os.getenv("SIM_MOCK"):
            return mock_chat(messages)

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ValueError("OpenRouter API key is missing. Set OPENROUTER_API_KEY or add it to .env.")

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "usage": {"include": True},
        }
        if self.config.max_tokens is not None:
            payload["max_tokens"] = self.config.max_tokens
        if self.config.reasoning is not None:
            payload["reasoning"] = self.config.reasoning

        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.time()
            try:
                response = httpx.post(
                    OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                    timeout=TIMEOUT_SECONDS,
                )
                data = response.json()
                if response.status_code != 200 or "error" in data:
                    raise RuntimeError(f"HTTP {response.status_code}: {str(data.get('error', data))[:300]}")
                choices = data.get("choices") or []
                content = (choices[0].get("message", {}).get("content") or "") if choices else ""
                usage = data.get("usage") or {}
                details = usage.get("completion_tokens_details") or {}
                log_usage(
                    {
                        "ts": now_iso(),
                        "model_id": self.config.id,
                        "model": self.config.model,
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "reasoning_tokens": details.get("reasoning_tokens", 0),
                        "cost": usage.get("cost"),
                        "seconds": round(time.time() - started, 2),
                        "attempt": attempt,
                        "empty": not content,
                    }
                )
                if content:
                    return content
                last_error = "empty response"
            except Exception as exc:  # network errors, bad JSON, provider errors
                last_error = f"{type(exc).__name__}: {exc}"
            print(f"[llm] attempt {attempt} failed model={self.config.model} error={last_error}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt + random.random())

        log_usage({"ts": now_iso(), "model_id": self.config.id, "model": self.config.model, "error": last_error})
        return ""


def mock_chat(messages: List[Dict[str, str]]) -> str:
    """Offline stand-in for a model, used to test the pipeline without spending money."""
    user = messages[-1]["content"]
    if "Create a concise character profile" in user:
        return json.dumps({"name": f"Mock Player {random.randint(100, 999)}", "career": "Tester"})
    tied = re.search(r"Tied candidates: (.*)", user)
    living = re.search(r"Living players: (.*)", user)
    if "REVOTE REQUIRED" in user and tied:
        return json.dumps({"vote_out": random.choice(tied.group(1).split(", "))})
    if "VOTE REQUIRED" in user and living:
        return json.dumps({"vote_out": random.choice(living.group(1).split(", "))})
    names = living.group(1).split(", ") if living else []
    return json.dumps(
        {
            "public_message": random.choice(["I don't have the money.", "I think someone is lying.", ""]),
            "private_message_to": random.choice(names) if names and random.random() < 0.3 else None,
            "private_message": "Let's work together.",
            "notes_update": "mock note",
            "done": random.random() < 0.6,
        }
    )


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
            label=item.get("label", item["id"]),
            reasoning=item.get("reasoning"),
        )
    return configs


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
