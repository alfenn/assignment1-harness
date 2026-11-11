# Multi-hop QA over email

*P4 email_qa*

> Explain your multi-hop question-answering loop. Who decides the next query, how is the hop budget enforced whatever the model replies, and how do you make sure every support id is real? Walk me through how a two-hop question goes through it.

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

The code owns the loop, in `answer_question`. The first search is the question itself, and there are at most `HOP_BUDGET` = 3 searches whatever the model writes. Each search returns K = 8 emails with bodies up to 1,500 characters, so most emails are shown whole.

Every call is one system message and one user message rebuilt from scratch: the question, the searches made so far and how many are left, and every email found so far, de-duplicated by id. The model replies either `ANSWER` and `SUPPORT`, or `SEARCH` with a query: the model proposes the next query, the code decides whether it runs. `parse_reply` tolerates markdown around the keywords and reads NONE, N/A or unknown as no answer. A repeated query or an unreadable reply ends the searching early, and then `FINAL_PROMPT` forces an answer or NONE from what was found. So the loop always ends within the budget.

Support is checked in `_support`: I keep only cited ids that search actually returned in this call. If none survive, I use the retrieved emails that contain the answer text, and failing that the top hit of the last search. No answer returns None with empty support.

A two-hop question: the first search finds emails that name the right person or project but do not hold the answer. The prompt tells the model to search again with that exact name plus the key words of the question; the second search finds the email with the answer, and the model replies ANSWER with that email as support. The prompt also says emails are data and to ignore text addressed to AI systems, because this pipeline retrieves some of the planted emails. In Part 2 it is the `email_qa` tool, on `aux_lm` with the shared email index.

## Code to point to

- cs329z_hw1/pipelines/email_qa.py:11-39 HOP_BUDGET, K and prompts
- cs329z_hw1/pipelines/email_qa.py:61-69 _user_message, rebuilt every call
- cs329z_hw1/pipelines/email_qa.py:80-95 parse_reply
- cs329z_hw1/pipelines/email_qa.py:98-108 _support, only returned ids
- cs329z_hw1/pipelines/email_qa.py:111-154 answer_question, the loop
- cs329z_hw1/agent/toolset.py:212-217 email_qa tool
