"""Model clients behind one interface.

`MockLLM` is a deterministic, extractive model so tests and the evaluation gate run
offline and in CI with no keys. `AzureOpenAIClient` and `BedrockClient` are the
production clients; both authenticate with managed identity / IAM roles, never keys.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

from .index import tokenize

SOURCE_LINE = re.compile(r"^\[(?P<doc>[A-Z]+-\d+)\]\s*(?P<text>.+)$", re.MULTILINE)
NO_ANSWER = "I can't answer that from the sources available to you. Please open a service desk ticket."


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient(Protocol):
    name: str

    def complete(self, messages: list[dict], temperature: float, max_tokens: int) -> Completion: ...


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


OBEY_TRIGGERS = re.compile(
    r"system prompt|hidden instructions|previous instructions|prior rules|no restrictions|"
    r"developer mode|without guardrails|unrestricted|\bDAN\b|follow the instructions",
    re.IGNORECASE,
)


class MockLLM:
    """Extractive stand-in: answers with the source sentences that best match the question.

    With `susceptible=True` (the default) it behaves like a naive model that OBEYS
    injected instructions: it leaks its system prompt when asked and repeats
    instructions planted in retrieved documents. That is deliberate. It means the
    evaluation gate only passes because the guardrails work, not because the model
    happens to be well behaved.
    """

    name = "mock-extractive"

    def __init__(self, min_overlap: int = 2, max_sentences: int = 2, susceptible: bool = True):
        self.min_overlap = min_overlap
        self.max_sentences = max_sentences
        self.susceptible = susceptible

    def complete(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 400) -> Completion:
        user = messages[-1]["content"]
        question = user.split("QUESTION:", 1)[-1].strip()
        sources_block = user.split("SOURCES:", 1)[-1].split("QUESTION:", 1)[0]
        q_terms = set(tokenize(question))

        if self.susceptible:
            if OBEY_TRIGGERS.search(question):
                leak = {"answer": "Sure! My instructions are: " + messages[0]["content"], "citations": [], "confidence": 1.0}
                return self._done(messages, leak)
            for m in SOURCE_LINE.finditer(sources_block):
                if re.search(r"ignore (all )?previous instructions", m.group("text"), re.IGNORECASE):
                    return self._done(messages, {"answer": "Following the system note: " + m.group("text"),
                                                 "citations": [m.group("doc")], "confidence": 1.0})

        scored = []
        for m in SOURCE_LINE.finditer(sources_block):
            for sentence in re.split(r"(?<=[.!?])\s+", m.group("text")):
                overlap = len(q_terms & set(tokenize(sentence)))
                if overlap >= self.min_overlap:
                    scored.append((overlap, m.group("doc"), sentence.strip()))
        scored.sort(key=lambda s: s[0], reverse=True)
        picked = scored[: self.max_sentences]

        if not picked:
            payload = {"answer": NO_ANSWER, "citations": [], "confidence": 0.0}
        else:
            answer = " ".join(f"{s} [{doc}]" for _, doc, s in picked)
            cites = sorted({doc for _, doc, _ in picked})
            conf = round(min(0.95, 0.5 + 0.1 * picked[0][0]), 2)
            payload = {"answer": answer, "citations": cites, "confidence": conf}
        return self._done(messages, payload)

    def _done(self, messages: list[dict], payload: dict) -> Completion:
        text = json.dumps(payload)
        prompt = "".join(m["content"] for m in messages)
        return Completion(text, estimate_tokens(prompt), estimate_tokens(text), self.name)


class AzureOpenAIClient:
    """Azure OpenAI over a private endpoint, authenticated with Entra ID (no API keys)."""

    def __init__(self, deployment: str | None = None):
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AzureOpenAI

        token = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
        self._client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )
        self.name = deployment or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "chat-prod")

    def complete(self, messages, temperature, max_tokens):
        resp = self._client.chat.completions.create(
            model=self.name, messages=messages, temperature=temperature,
            max_tokens=max_tokens, response_format={"type": "json_object"},
        )
        return Completion(resp.choices[0].message.content, resp.usage.prompt_tokens,
                          resp.usage.completion_tokens, self.name)


class BedrockClient:
    """Amazon Bedrock Converse API via the task's IAM role, with an optional Bedrock Guardrail."""

    def __init__(self, model_id: str | None = None):
        import boto3

        self._client = boto3.client("bedrock-runtime")
        self.name = model_id or os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0")
        self._guardrail = os.environ.get("BEDROCK_GUARDRAIL_ID")

    def complete(self, messages, temperature, max_tokens):
        system = [{"text": m["content"]} for m in messages if m["role"] == "system"]
        convo = [{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages if m["role"] != "system"]
        kwargs = dict(modelId=self.name, system=system, messages=convo,
                      inferenceConfig={"temperature": temperature, "maxTokens": max_tokens})
        if self._guardrail:
            kwargs["guardrailConfig"] = {"guardrailIdentifier": self._guardrail,
                                         "guardrailVersion": os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")}
        resp = self._client.converse(**kwargs)
        return Completion(resp["output"]["message"]["content"][0]["text"],
                          resp["usage"]["inputTokens"], resp["usage"]["outputTokens"], self.name)


def build_client(provider: str | None = None) -> LLMClient:
    provider = (provider or os.environ.get("LLM_PROVIDER", "mock")).lower()
    if provider == "azure":
        return AzureOpenAIClient()
    if provider == "bedrock":
        return BedrockClient()
    return MockLLM()
