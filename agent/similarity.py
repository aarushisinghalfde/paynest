"""Text fingerprints for dedupe and incidents: masked text, normalised, as character 4-grams."""
import re

_TOKEN = re.compile(r"<[A-Z_]+_\d+>")
_NOISE = re.compile(r"\b(?:re|fw|fwd)\s*:|following up on my earlier ticket pn-\d+[.,]?|no reply yet[.,]?|"
                    r"second request\s*-?|please (?:help|check|fix)[.!]?", re.I)
EXPLICIT_REF = re.compile(r"(?:earlier|previous|my) ticket (PN-\d+)", re.I)


def normalise(text: str) -> str:
    t = _NOISE.sub(" ", _TOKEN.sub(" ", text or ""))
    t = re.sub(r"\d+", "0", t.lower())
    return re.sub(r"[^\wऀ-ॿ؀-ۿ]+", " ", t).strip()


def shingles(text: str, n: int = 4) -> set[str]:
    t = normalise(text)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0

RESUBMIT_MARKER = re.compile(r"(?:^|\s)(?:re|fw|fwd)\s*:|following up|second request|earlier ticket|previous ticket|"
                             r"no reply|still waiting|again\b|dobara|phir se|مرة أخرى|फिर से", re.I)
_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "was", "with", "by", "our", "we",
         "my", "this", "that", "it", "be", "from", "at", "not", "but", "has", "have", "after", "before"}


def words(text: str) -> set[str]:
    return {w for w in normalise(text).split() if len(w) > 2 and w not in _STOP}


def containment(small: set, big: set) -> float:
    """Share of `small` found in `big` (an issue summary inside a longer ticket)."""
    return len(small & big) / len(small) if small else 0.0
