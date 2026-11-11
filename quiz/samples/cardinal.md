# Assembling the Cardinal toolset

*P8 cardinal*

> How does run_agent_session(lm, None, config) assemble the ten Cardinal tools? Why does creating a session not read the email archive, and what does a session get when it is given an explicit tool list?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** `tools=None` builds the Cardinal toolset from the spec unchanged; the indexes load lazily, once per process, and are shared; the LM-backed tools run on `aux_lm`; the email tools return pointers, not whole emails.

#### Building the tools · `session.py:388-397`, `toolset.py:209-295`
- `run_agent_session(lm, None, config)` → `create_session`
- `tools=None` → `build_tools(config, aux_lm)`: pairs a description and a function with `cardinal_spec` for each name, in `CARDINAL_TOOLS` order
- Names, schemas and read-only flags come from `cardinal.py` unchanged

#### Shared lazy indexes · `toolset.py:53-97`
- Creating a session reads nothing
- `EMAIL_INDEX` loads the archive and builds BM25 on the first `search_emails`, `read_email` or `email_qa` call, under a lock, checked again inside it
- Shared by every session in the process: the archive never changes, and the live tests create many sessions from several threads, so per session would be slow and racy
- `DOC_INDEX` works the same way

#### aux_lm
- `email_qa` and `daily_digest` run the P4 and P2 pipelines on `aux_lm`: the handout requires it for every call that is not an agent turn
- `create_session` falls back to `lm` when `aux_lm` is None

#### Output size · `toolset.py:119-141`
- `search_emails`: id, date, sender, up to 5 recipients, subject, first **200 chars**; k capped at **20**
- `read_email`: body cut at **8,000 chars**, and it says so

#### Explicit tool list · `toolset.py:298-307`
- The session gets exactly those tools
- Plus `ask_user` if `config.user` is set, and `remember` and `recall` if `config.memory_dir` is set; a listed tool with the same name wins
- Without a user or a memory_dir, those tools raise with a message telling the model what to do → `tool_error`

## Code to point to

- cs329z_hw1/agent/session.py:388-397 create_session
- cs329z_hw1/agent/toolset.py:209-295 build_tools
- cs329z_hw1/agent/toolset.py:53-97 lazy shared indexes
- cs329z_hw1/agent/toolset.py:119-141 email tool output
- cs329z_hw1/agent/toolset.py:298-307 extra_tools
