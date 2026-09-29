"""Lexical retrieval: BM25 over the scoped chunk set.

Why BM25 is the floor rather than an afterthought:

  - It needs no model, no GPU, no second service and no network. A fresh
    checkout retrieves correctly the moment a document is indexed, which
    means retrieval is demonstrable on a laptop with no internet.
  - Industrial queries are full of exact tokens - `P-204`, `CDU-II`,
    `API 610`, `2.5 mm/s`. Embeddings are notoriously weak on those; an
    exact-match scorer is not. In this corpus lexical search is not a
    fallback, it is the half that gets tag numbers right.
  - It degrades honestly. There is no configuration under which it silently
    stops working.

Semantic search is fused on top when an embedder is configured
(`retriever.py`), because the two fail in different places: BM25 misses
paraphrase, vectors miss identifiers.

Scaling: scoring runs in Python over every chunk the user may see. That is
right for a plant-scale corpus of thousands of chunks and wrong for
millions. The replacement is PostgreSQL full-text search or the sparse index
of a vector database; `Bm25Index` is deliberately a plain object over a list
of documents so that swap stays local to this file.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

#: Keeps identifiers whole. `p-204`, `cdu-ii`, `2.5`, `api610`, `iso/tr` all
#: survive as single tokens, which is the entire point for this corpus - a
#: tokenizer that split on the hyphen would turn "P-204" into "p" and "204"
#: and match every pump on site.
_TOKEN = re.compile(r"[a-z0-9]+(?:[-_./][a-z0-9]+)*")

#: A short list only. Aggressive stopword removal hurts technical text,
#: where "no", "not" and "off" carry meaning.
_STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have how in into is it its of on or
    that the their there these this to was were what when where which who
    will with
    """.split()
)

# Okapi BM25 parameters. k1 controls term-frequency saturation, b controls
# length normalisation; these are the standard defaults and there is no
# tuning data yet to justify moving them.
K1 = 1.5
B = 0.75


#: Everyday words for things the BIS corpus names formally. Applied to the
#: query only: "labs in Maharashtra" should reach a list of "laboratories".
_ALIASES = {
    "lab": ("laboratory",),
    # Four letters, so plural folding leaves these alone.
    "labs": ("lab", "laboratory"),
    "fees": ("fee", "charge"),
    "cert": ("certification",),
    "licence": ("license",),
    "license": ("licence",),
    "verify": ("verification",),
    "register": ("registration",),
    "fee": ("charge",),
    "fake": ("misuse", "spurious"),
}


def _stem(token: str) -> str:
    """Plural folding for plain words, nothing more.

    "laboratories" -> "laboratory", "labs" -> "lab", "charges" -> "charge".
    Identifiers (anything with a digit or separator) are left alone, and so
    are short words, where a trailing "s" is usually not a plural ("gas",
    "bis").
    """
    if len(token) <= 4 or not token.isalpha():
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith(("sses", "ss", "us", "is")):
        return token
    if token.endswith("s"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase, keep identifiers intact, fold plurals, drop stopwords."""
    tokens = _TOKEN.findall(text.lower())
    return [_stem(t) for t in tokens if t not in _STOPWORDS]


def expand_query_tokens(tokens: list[str]) -> list[str]:
    """Add the split form of hyphenated identifiers alongside the whole one.

    A document may write "P 204" or "P204" where the query writes "P-204".
    Keeping the intact token *and* its parts means an exact match still
    scores highest, while a differently punctuated one still matches at all.
    """
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(_ALIASES.get(token, ()))
        if any(sep in token for sep in "-_./"):
            parts = [p for p in re.split(r"[-_./]", token) if p]
            if len(parts) > 1:
                expanded.extend(parts)
                expanded.append("".join(parts))
    return expanded


@dataclass
class _Entry:
    key: str
    length: int
    frequencies: Counter


class Bm25Index:
    """An in-memory BM25 index over one search's candidate set.

    Built per query rather than cached, because the candidate set is already
    filtered by the caller's document permissions. A cached global index
    would have to be re-filtered per user anyway, and a stale one would be a
    way to leak a document that had just been revoked.
    """

    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._document_frequency: Counter = Counter()
        self._total_length = 0

    def add(self, key: str, text: str) -> None:
        tokens = tokenize(text)
        frequencies = Counter(tokens)

        self._entries.append(_Entry(key=key, length=len(tokens), frequencies=frequencies))
        self._document_frequency.update(frequencies.keys())
        self._total_length += len(tokens)

    @property
    def size(self) -> int:
        return len(self._entries)

    def _average_length(self) -> float:
        if not self._entries:
            return 0.0
        return self._total_length / len(self._entries)

    def _idf(self, term: str) -> float:
        """Robertson/Sparck-Jones IDF, floored at zero.

        The classic form goes negative for terms present in more than half
        the corpus. On a small corpus that is common, and a negative
        contribution would let a passage be *penalised* for containing a
        query term. Flooring at zero keeps scores monotonic in matches.
        """
        n = len(self._entries)
        df = self._document_frequency.get(term, 0)
        if df == 0:
            return 0.0
        return max(0.0, math.log(1.0 + (n - df + 0.5) / (df + 0.5)))

    def search(self, query: str) -> list[tuple[str, float]]:
        """Score every entry against `query`, best first.

        Entries scoring zero - no query term present at all - are dropped
        rather than returned with a zero score, so the caller can tell
        "nothing matched" from "everything matched equally".
        """
        if not self._entries:
            return []

        terms = expand_query_tokens(tokenize(query))
        if not terms:
            return []

        # A term repeated in the query should not count twice, but the
        # expansion above may legitimately produce duplicates.
        weights = Counter(terms)
        average = self._average_length() or 1.0

        scored: list[tuple[str, float]] = []
        for entry in self._entries:
            score = 0.0
            for term, weight in weights.items():
                frequency = entry.frequencies.get(term, 0)
                if not frequency:
                    continue
                idf = self._idf(term)
                if idf <= 0.0:
                    continue
                denominator = frequency + K1 * (
                    1.0 - B + B * (entry.length / average)
                )
                # Duplicate query terms are damped rather than added
                # linearly; a query is not a document.
                score += idf * (frequency * (K1 + 1.0) / denominator) * (
                    1.0 + math.log(weight)
                )
            if score > 0.0:
                scored.append((entry.key, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored


__all__ = ["Bm25Index", "expand_query_tokens", "tokenize"]
