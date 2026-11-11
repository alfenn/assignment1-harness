# The tool registry

*P5 tool_registry*

> Show me your tool registry. Why does validate exist separately from execute? What does the model see for an unknown tool, for bad arguments, and for a tool that raises?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** registering compiles a validator once; validate never runs the tool and never raises, and reports every error so the model can fix them in one retry; execute turns any exception into `tool_error`.

#### Register and schemas · `registry.py:19-33`
- Tools kept in a dict, in registration order
- One `Draft202012Validator` compiled per tool at registration, so each call only runs the check
- `schemas()` returns exactly name, description, parameters: all the model ever sees of a tool, and what `render_tools` formats

#### validate · `registry.py:35-59`
- Never calls the tool, never raises
- Unknown tool → the result lists the available tools
- Arguments not an object → says so
- Otherwise **every** schema error, sorted by path, with where and the message, so the model fixes them all in one retry
- Even a broken schema comes back as `invalid_args`

#### execute · `registry.py:61-69`
- Validates first, then runs `fn(**args)`
- Success → `ok` with str() of the return value
- Any exception → `tool_error` with its type and message; nothing escapes into the loop

#### Why validate is separate · `session.py:251-260`
- The session calls it before the guard and before approval
- A bad call is a malformed reply: never reaches the user for approval, never runs
- `unknown_tool` and `invalid_args` count toward the malformed limit; `tool_error` does not, because the call was well formed and the tool failed (`session.py:80`)

#### Not from the registry
- `denied` is written by the session, because a denied call is never executed
- Later problems rely on raise-to-`tool_error`: the terminal raises on a non-zero exit, `read_doc` on an unknown doc_id

## Code to point to

- cs329z_hw1/agent/registry.py:19-21 register, compiled validator
- cs329z_hw1/agent/registry.py:29-33 schemas
- cs329z_hw1/agent/registry.py:35-59 validate
- cs329z_hw1/agent/registry.py:61-69 execute, tool_error
- cs329z_hw1/agent/session.py:251-260 validate before guard and approval
- cs329z_hw1/agent/session.py:80 MALFORMED_STATUSES
