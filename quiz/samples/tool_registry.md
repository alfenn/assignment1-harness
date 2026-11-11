# The tool registry

*P5 tool_registry*

> Show me your tool registry. Why does validate exist separately from execute? What does the model see for an unknown tool, for bad arguments, and for a tool that raises?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

`ToolRegistry` keeps tools in a dict in registration order and compiles one `Draft202012Validator` per tool when it is registered, so each call only runs the check. `schemas()` returns exactly name, description and parameters: all the model ever sees of a tool, and what `render_tools` formats.

`validate` never calls the tool and never raises. For an unknown tool, the result lists the available tools. If the arguments are not an object, it says so. Otherwise it reports every schema error, sorted by path, with where it is and the message, so the model can fix them all in one retry; even a broken schema comes back as `invalid_args`. `execute` validates first, then runs `fn(**args)`. Success is `ok` with str() of the return value, and any exception becomes `tool_error` with the exception's type and message, so nothing escapes into the loop.

Validate is separate because the session calls it before the guard and before approval. A bad call is a malformed reply: it never reaches the user for approval and never runs. `unknown_tool` and `invalid_args` count toward the malformed limit; `tool_error` does not, because the call was well formed and the tool failed.

`denied` never comes from the registry: the session writes it, because a denied call is never executed. Later problems rely on raise-to-tool_error: the terminal raises for a non-zero exit, and `read_doc` for an unknown doc_id.

## Code to point to

- cs329z_hw1/agent/registry.py:19-21 register, compiled validator
- cs329z_hw1/agent/registry.py:29-33 schemas
- cs329z_hw1/agent/registry.py:35-59 validate
- cs329z_hw1/agent/registry.py:61-69 execute, tool_error
- cs329z_hw1/agent/session.py:251-260 validate before guard and approval
- cs329z_hw1/agent/session.py:80 MALFORMED_STATUSES
