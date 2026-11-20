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
INCIDENT = {
    "en": "We are aware of an issue affecting several of your users and are working on it. Your ticket {ref} is "
    "linked to it, and we will update you here as soon as it is fixed.",
    "hi-Latn": "Hume ek issue ki jaankari hai jo aapke kai users ko affect kar raha hai. Aapka ticket {ref} usse "
    "linked hai; fix hote hi hum yahin update denge.",
    "hi": "हमें एक समस्या की जानकारी है जो आपके कई उपयोगकर्ताओं को प्रभावित कर रही है। आपका टिकट {ref} उससे जुड़ा है; "
    "ठीक होते ही हम यहीं अपडेट देंगे।",
    "ar": "نحن على علم بمشكلة تؤثر على عدد من مستخدميك ونعمل على حلها. تذكرتك {ref} مرتبطة بها، وسنبلغك هنا فور حلها.",
}
DUPLICATE = {
    "en": "Thanks for following up. We have linked this message to your earlier ticket {duplicate_of} "
    "so nothing is lost; the team handling it will reply there.",
    "hi": "फ़ॉलो-अप के लिए धन्यवाद। हमने यह संदेश आपके पिछले टिकट {duplicate_of} से जोड़ दिया है; वहीं जवाब मिलेगा।",
    "ar": "شكراً للمتابعة. ربطنا هذه الرسالة بتذكرتك السابقة {duplicate_of} حتى لا يضيع شيء، وسيرد الفريق هناك.",
}
BLOCKED = {
    "en": "Thanks, we have received your message ({ref}). A specialist will review it and reply.",
    "hi": "धन्यवाद, हमें आपका संदेश ({ref}) मिल गया है। एक विशेषज्ञ इसे देखकर जवाब देंगे।",
    "ar": "شكراً، استلمنا رسالتك ({ref}). سيراجعها أحد المختصين ويرد عليك.",
}


GREETING = {
    "en": "Hi! I'm the Payce Support assistant. Ask me about payroll runs, payslips, statutory rules or anything "
    "else in Payce, and I'll answer from our approved guides or pass it to the right team.",
    "hi-Latn": "Namaste! Main Payce Support assistant hoon. Payroll, payslip, statutory rules ya Payce ke baare mein "
    "kuch bhi poochiye; main approved guides se jawab dunga ya sahi team tak pahunchaunga.",
    "hi": "नमस्ते! मैं Payce सपोर्ट असिस्टेंट हूँ। पेरोल, पेस्लिप, वैधानिक नियम या Payce के बारे में कुछ भी पूछिए।",
    "ar": "مرحباً! أنا مساعد دعم Payce. اسألني عن الرواتب أو قسائم الراتب أو القواعد النظامية أو أي شيء في Payce.",
}
THANKS = {
    "en": "You're welcome! Anything else I can help with?",
    "hi-Latn": "Koi baat nahi! Aur kuch madad chahiye?",
    "hi": "आपका स्वागत है! क्या कुछ और मदद चाहिए?",
    "ar": "على الرحب والسعة! هل يمكنني مساعدتك في شيء آخر؟",
}
CLARIFY = {
    "en": "I'd like to help with that. Could you tell me a little more: which payroll month, how many employees are "
    "affected, and what you see on screen (an error message or a status)?",
    "hi-Latn": "Main madad karna chahta hoon. Thoda aur bataiye: kaunsa payroll month, kitne employees affected hain, "
    "aur screen par kya dikh raha hai (error ya status)?",
    "hi": "मैं मदद करना चाहता हूँ। थोड़ा और बताइए: कौन सा पेरोल महीना, कितने कर्मचारी प्रभावित हैं, और स्क्रीन पर क्या दिख रहा है?",
    "ar": "يسعدني المساعدة. هل يمكنك توضيح المزيد: أي شهر رواتب، وكم عدد الموظفين المتأثرين، وما الذي يظهر على الشاشة؟",
}


def render(kind: str, language: str, **kw) -> str:
    table = {"ack": ACK, "incident": INCIDENT, "duplicate": DUPLICATE, "greeting": GREETING, "thanks": THANKS,
             "clarify": CLARIFY}.get(kind, BLOCKED)
    return table.get(language, table["en"]).format(**kw)
