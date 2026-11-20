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


HOWTO = re.compile(r"\b(how (do|can|to|should) (i|we|you)?|how to|where (can|do) (i|we)|steps to|kaise|kahan)\b"
                   r"|कैसे|कहाँ|كيف|أين", re.I)
PROBLEM = re.compile(
    r"\b(error|fail(ed|ing|s)?|reject(ed|ion)?|not (credited|working|showing|generated|received|paid|loading)|wrong"
    r"|mismatch|stuck|missing|unable|can'?t|cannot|issue|problem|urgent|nahi|nahin)\b"
    r"|नहीं|गलत|त्रुटि|لا أستطيع|لم يتم|لم تصل|خطأ|رفض|مشكلة", re.I)


def is_howto(text: str) -> bool:
    return bool(HOWTO.search(text or "")) and not PROBLEM.search(text or "")


FOLLOW_UP = re.compile(r"^\s*(and|also|what about|how about|same for|for|but|aur|और|भी|و|وماذا|ماذا عن)\b", re.I)


def is_follow_up(text: str) -> bool:
    """A message that only makes sense with the previous one: "and for contractors?", "aur UAE ke liye?"."""
    t = _clean(text)
    return bool(FOLLOW_UP.match(t)) or (0 < len(t.split()) <= 4 and not TOPIC_HINT.search(t) and kind(t) is None)
