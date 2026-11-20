"""Input and output guardrails.

These are deterministic, explainable checks that run in front of and behind the
model. In production they sit alongside Azure AI Content Safety / Bedrock
Guardrails; they do not replace them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

INJECTION_PATTERNS = {
    "override_instructions": r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|system)\b.{0,20}\b(instructions?|rules?|prompts?|guidelines?)",
    "reveal_system_prompt": r"\b(reveal|show|print|repeat|output|leak|tell me)\b.{0,40}\b(system|hidden|initial|original)\s+(prompt|instructions?|message)",
    "role_hijack": r"\b(you are now|act as|pretend (to be|you are)|from now on you)\b.{0,60}\b(unrestricted|jailbroken|dan|developer mode|no (rules|restrictions|filters))",
    "developer_mode": r"\b(developer|god|admin|debug|sudo)\s+mode\b",
    "dan": r"\bDAN\b|\bdo anything now\b",
    "exfiltration": r"\b(send|post|upload|exfiltrate|forward)\b.{0,40}\b(https?://|webhook|external (url|server)|attacker)",
    "acl_bypass": r"\b(bypass|ignore|skip|disable)\b.{0,30}\b(acl|access control|permissions?|security filter|guardrails?)",
    "encoded_payload": r"\b(base64|rot13|hex)[- ]?(decode|encoded)\b.{0,40}\b(instructions?|follow|execute)",
}
_COMPILED = {name: re.compile(p, re.IGNORECASE | re.DOTALL) for name, p in INJECTION_PATTERNS.items()}

PII_PATTERNS = {
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CARD": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "PHONE": re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)"),
}
SECRET_PATTERNS = re.compile(
    r"(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?i:(api[_-]?key|secret|password)\s*[:=]\s*\S{8,}))"
)


@dataclass
class GuardrailResult:
    allowed: bool
    findings: list[str] = field(default_factory=list)
    text: str = ""


def detect_injection(text: str) -> list[str]:
    return [name for name, rx in _COMPILED.items() if rx.search(text)]


def _luhn_ok(digits: str) -> bool:
    nums = [int(d) for d in digits][::-1]
    total = sum(n if i % 2 == 0 else (n * 2 - 9 if n * 2 > 9 else n * 2) for i, n in enumerate(nums))
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, list[str]]:
    found: list[str] = []

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            found.append("CARD")
            return "[REDACTED_CARD]"
        return m.group(0)

    text = PII_PATTERNS["CARD"].sub(card, text)
    for label in ("EMAIL", "SSN", "PHONE"):
        text, n = PII_PATTERNS[label].subn(f"[REDACTED_{label}]", text)
        found += [label] * n
    return text, found


def check_input(question: str, max_chars: int = 2000) -> GuardrailResult:
    if not question or not question.strip():
        return GuardrailResult(False, ["empty_input"])
    if len(question) > max_chars:
        return GuardrailResult(False, ["input_too_long"])
    hits = detect_injection(question)
    if hits:
        return GuardrailResult(False, [f"prompt_injection:{h}" for h in hits])
    redacted, pii = redact_pii(question)
    return GuardrailResult(True, [f"pii_redacted:{p}" for p in pii], redacted)


def screen_retrieved(text: str) -> list[str]:
    """Indirect prompt injection: instructions hidden inside retrieved documents."""
    return detect_injection(text)


def check_output(raw: str, allowed_citations: set[str]) -> GuardrailResult:
    """Model output must be valid JSON, cite only retrieved sources and leak no secrets."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return GuardrailResult(False, ["output_not_json"])
    if not isinstance(data, dict) or not isinstance(data.get("answer"), str):
        return GuardrailResult(False, ["output_schema_invalid"])
    citations = data.get("citations") or []
    if not isinstance(citations, list) or not set(citations) <= allowed_citations:
        return GuardrailResult(False, ["citation_not_in_retrieved_sources"])
    if SECRET_PATTERNS.search(data["answer"]):
        return GuardrailResult(False, ["secret_in_output"])
    answer, pii = redact_pii(data["answer"])
    data["answer"] = answer
    return GuardrailResult(True, [f"pii_redacted:{p}" for p in pii], json.dumps(data))
