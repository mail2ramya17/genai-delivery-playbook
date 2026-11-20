"""AI gateway: every model call goes through here.

Mirrors what APIM / an internal gateway does in production: per-user token quotas,
primary -> fallback routing, latency and cost metering, and a prompt/response audit
log that stores redacted text and a hashed user id only.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .llm import Completion, LLMClient

# USD per 1K tokens (example figures, configure per contract)
PRICING = {"default": {"input": 0.0025, "output": 0.01}}


class QuotaExceeded(Exception):
    pass


class AllModelsFailed(Exception):
    pass


@dataclass
class GatewayResult:
    completion: Completion
    latency_ms: float
    cost_usd: float
    route: str


class AIGateway:
    def __init__(self, primary: LLMClient, fallback: LLMClient | None = None,
                 daily_token_quota: int = 50_000, audit_path: str | Path | None = None):
        self.primary, self.fallback = primary, fallback
        self.quota = daily_token_quota
        self.audit_path = Path(audit_path) if audit_path else None
        self._usage: dict[tuple[str, str], int] = defaultdict(int)
        self._lock = threading.Lock()

    @staticmethod
    def _user_hash(user_id: str) -> str:
        return hashlib.sha256(user_id.encode()).hexdigest()[:16]

    def _check_quota(self, user_id: str) -> None:
        key = (user_id, time.strftime("%Y-%m-%d"))
        if self._usage[key] >= self.quota:
            raise QuotaExceeded(f"daily token quota of {self.quota} reached")

    def _meter(self, user_id: str, c: Completion) -> float:
        with self._lock:
            self._usage[(user_id, time.strftime("%Y-%m-%d"))] += c.input_tokens + c.output_tokens
        price = PRICING.get(c.model, PRICING["default"])
        return c.input_tokens / 1000 * price["input"] + c.output_tokens / 1000 * price["output"]

    def call(self, user_id: str, messages: list[dict], temperature: float, max_tokens: int,
             prompt_version: str) -> GatewayResult:
        self._check_quota(user_id)
        start = time.perf_counter()
        route, last_err = "primary", None
        for route, client in (("primary", self.primary), ("fallback", self.fallback)):
            if client is None:
                continue
            try:
                completion = client.complete(messages, temperature, max_tokens)
                break
            except Exception as err:  # noqa: BLE001 - any provider error triggers fallback
                last_err = err
        else:
            raise AllModelsFailed(str(last_err))
        latency = (time.perf_counter() - start) * 1000
        cost = self._meter(user_id, completion)
        result = GatewayResult(completion, latency, cost, route)
        self.audit(user_id, messages[-1]["content"], completion.text, prompt_version, result)
        return result

    def audit(self, user_id: str, prompt: str, response: str, prompt_version: str,
              result: GatewayResult | None = None, blocked_reason: str | None = None) -> None:
        if not self.audit_path:
            return
        from .guardrails import redact_pii

        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "user": self._user_hash(user_id),
            "prompt_version": prompt_version,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt_redacted": redact_pii(prompt)[0][:2000],
            "response_redacted": redact_pii(response)[0][:2000],
            "blocked_reason": blocked_reason,
        }
        if result:
            record.update(model=result.completion.model, route=result.route,
                          latency_ms=round(result.latency_ms, 1), cost_usd=round(result.cost_usd, 6),
                          tokens=result.completion.input_tokens + result.completion.output_tokens)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
