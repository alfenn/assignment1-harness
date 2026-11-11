# The tool-call protocol

*P6 tool_protocol · memo Q2*

> Describe the tool-call format you settled on and what led you to it. Point to where your parser decides where a call ends. What happens when (a) the reply is cut off inside the arguments, (b) a string argument contains </tool_call>, and (c) the model writes two calls in one reply?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

A call is one JSON object, `{"name": ..., "args": {...}}`, between `<tool_call>` and `</tool_call>`. `render_tools` puts the rules, an example and the "Waiting for the result." stop line in the system prompt. Results come back as a user message `<tool_result name=... status=...>`, and parse errors as a `malformed` result that says what was wrong.

What led me there: my first parser took everything between the two tags, and searching for the closing tag broke when it was missing, repeated, or inside an argument. Now the end of a call is decided by `json.JSONDecoder.raw_decode` right after the opening tag, in `_read_call`, not by finding the closing tag. `strict=False` accepts raw newlines inside strings.

(a) Cut off inside the arguments: the JSON does not decode, and the model gets a malformed result saying the call may be cut off. If the JSON is complete and only the closing tag is missing, I run the call. (b) A `</tool_call>` inside a string argument is ordinary string content to the decoder, so the call parses intact. (c) Two calls: a second `<tool_call>` after the first gives the error "more than one block", so the model sends one call at a time. The exception is one identical call written several times, which I saw in my field notes: `repeated_call` runs it once.

Tolerances added from live runs: a missing opening tag, the model's native `to=NAME` syntax, and a json code fence inside the tags.

## Code to point to

- cs329z_hw1/agent/protocol.py:26-27 the tags
- cs329z_hw1/agent/protocol.py:68-98 render_tools
- cs329z_hw1/agent/protocol.py:139-161 _read_call, raw_decode at L148
- cs329z_hw1/agent/protocol.py:171-185 _parse, more than one block
- cs329z_hw1/agent/protocol.py:188-204 repeated_call
- cs329z_hw1/agent/protocol.py:265-275 result and malformed format
- cs329z_hw1/agent/session.py:210-219 parse and malformed handling
