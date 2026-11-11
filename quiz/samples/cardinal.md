# Assembling the Cardinal toolset

*P8 cardinal*

> How does run_agent_session(lm, None, config) assemble the ten Cardinal tools? Why does creating a session not read the email archive, and what does a session get when it is given an explicit tool list?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

`run_agent_session(lm, None, config)` goes through `create_session`. With `tools=None` it calls `build_tools(config, aux_lm)`, which pairs a description and a function with `cardinal_spec` for each name, in `CARDINAL_TOOLS` order. The names, schemas and read-only flags come from `cardinal.py` unchanged.

Creating a session reads nothing. `EMAIL_INDEX` loads the archive and builds the BM25 index on the first `search_emails`, `read_email` or `email_qa` call, under a lock and checked again inside it. It is shared by every session in the process: the archive never changes, and the live tests create many sessions from several threads, so building it per session would be slow and racy. `DOC_INDEX` works the same way.

`email_qa` and `daily_digest` run the P4 and P2 pipelines on `aux_lm`, as the handout requires for every call that is not an agent turn; `create_session` falls back to `lm` when `aux_lm` is None. The email tools return pointers, not whole emails: `search_emails` shows id, date, sender, up to five recipients, subject and the first 200 characters, with k capped at 20, and `read_email` cuts the body at 8,000 characters and says so.

With an explicit list, the session gets exactly those tools, plus `ask_user` if `config.user` is set and `remember` and `recall` if `config.memory_dir` is set; a listed tool with the same name wins. Without a user or a memory_dir, those tools raise with a message telling the model what to do, which the registry turns into `tool_error`.

## Code to point to

- cs329z_hw1/agent/session.py:388-397 create_session
- cs329z_hw1/agent/toolset.py:209-295 build_tools
- cs329z_hw1/agent/toolset.py:53-97 lazy shared indexes
- cs329z_hw1/agent/toolset.py:119-141 email tool output
- cs329z_hw1/agent/toolset.py:298-307 extra_tools
