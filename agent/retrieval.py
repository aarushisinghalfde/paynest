"""Phase 8 retrieval: approved knowledge only, filtered by tenant region and question date.

Hybrid lexical ranking, no embedding model needed:
  - BM25 over word tokens (English, Hinglish and Hindi/Arabic words alike);
  - character 3-gram overlap, which catches spelling variants ("salry", "gratuty").
Filters come first and are hard: a chunk is a candidate only if its region is the tenant's
region or ALL, and it is valid on the date the QUESTION is about (loader.knowledge.valid_on).
A superseded excerpt is therefore never returned for a date after the rule changed.
"""

import math
import re
from collections import Counter
from datetime import date, datetime

from loader.knowledge import valid_on

WORD_RE = re.compile(r"[\wऀ-ॿ؀-ۿ]+", re.UNICODE)
STOP = {
    "the", "a", "an", "is", "are", "for", "of", "to", "in", "on", "and", "or", "my", "our", "we", "i",
    "it", "this", "that", "with", "how", "what", "do", "does", "can", "please", "hai", "ka", "ki", "ke",
    "kya", "hum", "mera", "hamara", "se", "ko", "me", "mein", "see", "get", "where", "find", "need", "want",
}
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
MONTHS |= {k[:3]: v for k, v in list(MONTHS.items())} | {"sept": 9}
MONTH_RE = re.compile(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b\.?(?:\s*'?(\d{2,4}))?", re.I)
ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


def _stem(w: str) -> str:
    """Light English stemming so "payslip" finds "payslips" and "downloading" finds "download"."""
    for suf in ("ing", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf) and w.isascii():
            return w[: -len(suf)]
    return w


def words(text: str) -> list[str]:
    return [_stem(w) for w in (m.lower() for m in WORD_RE.findall(text or "")) if w not in STOP and len(w) > 1]


def trigrams(text: str) -> set[str]:
    t = " ".join(words(text))
    return {t[i : i + 3] for i in range(max(len(t) - 2, 0))}


def _as_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v:
        return date.fromisoformat(v[:10])
    return date.today()


def question_date(text: str, created) -> date:
    """The date a question is about: an ISO date or a month it names, else the ticket date.

    A month without a year means the latest such month not after the ticket date, so
    "July payroll" asked in September is July of the same year. The 1st of the month is used.
    """
    created_d = _as_date(created)
    m = ISO_RE.search(text or "")
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = MONTH_RE.search(text or "")
    if not m:
        return created_d
    month = MONTHS[m[1].lower().rstrip(".")]
    if m[2]:
        year = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
    else:
        year = created_d.year if month <= created_d.month else created_d.year - 1
    return date(year, month, 1)


# The approved knowledge base is English. Arabic and Hindi questions are expanded with the
# English words for the topics customers actually raise in those languages (from the data
# room's Arabic/Hindi tickets: salaries not credited, WPS/SIF rejections, gratuity, payslip
# download, login), so they find the same guides.
GLOSSARY = [
    (re.compile(r"كشوف الرواتب|كشف الراتب|قسيمة الراتب|قسائم الراتب|पेस्लिप|वेतन पर्ची|सैलरी स्लिप"), "payslip download"),
    (re.compile(r"تسجيل الدخول|كلمة المرور|लॉगिन|पासवर्ड|लॉग इन"), "login password sign-in"),
    (re.compile(r"مكافأة نهاية الخدمة|نهاية الخدمة|ग्रेच्युटी"), "gratuity end-of-service calculation"),
    (re.compile(r"حماية الأجور|ملف الأجور|ملف الرواتب"), "wps sif file bank"),
    (re.compile(r"لم تصل|لم يتم تحويل|वेतन नहीं|सैलरी नहीं"), "salary not credited bank file"),
    (re.compile(r"موظف جديد|إضافة موظف|नया कर्मचारी|कर्मचारी जोड़"), "adding new employee"),
    (re.compile(r"إجازة|छुट्टी"), "leave policy"),
    (re.compile(r"فاتورة|बिल|चालान"), "invoice billing"),
    (re.compile(r"भविष्य निधि|पीएफ"), "pf wage ceiling"),
    (re.compile(r"टीडीएस|आयकर"), "tds slabs"),
]


def expand(text: str) -> str:
    extra = [words for rx, words in GLOSSARY if rx.search(text or "")]
    return " ".join([text or "", *extra])


class Retriever:
    def __init__(self, chunks: list[dict], rules: list[dict] | None = None, k1: float = 1.4, b: float = 0.75,
                 examples: list[dict] | None = None):
        titles = {c["kb_id"]: c for c in chunks if c.get("source_kind") == "kb_title" and c.get("kb_id")}
        # Past customer questions an agent solved with a KB article: customers' own words for each guide.
        example_chunks = [
            {"chunk_id": f"{e['kb_id']}#example{i}", "kb_id": e["kb_id"], "source_kind": "resolved_example",
             "region": titles[e["kb_id"]]["region"], "topic": titles[e["kb_id"]].get("topic"),
             "title": titles[e["kb_id"]]["title"], "content": e["question"][:600]}
            for i, e in enumerate(examples or []) if e.get("kb_id") in titles and e.get("question")
        ]
        self.chunks = [dict(c, effective_from=_opt(c.get("effective_from")), effective_to=_opt(c.get("effective_to")))
                       for c in [*chunks, *example_chunks]]
        self.rules = [dict(r, effective_from=_as_date(r["effective_from"])) for r in (rules or [])]
        self.docs = [words(f"{c.get('title') or ''} {c.get('topic') or ''} {c['content']}") for c in self.chunks]
        self.grams = [trigrams(f"{c.get('title') or ''} {c['content']}") for c in self.chunks]
        self.avg = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df = Counter(w for d in self.docs for w in set(d))
        n = len(self.docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.k1, self.b = k1, b
        sig = sorted(f"{c['chunk_id']}|{c.get('effective_from')}|{c.get('effective_to')}" for c in self.chunks
                     if c["source_kind"] != "resolved_example")
        self.version = __import__("hashlib").sha256("\n".join(sig).encode()).hexdigest()[:12]  # KB version

    def _bm25(self, q: list[str], i: int) -> float:
        tf, dl = Counter(self.docs[i]), len(self.docs[i]) or 1
        s = 0.0
        for w in set(q):
            if w in tf:
                f = tf[w]
                s += self.idf.get(w, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
        return s

    def search(self, text: str, region: str | None, as_of: date, k: int = 4, kinds=None) -> list[dict]:
        text = expand(text)
        q, qg = words(text), trigrams(text)
        if not q:
            return []
        hits = []
        for i, c in enumerate(self.chunks):
            if region and c["region"] not in (region, "ALL"):
                continue
            if not valid_on(c, as_of):
                continue
            if kinds and c["source_kind"] not in kinds:
                continue
            lex = self._bm25(q, i)
            if lex <= 0:
                continue
            g = self.grams[i]
            char = len(qg & g) / max(len(qg | g), 1)
            score = lex + 4.0 * char + (0.5 if c["source_kind"] == "rule" else 0.0)
            hits.append({**_public(c), "score": round(score, 3)})
        hits.sort(key=lambda h: (-h["score"], h["chunk_id"]))
        return hits[:k]


    def howto_articles(self, text: str, region: str | None, as_of: date, k: int = 3,
                       with_excerpts: bool = False) -> list[dict]:
        """The KB articles that answer a how-to question, best first.

        An article scores by its title/excerpt and by past customer questions it solved; the hit
        returned is the article's title chunk (plus its excerpt text when the excerpt is real and
        valid on the date), with `solved` = how many similar past questions it resolved.
        Excerpts are off by default: the only real ones are statutory (PF, WPS), which auto-sent
        replies must never quote.
        """
        hits = self.search(text, region, as_of, k=40,
                           kinds=("kb_title", "kb_excerpt", "kb_article", "resolved_example"))
        by_kb: dict[str, dict] = {}
        for h in hits:
            if str(h.get("topic") or "").startswith("statutory") and not with_excerpts:
                continue  # imported statutory articles: human-review route only
            kb = h.get("kb_id") or h["chunk_id"].split("#")[0]
            a = by_kb.setdefault(kb, {"score": 0.0, "solved": 0, "excerpt": None, "steps": []})
            a["score"] = max(a["score"], h["score"])
            a["solved"] += h["source_kind"] == "resolved_example"
            if h["source_kind"] == "kb_excerpt" and with_excerpts:
                a["excerpt"] = h["content"]
            if h["source_kind"] == "kb_article" and len(a["steps"]) < 2:
                a["steps"].append(h["content"])  # imported article text, best-matching parts first
        out = []
        for kb, a in by_kb.items():
            title = next((c for c in self.chunks if c["chunk_id"] == f"{kb}#title"), None)
            if title is None:
                continue
            body = "\n".join([*(a["steps"]), *([a["excerpt"]] if a["excerpt"] else [])])
            content = title["content"] + (f"\n{body}" if body else "")
            out.append({**_public(title), "content": content, "score": round(a["score"] + 0.6 * min(a["solved"], 5), 3),
                        "solved": a["solved"], "has_steps": bool(body), "steps": body})
        out.sort(key=lambda h: (-h["score"], h["chunk_id"]))
        return out[:k]


def _opt(v):
    return None if v in (None, "") else _as_date(v)


def _public(c: dict) -> dict:
    keys = ("chunk_id", "kb_id", "source_kind", "region", "topic", "title", "content", "effective_from",
            "effective_to", "superseded_by")
    return {k: c.get(k) for k in keys}
