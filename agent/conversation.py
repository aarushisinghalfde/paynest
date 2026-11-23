"""Chat behaviour that is not a support ticket: greetings, thanks, and messages too vague to act on.

kind(text) -> "greeting" | "thanks" | "vague" | None
is_howto(text) -> True for a how-to-use question with no sign of a problem
is_follow_up(text) -> True for a message that only makes sense with the previous turn
  greeting / thanks  a short message that is only that ("hi", "thanks!", "नमस्ते", "مرحبا")
  vague              three words or fewer with no topic we can act on ("payment delayed")
The router turns these into the chat and ask routes: a conversational reply or one
clarifying question, instead of a ticket acknowledgement.
"""

import re

GREETING = re.compile(
    r"^(hi+|hello+|hey+|hiya|yo|namaste|namaskar|salaam|salam|marhaba|good (morning|afternoon|evening)"
    r"|नमस्ते|नमस्कार|مرحبا|السلام عليكم|اهلا|أهلا)( there| team| payce)?$", re.I)
THANKS = re.compile(
    r"^(thanks?( you)?( so much| a lot)?|thx|ty|ok(ay)?( thanks?)?|great|cool|got it|perfect|bye|shukriya"
    r"|dhanyavaad|dhanyawad|धन्यवाद|शुक्रिया|شكرا|شكراً)$", re.I)
TOPIC_HINT = re.compile(r"\d|\b(pf|epf|esi|tds|wps|sif|payslip|salary|run|pt|gratuity|ecr|invoice|login|password)\b", re.I)


def _clean(text: str) -> str:
    return re.sub(r"[\s!.,?¡¿؟।]+", " ", text or "").strip()


def kind(text: str) -> str | None:
    t = _clean(text)
    if not t:
        return "vague"
    if GREETING.match(t):
        return "greeting"
    if THANKS.match(t):
        return "thanks"
    if len(t.split()) <= 3 and not TOPIC_HINT.search(t):
        return "vague"
    return None


HOWTO = re.compile(r"\b(how (do|can|to|should) (i|we|you)?|how to|where (can|do) (i|we)|steps to|kaise|kahan"
                   r"|kahaan|karne hain|karna hai|kar sakte|batao|bataiye|chahiye)\b"
                   r"|कैसे|कहाँ|كيف|أين", re.I)
PROBLEM = re.compile(
    r"\b(error|fail(ed|ing|s)?|reject(ed|ion)?|not (credited|working|showing|generated|received|paid|loading)|wrong"
    r"|mismatch|stuck|missing|unable|can'?t|cannot|issue|problem|urgent|nahi|nahin"
    # Q3 problem reports a guide does not fix: "token returns 401", "webhook not firing", "arrears not included"
    r"|not (included|picked up|reflected|firing|triggering|syncing|updating|applied)|did ?n[o']?t|does ?n[o']?t"
    r"|duplicate[sd]?|doubled|returns? (an? )?(error|[45]\d\d)|[45]0\d error|since (yesterday|today|the (last )?update)|blank|empty|loop|redirect\w*|keeps? (failing|logging)"
    r"|aa rah[ie]|nahi (aa|ho|khul))\b"
    r"|नहीं|गलत|त्रुटि|لا أستطيع|لم يتم|لم تصل|خطأ|رفض|مشكلة", re.I)


def is_howto(text: str) -> bool:
    return bool(HOWTO.search(text or "")) and not PROBLEM.search(text or "")


FOLLOW_UP = re.compile(r"^\s*(and|also|what about|how about|same for|for|but|aur|और|भी|و|وماذا|ماذا عن)\b", re.I)


def is_follow_up(text: str) -> bool:
    """A message that only makes sense with the previous one: "and for contractors?", "aur UAE ke liye?"."""
    t = _clean(text)
    return bool(FOLLOW_UP.match(t)) or (0 < len(t.split()) <= 4 and not TOPIC_HINT.search(t) and kind(t) is None)


QUESTION_START = re.compile(
    r"^\s*(what|how|where|when|why|which|who|can|could|is|are|do|does|will|should|kya|kaise|kab|kahan|kyun"
    r"|क्या|कैसे|कब|कहाँ|क्यों|ما|ماذا|كيف|متى|هل|أين|لماذا)\b", re.I)


RUN_STATUS = re.compile(r"\b(status|progress|stuck|update|where is|kahan hai|kya hua)\b|حالة|स्थिति", re.I)


def is_run_status(text: str) -> bool:
    """Asks where a specific payroll run is ("What is the status of payroll run PR-202609?")."""
    from agent.tools import RUN_ID_RE
    return bool(RUN_ID_RE.search(text or "")) and bool(RUN_STATUS.search(text or ""))


FIGURE_ASK = re.compile(
    r"\b(rate|ceiling|limit|slab|threshold|percentage|how much|calculat\w*|kitn[aie]|kitna)\b|कितन[ाीे]|गणना|सीमा"
    r"|احتساب|حساب|كم\b|نسبة|الحد", re.I)


def asks_statutory_figure(text: str) -> bool:
    """Asks for a statutory rate, limit or calculation (PF ceiling, gratuity, TDS slab, WPS format) in any
    language. Those answers always get a person's approval, whatever team the words resemble."""
    from agent.tools import RATE_TRIGGERS
    return any(rx.search(text or "") for rx, _, _ in RATE_TRIGGERS) and bool(FIGURE_ASK.search(text or ""))


def is_new_question(text: str) -> bool:
    """A self-contained question ("What is the status of run PR-1?"), not an answer to ours."""
    return bool(QUESTION_START.match(text or "")) and len(_clean(text).split()) >= 4
