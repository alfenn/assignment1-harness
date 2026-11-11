# The tool-call protocol

*P6 tool_protocol · memo Q2*

> Describe the tool-call format you settled on and what led you to it. Point to where your parser decides where a call ends. What happens when (a) the reply is cut off inside the arguments, (b) a string argument contains </tool_call>, and (c) the model writes two calls in one reply?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** one JSON object between `<tool_call>` tags. Where a call ends is decided by `raw_decode`, not by finding the closing tag, which handles a cut-off call, a closing tag inside an argument, and two calls.

#### Format · `protocol.py:26-27`, `protocol.py:68-98`
- A call: `{"name": ..., "args": {...}}` between `<tool_call>` and `</tool_call>`
- `render_tools` puts the rules, an example and the "Waiting for the result." stop line in the system prompt
- Results come back as a user message `<tool_result name=... status=...>` (`protocol.py:265-275`)
- Parse errors → a `malformed` result that says what was wrong

#### Parser · `protocol.py:139-161`
- First version took everything between the two tags; broke when the closing tag was missing, repeated, or inside an argument
- Now `json.JSONDecoder.raw_decode` right after the opening tag decides where the call ends (`_read_call`, L148)
- `strict=False` accepts raw newlines inside strings

#### The three cases
- **(a) Cut off inside the arguments**: the JSON does not decode → malformed, saying the call may be cut off. JSON complete, only the closing tag missing → run it
- **(b) Closing tag inside a string argument**: ordinary string content to the decoder, so the call parses intact
- **(c) Two calls**: a second `<tool_call>` → error "more than one block" (`protocol.py:171-185`), so one call at a time
- Exception: one identical call written several times (seen in my field notes) → `repeated_call` runs it once (`protocol.py:188-204`)

#### Tolerances added from live runs
- A missing opening tag
- The model's native `to=NAME` syntax
- A json code fence inside the tags

## Code to point to

- cs329z_hw1/agent/protocol.py:26-27 the tags
- cs329z_hw1/agent/protocol.py:68-98 render_tools
- cs329z_hw1/agent/protocol.py:139-161 _read_call, raw_decode at L148
- cs329z_hw1/agent/protocol.py:171-185 _parse, more than one block
- cs329z_hw1/agent/protocol.py:188-204 repeated_call
- cs329z_hw1/agent/protocol.py:265-275 result and malformed format
- cs329z_hw1/agent/session.py:210-219 parse and malformed handling
