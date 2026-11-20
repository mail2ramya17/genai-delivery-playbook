# Security runbook: Chat over documents (RAG)

Use this runbook with the `chat-over-documents` pattern. Every item maps to code or config in this repo.

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| User sees documents they are not entitled to | Access labels kept through ingestion; ACL filter applied inside the search call; no identity = no results | `copilot/ingestion.py`, `copilot/index.py` |
| Direct prompt injection / jailbreak | Input guardrail (pattern set) in front of Prompt Shields / Bedrock Guardrails | `copilot/guardrails.py::check_input` |
| Indirect prompt injection via documents | Retrieved chunks screened; poisoned chunks dropped and logged | `guardrails.screen_retrieved`, `evals/poisoned_docs/` |
| Hallucinated or uncited answers | Grounding prompt, temperature 0.1, JSON output, citations must be a subset of retrieved sources | `copilot/prompts/answer_v1.yaml`, `guardrails.check_output` |
| PII in prompts, answers and logs | Redaction on input, output and audit log; user id hashed | `guardrails.redact_pii`, `copilot/gateway.py` |
| Secrets leaked in output | Secret patterns blocked at output | `guardrails.SECRET_PATTERNS` |
| Cost runaway / abuse | Per-user daily token quota; APIM token limit | `gateway.AIGateway`, `infra/apim-ai-gateway-policy.xml` |
| Provider outage | Primary to fallback routing | `gateway.AIGateway.call` |
| Network exposure | Private endpoints, `public_network_access_enabled = false` | `infra/terraform/main.tf` |
| Key theft | Managed identity, `local_auth_enabled = false`, Key Vault with RBAC | `infra/terraform/main.tf`, `copilot/llm.py` |

## Checked by hand before every release

- Prompt injection through documents (try a fresh poisoned doc, not just the fixture)
- Data leaks across user permissions (same question, three different users)
- Over-privileged tools or agents (none in this pattern; confirm nothing was added)
- Logging and retention of prompts (retention matches the privacy review)

## Incident: harmful or wrong output

1. Capture the audit record (`prompt_sha256`, `prompt_version`, `model`, hashed user).
2. If harmful: block the pattern at the gateway / guardrail within the hour; roll back the prompt version if it caused it.
3. Add the case to `evals/attacks.jsonl` or `evals/golden.jsonl` so the gate catches it forever.
4. Post-incident review with the data owner and RAI reviewer.
