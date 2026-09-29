"""Cross-language retrieval.

The knowledge base is published by BIS in English, and keyword search
matches tokens. A question asked in Hindi, Tamil or Bengali therefore shares
no tokens with any passage, BM25 scores every chunk at zero, and the
assistant answers from general knowledge with no citation - exactly the
people the helpdesk is for get the worst answers.

So a question written mostly in a non-Latin script is rewritten into
English search terms before retrieval. Only the *search* changes: the model
still receives the user's own words and is told to answer in their
language, so nothing the user said is lost in translation.

The rewrite is additive. The search runs over the English terms *and* the
original text, so an IS number, a brand or an HUID the user typed survives
even if the translation drops it.

Hinglish - Hindi written in Latin script ("sone ki hallmarking kaise check
kare") - is deliberately left alone: its key terms are usually English
already ("hallmarking", "ISI"), and translating every Latin-script turn would
spend a model call on each English question for no gain.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from app.core.logging import get_logger
from app.models import ChatMessage, ModelError, get_gateway
from app.models import router as model_router

log = get_logger(__name__)

#: Above this share of non-Latin letters, a question is treated as written
#: in another script. Well below 1.0 because such questions routinely carry
#: Latin tokens - "IS 1293", "ISI", "BIS", "HUID".
NON_LATIN_THRESHOLD = 0.3

#: Generous on purpose. The fast route may be a reasoning model, which
#: spends its budget thinking before it writes a word: at 60 tokens
#: gpt-oss-20b returned an empty string with finish_reason "length", every
#: time, and every Hindi question was searched untranslated.
MAX_QUERY_TOKENS = 400
MAX_INPUT_CHARS = 600

#: A search query, not an answer. Longer output means the model answered
#: the question instead of translating it.
MAX_QUERY_CHARS = 200

TRANSLATE_PROMPT = """Rewrite the question below as a short English search query \
for the Bureau of Indian Standards (BIS) knowledge base.

Rules:
- Output ONLY the query, on one line. No quotes, no explanation.
- Translate the meaning into the English terms BIS documents use, for example \
"ISI mark" / "Standard Mark", "hallmarking", "HUID", "certification", \
"licence", "Quality Control Order", "laboratory", "complaint".
- Copy numbers, IS numbers (like IS 1293:2019), HUID codes and product names exactly.

Question: {question}"""


@dataclass(frozen=True)
class SearchQuery:
    """What retrieval searches for, and how it got there."""

    text: str
    #: The English rewrite, when one was made. None for an English question
    #: or when the rewrite was unavailable.
    translated: str | None = None
    #: Why no rewrite happened, when one was needed. Empty otherwise.
    note: str = ""


def non_latin_share(text: str) -> float:
    """Share of the letters in `text` that are outside the Latin script."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    foreign = sum(1 for ch in letters if "LATIN" not in unicodedata.name(ch, ""))
    return foreign / len(letters)


def needs_translation(text: str) -> bool:
    return non_latin_share(text) >= NON_LATIN_THRESHOLD


def search_query(question: str) -> SearchQuery:
    """The text to search the knowledge base with for this question.

    Never raises. A rewrite that fails leaves the original question in place,
    which is a weaker search, not a broken turn.
    """
    if not needs_translation(question):
        return SearchQuery(text=question)

    route = model_router.resolve(model_router.ROLE_FAST)
    try:
        completion = get_gateway().complete(
            [
                ChatMessage(
                    role="user",
                    content=TRANSLATE_PROMPT.format(
                        question=question[:MAX_INPUT_CHARS]
                    ),
                )
            ],
            temperature=0.0,
            max_tokens=MAX_QUERY_TOKENS,
            model=route.model or None,
        )
    except ModelError as exc:
        log.warning("Query translation unavailable: %s", exc)
        return SearchQuery(
            text=question,
            note="Could not translate the question for search; searched as written.",
        )

    translated = " ".join((completion.text or "").split()).strip("\"'` ")
    if (
        not translated
        or needs_translation(translated)
        or len(translated) > MAX_QUERY_CHARS
    ):
        # Empty, in the source language, or an answer rather than a query.
        # Either way it is not an English search query.
        return SearchQuery(
            text=question,
            note="Could not translate the question for search; searched as written.",
        )

    return SearchQuery(text=f"{translated} {question}", translated=translated)


__all__ = [
    "SearchQuery",
    "needs_translation",
    "non_latin_share",
    "search_query",
]
