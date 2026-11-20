"""Orchestrator: user -> guardrails -> ACL-trimmed retrieval -> gateway -> LLM -> guardrails -> answer."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from . import guardrails
from .gateway import AIGateway, AllModelsFailed, QuotaExceeded
from .index import VectorIndex
from .ingestion import load_directory
from .llm import NO_ANSWER, LLMClient, MockLLM

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = Path(__file__).parent / "prompts" / "answer_v1.yaml"
BLOCKED_MESSAGE = "This request was blocked by a safety policy. If you think this is a mistake, contact the service desk."


@dataclass
class User:
    user_id: str
    groups: set[str]


@dataclass
class Answer:
    answer: str
    citations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    prompt_version: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["latency_ms"] = round(self.latency_ms, 1)
        data["cost_usd"] = round(self.cost_usd, 6)
        return data


def load_prompt(path: Path = PROMPT_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class SupportCopilot:
    def __init__(self, index: VectorIndex, gateway: AIGateway, prompt: dict | None = None, top_k: int = 5):
        self.index, self.gateway, self.top_k = index, gateway, top_k
        self.prompt = prompt or load_prompt()

    @classmethod
    def from_directory(cls, docs: str | Path = ROOT / "data" / "sample_docs",
                       primary: LLMClient | None = None, fallback: LLMClient | None = None,
                       audit_path: str | Path | None = None) -> "SupportCopilot":
        gateway = AIGateway(primary or MockLLM(), fallback, audit_path=audit_path)
        return cls(VectorIndex(load_directory(docs)), gateway)

    def _messages(self, question: str, chunks) -> list[dict]:
        sources = "\n".join(f"[{c.doc_id}] {c.text}" for c in chunks)
        msgs = [{"role": "system", "content": self.prompt["system"]}]
        for shot in self.prompt.get("few_shot", []):
            msgs += [{"role": "user", "content": shot["user"]}, {"role": "assistant", "content": shot["assistant"]}]
        msgs.append({"role": "user", "content": f"SOURCES:\n{sources}\n\nQUESTION: {question}"})
        return msgs

    def _blocked(self, user: User, question: str, reasons: list[str], start: float) -> Answer:
        self.gateway.audit(user.user_id, question, BLOCKED_MESSAGE, self.prompt["version"], blocked_reason=";".join(reasons))
        return Answer(BLOCKED_MESSAGE, blocked=True, reasons=reasons,
                      latency_ms=(time.perf_counter() - start) * 1000, prompt_version=self.prompt["version"])

    def answer(self, question: str, user: User) -> Answer:
        start = time.perf_counter()
        version = self.prompt["version"]

        checked = guardrails.check_input(question)
        if not checked.allowed:
            return self._blocked(user, question, checked.findings, start)
        reasons = list(checked.findings)

        hits = self.index.search(checked.text, user.groups, top_k=self.top_k)
        chunks = []
        for chunk, _score in hits:
            poisoned = guardrails.screen_retrieved(chunk.text)
            if poisoned:
                reasons.append(f"indirect_injection_dropped:{chunk.chunk_id}")
                continue
            chunks.append(chunk)

        if not chunks:
            return Answer(NO_ANSWER, reasons=reasons + ["no_authorized_sources"],
                          latency_ms=(time.perf_counter() - start) * 1000, prompt_version=version)

        try:
            result = self.gateway.call(user.user_id, self._messages(checked.text, chunks),
                                       self.prompt["temperature"], self.prompt["max_output_tokens"], version)
        except QuotaExceeded:
            return self._blocked(user, question, ["quota_exceeded"], start)
        except AllModelsFailed:
            return Answer("The assistant is temporarily unavailable.", reasons=reasons + ["model_unavailable"],
                          latency_ms=(time.perf_counter() - start) * 1000, prompt_version=version)

        out = guardrails.check_output(result.completion.text, {c.doc_id for c in chunks})
        if not out.allowed:
            return Answer(NO_ANSWER, reasons=reasons + out.findings, latency_ms=result.latency_ms,
                          cost_usd=result.cost_usd, prompt_version=version)
        data = json.loads(out.text)
        cited = set(data.get("citations", []))
        return Answer(
            answer=data["answer"],
            citations=sorted(cited),
            confidence=float(data.get("confidence", 0.0)),
            reasons=reasons + out.findings,
            sources=[{"doc_id": c.doc_id, "chunk_id": c.chunk_id, "title": c.title, "text": c.text}
                     for c in chunks if c.doc_id in cited],
            latency_ms=(time.perf_counter() - start) * 1000,
            cost_usd=result.cost_usd,
            prompt_version=version,
        )
