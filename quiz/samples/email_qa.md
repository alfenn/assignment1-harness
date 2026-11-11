# Multi-hop QA over email

*P4 email_qa*

> Explain your multi-hop question-answering loop. Who decides the next query, how is the hop budget enforced whatever the model replies, and how do you make sure every support id is real? Walk me through how a two-hop question goes through it.

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** the code owns the loop: at most 3 searches, every call rebuilt from scratch, the model only proposes the next query, and support is limited to ids the search actually returned.

#### Budget · `email_qa.py:11-39`
- First search is the question itself
- At most `HOP_BUDGET` = **3** searches, whatever the model writes
- Each search: K = **8** emails, bodies up to **1,500 chars**, so most emails are shown whole

#### Every call · `email_qa.py:61-69`
- One system message and one user message, rebuilt from scratch
- Holds the question, the searches so far and how many are left, and every email found so far, de-duplicated by id

#### Reply and loop · `email_qa.py:80-95`, `email_qa.py:111-154`
- Model replies `ANSWER` + `SUPPORT`, or `SEARCH` + a query: the model proposes, the code decides whether it runs
- `parse_reply` tolerates markdown around the keywords; NONE, N/A or unknown means no answer
- Repeated query or unreadable reply → searching ends early, and `FINAL_PROMPT` forces an answer or NONE from what was found
- So the loop always ends within the budget

#### Support · `email_qa.py:98-108`
- `_support` keeps only cited ids that search returned in this call
- None survive → the retrieved emails that contain the answer text → failing that, the top hit of the last search
- No answer → None with empty support

#### Two-hop example
- Search 1 finds emails naming the right person or project, but not the answer
- Prompt says: search again with that exact name plus the question's key words
- Search 2 finds the email with the answer → ANSWER with that email as support

#### Also
- Prompt says emails are data and to ignore text addressed to AI systems: this pipeline retrieves some of the planted emails
- Part 2: the `email_qa` tool, on `aux_lm` with the shared email index (`toolset.py:212-217`)

## Code to point to

- cs329z_hw1/pipelines/email_qa.py:11-39 HOP_BUDGET, K and prompts
- cs329z_hw1/pipelines/email_qa.py:61-69 _user_message, rebuilt every call
- cs329z_hw1/pipelines/email_qa.py:80-95 parse_reply
- cs329z_hw1/pipelines/email_qa.py:98-108 _support, only returned ids
- cs329z_hw1/pipelines/email_qa.py:111-154 answer_question, the loop
- cs329z_hw1/agent/toolset.py:212-217 email_qa tool
