# Retrieval as a tool

*P9 search_docs · memo Q4*

> Walk me through your document search tool. What is a passage, how do you choose the snippet a search result shows, and how big is a read_doc window, and why that size? Show me where.

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** passages are what gets ranked, a snippet centres on the rarest query term, and a `read_doc` window is 600 tokens so the model can afford several reads under the 6,000-token cap.

#### Passage · `search_docs.py:74-99`
- Consecutive non-blank lines in one section, cut when it would pass **440 chars**
- Minimum **8 tokens**, so a table, a list, or a heading with its first line stays together
- Each passage is one BM25 document, indexed as title + section heading + text
- Whole documents are never ranked against each other

#### Snippet · `search_docs.py:123-148`
- Not the first N characters
- Query terms sorted by IDF, rarest first
- `_excerpt` centres up to **440 chars** on the first occurrence of the rarest term the passage contains
- `_snippet` puts the section heading in front (up to 80 chars) and caps the whole snippet at **600 chars**, under the 150-token limit

#### Results · `search_docs.py:151-177`
- At most **2 results per document**, drawn from `max(8k, 40)` candidates, so an older and a newer version of a policy can both appear
- Each document's date extracted and shown; the output says the later date is the current rule (the superseded-policy case)

#### read_doc window · `search_docs.py:183-207`
- Whole lines from start_line until **600 tokens** or **40 non-blank lines**, whichever comes first
- Numbered, with a line saying how to continue
- Why 600, not the 1,500 the tests allow: the live test caps these two tools at **6,000 tokens** per conversation, and 1,500-token windows reach that after four reads

#### Extras · `toolset.py:163-206`
- An empty result suggests other keywords
- Passages addressed to AI agents are flagged

## Code to point to

- cs329z_hw1/pipelines/search_docs.py:39-48 snippet, passage and window sizes
- cs329z_hw1/pipelines/search_docs.py:74-99 _passages
- cs329z_hw1/pipelines/search_docs.py:123-148 _excerpt and _snippet
- cs329z_hw1/pipelines/search_docs.py:151-177 search_docs, two per document
- cs329z_hw1/pipelines/search_docs.py:183-207 read_doc window
- cs329z_hw1/agent/toolset.py:163-206 what the model sees
