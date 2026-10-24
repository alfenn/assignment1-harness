# CS329Z Assignment 1 TODO

Read the handout (`cs329z_assignment1_harness.pdf`) for each problem before starting it.
All code goes in `cs329z_hw1/`; wire it up through `cs329z_hw1/adapters.py`.
Problems are listed in handout order (Problem 1–17).

## Setup
- [x] `uv sync`, `.env` with `OPENROUTER_API_KEY`
- [x] Unpack email archive (`data/emails/emails.jsonl`)
- [x] `uv run pytest` — confirm baseline `NotImplementedError` failures

## Part 1 — LLM pipelines (`cs329z_hw1/pipelines/`)
- [x] **P1 priority** (3 pts) — stub: [`run_priority`](cs329z_hw1/adapters.py#L48). Single email → LM classification.
  - Suggested impl: `cs329z_hw1/pipelines/priority.py`.
  - Test: [`tests/test_priority.py`](tests/test_priority.py), rubric: [`data/priority_rubric.md`](data/priority_rubric.md)
    - [x] Run: `uv run pytest tests/test_priority.py`
    - [x] Live: `uv run pytest tests/test_priority.py -m live -s`
- [x] **P2 daily_digest** (4 pts) — stub: [`run_daily_digest`](cs329z_hw1/adapters.py#L67). List of emails → LM summary; builds on P1.
  - Suggested impl: `cs329z_hw1/pipelines/daily_digest.py`.
  - Test: [`tests/test_daily_digest.py`](tests/test_daily_digest.py)
    - [x] Run: `uv run pytest tests/test_daily_digest.py`
    - [x] Live: `uv run pytest tests/test_daily_digest.py -m live -s`
- [x] **P3 bm25** (8 pts) — stub: [`run_bm25_build`](cs329z_hw1/adapters.py#L85) / [`run_bm25_search`](cs329z_hw1/adapters.py#L98) (k1=1.5, b=0.75, Lucene IDF). No LM calls.
  - Suggested impl: `cs329z_hw1/pipelines/bm25.py`. Try queries with `uv run python -m cs329z_hw1.show bm25 "larchfield audit"` (needed for P17).
  - Test: [`tests/test_bm25.py`](tests/test_bm25.py)
    - [x] Run: `uv run pytest tests/test_bm25.py`
    - Live: none (deterministic only)
- [x] **P4 email_qa** (8 pts) — stub: [`run_email_qa`](cs329z_hw1/adapters.py#L119). Multi-hop (≤3 search calls) using the bm25-backed search.
  - Suggested impl: `cs329z_hw1/pipelines/email_qa.py`.
  - Test: [`tests/test_email_qa.py`](tests/test_email_qa.py)
    - [x] Run: `uv run pytest tests/test_email_qa.py`
    - [x] Live: `uv run pytest tests/test_email_qa.py -m live -s`

## Part 2 — Cardinal Agent (`cs329z_hw1/agent/`)
- [x] **P5 tool_registry** (3 pts) — stub: [`run_tool_registry`](cs329z_hw1/adapters.py#L150). Schema validation/execute, no LM.
  - Suggested impl: `cs329z_hw1/agent/registry.py`.
  - Test: [`tests/test_tool_registry.py`](tests/test_tool_registry.py)
    - [x] Run: `uv run pytest tests/test_tool_registry.py`
    - Live: none (deterministic only)
- [x] **P6 tool_protocol** (4 pts) — stub: [`run_render_tools`](cs329z_hw1/adapters.py#L177), [`run_parse_response`](cs329z_hw1/adapters.py#L189), [`run_format_tool_call`](cs329z_hw1/adapters.py#L209). Text format for tool calls.
  - Suggested impl: `cs329z_hw1/agent/protocol.py`.
  - Test: [`tests/test_tool_protocol.py`](tests/test_tool_protocol.py)
    - [x] Run: `uv run pytest tests/test_tool_protocol.py`
    - [x] Live: `uv run pytest tests/test_tool_protocol.py -m live -s`
- [ ] **P7 agent_loop** (8 pts) — stub: [`run_agent_session`](cs329z_hw1/adapters.py#L228) core loop: malformed-reply handling, turn/token budgets, transcript events.
  - Suggested impl: `cs329z_hw1/agent/session.py`.
  - Test: [`tests/test_agent_loop.py`](tests/test_agent_loop.py)
    - [ ] Run: `uv run pytest tests/test_agent_loop.py`
    - Live: none (deterministic only)
- [ ] **P8 cardinal** (2 pts) — `run_agent_session(lm, None, config)` registers all ten tools; build the email index lazily (no archive read at session creation); explicit tool lists get only those + `ask_user`/`remember`/`recall` when configured.
  - Reference: [`cs329z_hw1/cardinal.py`](cs329z_hw1/cardinal.py). Afterwards `uv run python -m cs329z_hw1.chat` works.
  - Test: [`tests/test_cardinal.py`](tests/test_cardinal.py)
    - [ ] Run: `uv run pytest tests/test_cardinal.py`
    - Live: none (deterministic only)
- [ ] **P9 search_docs** (5 pts) — stub: [`run_build_doc_index`](cs329z_hw1/adapters.py#L344) / [`run_search_docs`](cs329z_hw1/adapters.py#L357) / [`run_read_doc`](cs329z_hw1/adapters.py#L374). Reuses bm25 logic over `data/docs/`; snippets/windows, not whole docs. Register the tools.
  - Suggested impl: `cs329z_hw1/pipelines/search_docs.py`.
  - Test: [`tests/test_search_docs.py`](tests/test_search_docs.py)
    - [ ] Run: `uv run pytest tests/test_search_docs.py`
    - [ ] Live: `uv run pytest tests/test_search_docs.py -m live -s`
- [ ] **P10 terminal** (6 pts) — wire `run_terminal` tool to `sandbox.run_terminal` (timeout/rejection/non-zero exit, observation policy for large output), inside `run_agent_session`.
  - Reference: [`cs329z_hw1/sandbox.py`](cs329z_hw1/sandbox.py), [`cs329z_hw1/cardinal.py`](cs329z_hw1/cardinal.py)
  - Test: [`tests/test_terminal.py`](tests/test_terminal.py)
    - [ ] Run: `uv run pytest tests/test_terminal.py`
    - [ ] Live: `uv run pytest tests/test_terminal.py -m live -s`
- [ ] **P11 compaction** (8 pts) — keep every model call under `context_budget`, summarize via `aux_lm`, inside `run_agent_session`.
  - Test: [`tests/test_compaction.py`](tests/test_compaction.py)
    - [ ] Run: `uv run pytest tests/test_compaction.py`
    - [ ] Live: `uv run pytest tests/test_compaction.py -m live -s`
- [ ] **P12 memory** (8 pts) — `remember`/`recall` backed by files under `config.memory_dir`, inside `run_agent_session`.
  - Test: [`tests/test_memory.py`](tests/test_memory.py)
    - [ ] Run: `uv run pytest tests/test_memory.py`
    - [ ] Live: `uv run pytest tests/test_memory.py -m live -s`
- [ ] **P13 interactive** (7 pts) — confirm vs. auto mode, `ask_user`, approval flow, steering via `pending_message`, inside `run_agent_session`.
  - Reference: [`cs329z_hw1/user.py`](cs329z_hw1/user.py)
  - Test: [`tests/test_interactive.py`](tests/test_interactive.py)
    - [ ] Run: `uv run pytest tests/test_interactive.py`
    - Live: none (deterministic only)
- [ ] **P14 guardrails** (4 pts) — deny-rule regex checks on terminal commands, prompt injection, inside `run_agent_session`.
  - Test: [`tests/test_guardrails.py`](tests/test_guardrails.py)
    - [ ] Run: `uv run pytest tests/test_guardrails.py`
    - [ ] Live: `uv run pytest tests/test_guardrails.py -m live -s`
- [ ] **P15 sim_eval** (10 pts) — exercise everything via `cs329z_hw1/simulation`; keep the final run in `runs/`.
  - Reference: [`cs329z_hw1/simulation/`](cs329z_hw1/simulation), personas: [`tests/fixtures/personas/`](tests/fixtures/personas)
  - Test: [`tests/test_sim_eval.py`](tests/test_sim_eval.py)
    - [ ] Run: `uv run pytest tests/test_sim_eval.py`
    - [ ] Live: `uv run pytest tests/test_sim_eval.py -m live -s`

## Write-ups
- [ ] **P16 field_notes** (10 pts) — `uv run python -m cs329z_hw1.chat` (confirm mode), ≥5 requests: company doc question, email archive question, terminal request, one it should ask about first, one it should refuse/be denied. Check answers. `field_notes.pdf`, 1 page, 11pt, plus the `runs/chat-*.json` it cites.
- [ ] **P17 design_memo** (20 pts) — answer the 10 questions (bm25 errors, protocol, termination rule, search snippets/windows, terminal observation policy, compaction, memory — check `uv run python -m cs329z_hw1.show memory`, approval policy, sandbox.py limits, overall limitations). `design_memo.pdf`, ≤2 pages, 11pt.

## Submission
- [ ] Gradescope: repo zip (without `.env`, `.lm_cache/`, `data/emails/`; with `runs/` holding final eval run + chat conversations), `field_notes.pdf`, `design_memo.pdf`. Only `cs329z_hw1/` is copied for grading.

## Per-problem workflow
1. Read the problem in the handout.
2. Read the adapter's docstring in `cs329z_hw1/adapters.py`.
3. Implement in your package (e.g. `cs329z_hw1/pipelines/priority.py`).
4. Replace the stub body with a call into your code.
5. `uv run pytest tests/test_<problem>.py` (deterministic), then `-m live -s` (costs money).
