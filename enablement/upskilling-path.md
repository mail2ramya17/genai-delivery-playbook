# Upskilling path: teams that no longer need us

Five hands-on workshops, each run on this repo with real (sample) data. Goal: an engineering team ships its own first prototype in about a week using a pattern from `patterns/catalog.yaml`.

| # | Workshop | What teams build | Lab in this repo |
|---|---|---|---|
| 1 | Prompt engineering | System prompt, few-shot examples, structured JSON output, temperature tuning | Edit `copilot/prompts/answer_v1.yaml`, re-run `make eval` and see the scores move |
| 2 | RAG design | Chunking, embeddings, retrieval, ACLs | Add a doc with new `groups:` to `data/sample_docs/`, prove another user cannot see it |
| 3 | Orchestration frameworks | Semantic Kernel, LangChain, LlamaIndex, Bedrock Agents | Port `copilot/answer.py` to one framework and keep the tests green |
| 4 | Evaluation & safety | Test sets, guardrails, red teaming | Write 5 new attacks in `evals/attacks.jsonl`; break the gate, then fix it |
| 5 | Agents & tools | Tool design, least privilege, approval | Design an "open ticket" tool with scoped credentials and human approval |

## Materials

- **Documentation**: `docs/PLAYBOOK.md` (architecture and standards)
- **Playbooks / runbooks**: `docs/runbooks/` (step-by-step, security built in)
- **Quick-start**: the README "Run it in 2 minutes" section, first prototype in a day
- **Template repos**: this repository is the RAG template
- **Office hours**: weekly, to unblock live work

## Operating cadence (liaison role)

Weekly use-case intake, architecture review board, office hours, monthly roadmap sync with the central AI platform team, a shared backlog of platform gaps, an escalation path for blockers and an adoption scorecard.
