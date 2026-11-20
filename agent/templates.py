"""Fixed reply templates (phase 5 stand-in for drafting). One per language."""

ACK = {
    "en": "Thanks for contacting Payce Support. Your ticket {ref} is with our {team} team. "
    "We will reply here as soon as we have checked it.",
    "hi-Latn": "Payce Support se sampark karne ke liye dhanyavaad. "
    "Aapka ticket {ref} hamari {team} team ke paas hai. "
    "Jaanch ke baad hum yahin jawab denge.",
    "hi": "Payce सपोर्ट से संपर्क करने के लिए धन्यवाद। आपका टिकट {ref} हमारी {team} टीम के पास है। "
    "जाँच के बाद हम यहीं जवाब देंगे।",
    "ar": "شكراً لتواصلك مع دعم Payce. تذكرتك {ref} لدى فريق {team}. سنرد هنا فور الانتهاء من المراجعة.",
}
BLOCKED = {
    "en": "Thanks, we have received your message ({ref}). A specialist will review it and reply.",
}


def render(kind: str, language: str, **kw) -> str:
    table = ACK if kind == "ack" else BLOCKED
    return table.get(language, table["en"]).format(**kw)
