"""Conservative lexical deduplication; preserve changed numbers and negations."""

import re
from difflib import SequenceMatcher


def tokens(text):
    return re.findall(r"\w+", text.casefold())


def near_duplicate(left: str, right: str, *, claim: bool = False) -> bool:
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return False
    protected = lambda words: [word for word in words if any(char.isdigit() for char in word) or word in {"not", "no", "never", "without", "cannot", "false", "true"}]
    if protected(a) != protected(b):
        return False
    if a == b:
        return True
    if claim:
        # ponytail: conservative lexical matching; no guessed semantic equivalence between entities.
        content = lambda words: [word for word in words if word not in {"a", "an", "the"}]
        return content(a) == content(b)
    return min(len(a), len(b)) >= 20 and SequenceMatcher(None, a, b, autojunk=False).ratio() >= .95
