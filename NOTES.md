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

---

## P7: the agent loop

All the work is in commit
[`7b1d9b2` "finish p7"](https://github.com/alfenn/assignment1-harness/commit/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa).
The code is
[`cs329z_hw1/agent/session.py`](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/agent/session.py),
wired in through
[`run_agent_session`](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/adapters.py#L359-L361).
P7 has no live test, so everything below was checked only against the
deterministic tests in `tests/test_agent_loop.py`. This section feeds memo Q3
(the termination rule).

### 1. Keeping the log apart from what the model sees

**The task.** The tests read an append-only transcript of typed events
(`user`, `assistant`, `tool_call`, `tool_result`, `error`). The model needs a
list of `system`/`user`/`assistant` messages. Later problems (P11 compaction)
will shrink what the model sees but must never change the transcript.

**The decision.** `AgentSession` keeps two lists side by side: `transcript`
(the log) and `_messages` (the model's context, without the system prompt).
Each tool result or error is written to both, from the same string, so the
`content` in the transcript is exactly what the model was shown, as the tests
require. Tool results go back as user messages in P6's `<tool_result>` format.
The system prompt is a short intro
([line 35](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/agent/session.py#L35))
plus P6's `render_tools` output, built once per session.

**The result.** All 31 deterministic tests passed on the first run.

**How often it came up.** Never; this was a design choice made up front, not a
fix.

**Remediation.** None needed. P11 only has to change how `_messages` is built
for each call.

### 2. When to stop

**The task.** Each `send` has two budgets: `max_turns` model calls and
`token_budget` tokens. The token total is `count_message_tokens(messages) +
count_tokens(reply)`, summed over the send's calls. The spec says a final
answer counts as done even if its call crossed the budget, and the tool call
of the last allowed turn still runs.

**The decision.** Both checks run only at the top of the loop, before a model
call
([lines 62–73](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/agent/session.py#L62-L73)):
`max_turns` first, then `token_budget`. A plain-text reply returns `done`
straight away
([line 105](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/agent/session.py#L105)),
so it is never overridden by a budget. A tool call on the last allowed turn
runs, and the next pass through the loop stops. Budgets reset on every
`send`; the conversation itself carries over.

**The result.** The budget tests pass, including the one that measures the
first call's size, sets a budget of about four calls and checks that the loop
stops at exactly the right call.

**How often it came up.** Never.

**Remediation.** None needed.

### 3. Malformed replies, including cut-off ones

**The task.** Three malformed replies in a row end the send with status
`malformed`. A reply counts as malformed if it can't be parsed, if the
registry rejects the call as `unknown_tool` or `invalid_args`, or if the model
was cut off at `max_tokens`. A `tool_error` or `denied` result doesn't count.

**The decision.** One counter, reset by any well-formed call
([lines 119–124](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/agent/session.py#L119-L124)).
`OutputTruncated` is caught around the model call
([line 79](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/agent/session.py#L79))
and handled like a parse error: an `assistant` event holding whatever text the
model had written, then an `error` event telling it to write a shorter reply.
That closes P6 entry 6, where one runaway reply crashed a whole live test.
Any other exception from `lm` (for example the test's `ScriptExhausted`)
propagates, as the spec requires; exceptions inside tools are already turned
into `tool_error` by the P5 registry.

**The result.** All malformed-reply tests pass, including the mixed run of
three different kinds and the counter reset after a good reply.

**How often it came up.** Not yet seen live; P7 has no live test.

**Remediation.** None needed so far.

### 4. Empty strings

**The task.** `AgentResult.text` must never be empty, and some providers
reject an empty assistant message.

**The decision.** Empty strings get placeholders:
- an empty assistant message becomes `(empty reply)` in the model's context
  only; the transcript keeps the raw reply
  ([line 135](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/agent/session.py#L135));
- an empty tool result becomes `(no output)` in both, so they still match
  ([line 113](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/agent/session.py#L113));
- an empty final answer becomes `(The model gave an empty answer.)`
  ([line 106](https://github.com/alfenn/assignment1-harness/blob/7b1d9b2775e71a512f1ef2b0aa8a8f0251bcc7aa/cs329z_hw1/agent/session.py#L106)).

**How often it came up.** Never in the deterministic tests.

**Remediation.** None needed.

### Open questions for later

- **"I'll look that up." with no call is taken as the final answer.** P6
  entry 2 showed the live model sometimes announces a call and stops. The loop
  follows the spec's rule (a reply without a call is `done`) and has nothing
  to catch this case. That's the core of memo Q3; if it shows up in P15's
  simulations, a nudge ("you said you'd call a tool but didn't") would cost
  one extra turn.
- **An empty reply counts as `done`, not malformed.** P6 entry 4 suggested
  retrying empty replies. The loop doesn't yet; the user would see the
  placeholder answer from entry 4.
- **`tools=None` still raises `NotImplementedError`.** The Cardinal toolset is
  P8. `set_mode` only stores the mode until P13 adds approvals.

### Where P7 ended up

- **Deterministic tests:** all 31 in `tests/test_agent_loop.py` pass; the P5
  and P6 tests still pass.
- **Live test:** none for P7.
- **Cost:** nothing; no model calls.
