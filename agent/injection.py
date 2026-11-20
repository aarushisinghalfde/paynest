"""Prompt-injection rules (the cheap first layer; the classifier's is_injection and, once
Bedrock is available, the Guardrails prompt-attack filter are the others)."""
import re

PATTERNS = [
    r"\bignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)\b",
    r"\bdisregard (?:all |the )?(?:previous|prior|above) ",
    r"\byou are now (?:in )?(?:admin|developer|god|dan|jailbreak)\b", r"\badmin mode\b", r"\bdeveloper mode\b",
    r"\b(?:reveal|print|show|repeat) (?:your |the )?(?:system )?(?:prompt|instructions)\b",
    r"\bact as (?:the )?(?:system|administrator|admin)\b",
    r"\b(?:list|send|reply with) (?:all |every )?(?:the )?(?:customer|user|admin)s?'? (?:admin )?emails?\b",
    r"\bdo not (?:mention|tell) (?:this|anyone)\b",
    r"pichle (?:sabhi )?(?:instructions|nirdesh) (?:ko )?ignore",              # Hinglish
    r"पिछले (?:सभी )?निर्देश(?:ों)? (?:को )?(?:अनदेखा|नज़रअंदाज़|ignore)",      # Hindi
    r"تجاهل (?:جميع |كل )?التعليمات (?:السابقة)?",                             # Arabic
]
_RX = [re.compile(p, re.I) for p in PATTERNS]


def detect(text: str) -> list[str]:
    """Ids of the rules that fired (empty = no injection found)."""
    return [f"inj{i:02d}" for i, rx in enumerate(_RX) if rx.search(text or "")]
