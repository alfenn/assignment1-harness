"""Problem (bm25): a BM25 retriever on an inverted index, with no search libraries."""

from __future__ import annotations

import heapq
import math
from collections import Counter
from dataclasses import dataclass

from cs329z_hw1.tokenizer import tokenize

K1 = 1.5
B = 0.75


@dataclass
class BM25Index:
    # term -> [(doc_id, term frequency)], doc ids ascending.
    postings: dict[str, list[tuple[int, int]]]
    # term -> Lucene IDF, computed once at build time.
    idf: dict[str, float]
    # doc_id -> k1 * (1 - b + b * |d| / avgdl), the length part of the denominator.
    norms: list[float]


def build_index(docs: list[str]) -> BM25Index:
    """Index ``docs`` in one pass; a document's id is its list position."""
    postings: dict[str, list[tuple[int, int]]] = {}
    lengths: list[int] = []
    for doc_id, text in enumerate(docs):
        tokens = tokenize(text)
        lengths.append(len(tokens))
        for term, tf in Counter(tokens).items():
            entry = postings.get(term)
            if entry is None:
                postings[term] = [(doc_id, tf)]
            else:
                entry.append((doc_id, tf))

    n_docs = len(docs)
    # An all-blank corpus has avgdl 0; any value works since no term matches.
    avgdl = (sum(lengths) / n_docs) if n_docs and sum(lengths) else 1.0
    norms = [K1 * (1 - B + B * length / avgdl) for length in lengths]
    idf = {
        term: math.log((n_docs - len(entry) + 0.5) / (len(entry) + 0.5) + 1)
        for term, entry in postings.items()
    }
    return BM25Index(postings=postings, idf=idf, norms=norms)


def search(index: BM25Index, query: str, k: int) -> list[tuple[int, float]]:
    """Top-k ``(doc_id, score)``, best first, ties broken by lower doc_id.

    Reads only the postings of the query's distinct terms, so a document that
    shares no term with the query is never scored or returned.
    """
    if k <= 0:
        return []
    scores: dict[int, float] = {}
    norms = index.norms
    for term in set(tokenize(query)):
        entry = index.postings.get(term)
        if entry is None:
            continue
        idf = index.idf[term]
        for doc_id, tf in entry:
            weight = idf * tf * (K1 + 1) / (tf + norms[doc_id])
            scores[doc_id] = scores.get(doc_id, 0.0) + weight
    top = heapq.nsmallest(k, scores.items(), key=lambda item: (-item[1], item[0]))
    return [(int(doc_id), float(score)) for doc_id, score in top]
