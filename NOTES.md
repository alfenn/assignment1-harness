# Implementation notes

A running diary of the problems we hit while building the harness, and what we
did about them. It's written so we can rebuild the story later for the design
memo (P17) and the field notes (P16).

Each entry follows the same shape: what we were trying to do, the design
decision we made, what happened, how often it happened, and how we fixed it.

Request ids like `req-03` refer to
[`tests/fixtures/agent_protocol_requests.json`](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/tests/fixtures/agent_protocol_requests.json).

---

## P6: the tool-call protocol

All the work is in commit
[`291fa90` "finish p6"](https://github.com/alfenn/assignment1-harness/commit/291fa901e47d8f49e47c8f565d1268ac0cfb0f49).
The code is
[`cs329z_hw1/agent/protocol.py`](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py).
The prompt changes below were made before that commit, so the commit holds the
final prompt, not the intermediate versions. This section feeds memo Q2 (the
protocol) and Q3 (the termination rule, which is P7's problem).

### 1. Picking a call format the parser can't get confused by

**The task.** The course LM only takes text in and gives text out, with no
built-in tool calling. We had to invent a way for the model to write "call
this tool with these arguments" as text, and a parser that reads it back. The
parser has to cope with three hard cases from the tests:
- a reply that gets cut off at any character;
- two calls in one reply;
- an argument that itself contains a complete call.

**The decision.** The model writes one JSON object between tags:

```
<tool_call>
{"name": "lookup", "args": {"key": "guest_wifi"}}
</tool_call>
```

The key trick is that the parser doesn't search for `</tool_call>` to find
where the call ends. It finds the opening tag and lets Python's JSON decoder
read exactly one object from there
([`raw_decode`, line 150](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py#L150)).
That gives us the three hard cases almost for free:
- **Nested calls:** a `<tool_call>` inside a string argument is just part of
  the string, so it can't confuse the parser.
- **Cut-off replies:** a JSON object that's been cut short never decodes,
  because its closing `}` is the last character. A truncated call becomes an
  error and can never parse to a wrong call. If only the closing tag is missing,
  the JSON is complete and we accept it
  ([line 161](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py#L161)).
- **Two calls:** after the first call, any second `<tool_call>` is an error
  ([line 181](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py#L181)).

We also made the parser forgiving about small things models get wrong
([lines 29–30](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py#L29-L30)):
- `arguments` or `parameters` in place of `args`;
- raw newlines inside strings;
- a ```` ```json ```` fence inside the tags.

Tool results go back to the model as a user message
`<tool_result name="..." status="...">...</tool_result>`
([`format_tool_result`, line 200](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py#L200)),
ready for P7 to use.

We considered two other formats and rejected both:
- **A fenced ```` ``` ```` block.** It gets ambiguous as soon as an argument
  contains code with its own fences.
- **One XML tag per argument.** It loses the difference between `1`, `"1"`
  and `true`, and needs escaping of markup in values.

**The result.** Every deterministic test in `tests/test_tool_protocol.py`
passed on the first try.

**How often it came up.** Never. All the trouble below came from the live
model, not from the parser.

**Remediation.** None needed.

### 2. The model said it would call a tool, then didn't

**The task.** Pass the live test, where the real grading model
(`openai/gpt-6-luna`) sees our tool descriptions and 20 requests and has to
write a correct call for at least 18 of them.

**The decision.** The first prompt explained the format, gave the rules, and
said "you may write a short sentence before" the call.

**The result.** It scored only 12 of 20 the first time we ran
`uv run pytest tests/test_tool_protocol.py -m live -s`. The parser wasn't the
problem; the model just didn't write the call. It failed in two ways:
- **It announced a call and stopped.** req-02 replied "I'll calculate that."
  and req-20 replied "I'll run it now.", with no call after either.
- **It did the job itself.** req-03 replied "I'll calculate it. -28", and
  req-06 echoed the sentence back instead of calling `echo`.

**How often it came up.** 8 of 20 requests on the first run (req-02, 03, 05,
06, 07, 11, 19, 20). Three of those were empty replies, which are covered in
entry 4.

**Remediation.** We rewrote the prompt
([lines 69–102](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py#L69-L102)).
It now says:
- **Only the block runs a tool.** Saying "I'll look that up" does nothing
  ([line 80](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py#L80)).
- **Call the tool even if you could answer yourself.** Don't do the arithmetic
  or echo the text
  ([line 81](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py#L81)).
- **No preamble is needed.** The example reply is now just the block.
- **A reminder repeats the rule** after the tool list.

That took us from 12/20 to 18/20 on the next pass. The same behaviour will show
up in P7's loop: a reply like "I'll look that up." with no call would be taken
as the final answer unless the loop has a rule for it. That's memo Q3.

### 3. The model thought it didn't have any tools

**The task.** Same live test, after the fix in entry 2.

**The decision.** The prompt described the format but didn't say outright that
writing text is how tools are called.

**The result.** req-03 replied "I'm unable to call the calculator tool in this
response. -40 + 12 = -28." Our guess is that GPT models are trained to expect
the API's built-in tool calling. When no built-in tools are attached, it
sometimes concludes it has none.

**How often it came up.** Once (req-03) in the run after entry 2's fix. A
similar reply showed up once more later: req-15, in an uncached run, said
"I'm unable to pause because the available tools don't include a timer".

**Remediation.** We added a line to the top of the prompt: calls are plain
text, need no special tool-calling feature, and always work
([line 71](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/agent/protocol.py#L71)).
The req-15 case is still open. The `slow` tool's description says "Wait for
the given number of seconds" and never says "timer" or "pause". That
description lives in the test fixtures, so we can't change it.

### 4. Some replies came back completely empty

**The task.** Same live test.

**The decision.** None; we just read the reply text the course wrapper hands
back.

**The result.** A few replies were an empty string `''`. To investigate, we
sent the same requests (req-09 and req-03) straight to the API with the
`openai` client, using the same model, temperature and reasoning effort, three
times each. All six came back correct, with a normal `finish_reason: stop`
and no built-in tool calls attached. We never found the cause.

**How often it came up.** Three times in roughly the first 60 live calls
(req-07 and req-19 in the first run, req-09 later), and 0 of 6 when we went
looking for it.

**Remediation.** None in our code. The course wrapper
[doesn't cache empty replies](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/llm.py#L311),
so rerunning the test asks the model again. If it keeps happening in P7, the
loop should treat an empty reply as malformed and retry.

### 5. The cache kept replaying a bad answer

**The task.** Find out how reliable the prompt really is, not just whether one
run passes.

**The decision.** At first we just reran the live test.

**The result.** The course wrapper caches every non-empty reply, so a bad
answer (req-03's "I'm unable to call…") came back on every rerun until we
changed the prompt text. A passing run built from cached answers tells us
little about what a fresh run, like the grader's, will do.

**How often it came up.** On every rerun with an unchanged prompt.

**Remediation.** We changed how we measure. We built one `LM(salt=...)` per
run; a different salt gives a different cache key, so every reply is fresh.
Then we scored all 20 requests with the test's own
[`check_reply`](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/tests/test_tool_protocol.py#L371).
Three runs (no salt, `s1`, `s2`) gave 20, 20 and 18, so 58 of 60, or about
97% per request. At that rate, a rough estimate is a 2–3% chance that a fresh
run scores below 18/20.

The other `s2` miss: req-19 wrote the same `write_note` call twice. We can't
accept that, because the tests require a doubled call to be rejected
([`same-call-twice`](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/tests/test_tool_protocol.py#L225)).

### 6. One runaway reply crashed the whole live test

**The task.** Same live test, on the run after entry 2's prompt fix.

**The decision.** None; the test calls the model directly.

**The result.** One reply ran out of room: 10,098 characters, hitting the
4096-token limit. The wrapper raises `OutputTruncated` when that happens
([`llm.py` line 303](https://github.com/alfenn/assignment1-harness/blob/291fa901e47d8f49e47c8f565d1268ac0cfb0f49/cs329z_hw1/llm.py#L303)).
The test doesn't catch it, so the whole test died instead of counting one
miss. We never found out which request caused it.

**How often it came up.** Once, in about 100 live calls. It didn't happen again.

**Remediation.** Nothing to do in P6, since the test isn't ours to change. P7's
loop must catch `OutputTruncated` and treat it as a malformed reply, so one
runaway answer doesn't end a whole session.

### Where P6 ended up

- **Deterministic tests:** all pass.
- **Live test:** 20/20 on the graded run, and about 97% per request across
  uncached runs.
- **Cost:** about half a cent for all of P6's live testing
  (`uv run python -m cs329z_hw1.llm` prints the ledger).
