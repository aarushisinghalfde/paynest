#!/usr/bin/env python3
"""Generate the 60 seeded tickets for the phase 3 leak test (all values are synthetic).

    python scripts/make_pii_seed.py   ->  tests/fixtures/pii_seeded.json

15 tickets each in English, Hinglish, Hindi and Arabic, for India and UAE tenants.
Identifiers carry valid checksums (Aadhaar Verhoeff, Emirates ID Luhn, IBAN mod-97), and
some Hindi and Arabic tickets write numbers in native digits. Every inserted value is
listed in raw_values; after masking, none of them may remain.
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pii.validators import verhoeff_check_digit  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OUT = FIXTURES / "pii_seeded.json"
OUT_NER = FIXTURES / "pii_seeded_ner.json"   # names in mid-sentence: need the Presidio layer
rng = random.Random(20261120)

IN_FIRST = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Ananya", "Rohan", "Kavya", "Arjun", "Meera",
            "Sanjay", "Pooja", "Nikhil", "Divya", "Karan"]
IN_LAST = ["Sharma", "Verma", "Iyer", "Reddy", "Patel", "Gupta", "Nair", "Menon", "Joshi", "Kulkarni",
           "Banerjee", "Chatterjee", "Malhotra", "Singhania", "Deshpande"]
HI_FIRST = ["राहुल", "प्रिया", "अमित", "स्नेहा", "विक्रम", "अनन्या", "रोहन", "काव्या", "अर्जुन", "मीरा"]
HI_LAST = ["शर्मा", "वर्मा", "गुप्ता", "पटेल", "जोशी", "मिश्रा", "यादव", "सिंह", "चौहान", "त्रिपाठी"]
AR_FIRST_LAT = ["Ahmed", "Fatima", "Omar", "Mariam", "Khalid", "Aisha", "Yousef", "Noura", "Hamdan", "Layla"]
AR_LAST_LAT = ["Al Mansoori", "Al Hashimi", "Al Nuaimi", "Al Shamsi", "Al Mazrouei", "Al Falasi"]
AR_FIRST = ["أحمد", "فاطمة", "عمر", "مريم", "خالد", "عائشة", "يوسف", "نورة", "حمدان", "ليلى"]
AR_LAST = ["المنصوري", "الهاشمي", "النعيمي", "الشامسي", "المزروعي", "الفلاسي"]
DOMAINS = ["gmail.com", "yahoo.co.in", "outlook.com", "acme-corp.in", "gulfco.ae"]
BANKS = ["HDFC", "ICIC", "SBIN", "UTIB", "KKBK"]

DEVA = str.maketrans("0123456789", "०१२३४५६७८९")
ARAB = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def digits(n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def aadhaar() -> str:
    base = rng.choice("23456789") + digits(10)
    return base + verhoeff_check_digit(base)


def pan(last: str) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    head = "".join(rng.choice(letters) for _ in range(3))
    return head + "P" + last[0].upper() + digits(4) + rng.choice(letters)


def uan() -> str:
    return "10" + digits(10)


def luhn_digit(partial: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(partial)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def emirates_id() -> str:
    partial = "784" + str(rng.randint(1975, 2002)) + digits(7)
    return partial + luhn_digit(partial)


def iban_ae() -> str:
    bban = digits(3) + digits(16)
    numeric = "".join(str(int(c, 36)) for c in bban + "AE00")
    check = 98 - int(numeric) % 97
    return f"AE{check:02d}{bban}"


def fmt_iban(iban: str) -> str:
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def phone_in() -> str:
    return rng.choice("6789") + digits(9)


def phone_ae() -> str:
    return "5" + rng.choice("024568") + digits(7)


def email(first: str, last: str) -> str:
    return f"{first.lower()}.{last.lower().replace(' ', '')}@{rng.choice(DOMAINS)}"


def ticket(i, lang, region, sender, sender_email, sender_phone, body, raw):
    return {"id": f"SEED-{i:03d}", "language": lang, "tenant_region": region, "sender_name": sender,
            "sender_email": sender_email, "sender_phone": sender_phone, "body": body,
            "raw_values": sorted(set(raw))}


def english(i):
    if i % 2 == 0:  # India tenant
        f, last = rng.choice(IN_FIRST), rng.choice(IN_LAST)
        f2, l2 = rng.choice(IN_FIRST), rng.choice(IN_LAST)
        name, name2 = f"{f} {last}", f"{f2} {l2}"
        a, p, u, ph, em = aadhaar(), pan(last), uan(), phone_in(), email(f, last)
        acct, ifsc = digits(rng.choice([11, 12, 14])), rng.choice(BANKS) + "0" + digits(6)
        if acct[:4].isdigit() and len(acct) == 12:
            acct = digits(14)
        bodies = [
            (f"Hi team,\nMy name is {name}. My October salary was not credited to account {acct} "
             f"(IFSC {ifsc}). Please check.\nPAN: {p}\nRegards,\n{f}", [name, f, last, acct, ifsc, p]),
            (f"Hello,\nEmployee {name2} cannot see the PF contribution. UAN {u}. Aadhaar "
             f"{a[:4]} {a[4:8]} {a[8:]}. Call me on +91 {ph[:5]} {ph[5:]}.\nThanks,\n{name}",
             [name2, f2, l2, u, a, ph, name, f, last]),
            (f"Payslip shows the wrong TDS for my PAN {p}. Contact {em} or {ph}.\n- {name}",
             [p, em, ph, name, f, last]),
        ]
        body, raw = bodies[i % 3]
        return ticket(i, "en", "IN", name, em, "+91" + ph, body, raw)
    f, last = rng.choice(AR_FIRST_LAT), rng.choice(AR_LAST_LAT)
    f2, l2 = rng.choice(AR_FIRST_LAT), rng.choice(AR_LAST_LAT)
    name, name2 = f"{f} {last}", f"{f2} {l2}"
    ib, eid, ph, em = iban_ae(), emirates_id(), phone_ae(), email(f, last)
    bodies = [
        (f"Dear Payce,\nI am {name}. My WPS salary transfer to IBAN {fmt_iban(ib)} failed. Emirates ID "
         f"{eid[:3]}-{eid[3:7]}-{eid[7:14]}-{eid[14]}. "
         f"Mobile +971 {ph[:2]} {ph[2:5]} {ph[5:]}.\nRegards,\n{name}",
         [name, f, ib, eid, ph]),
        (f"Hi, please update the bank details for staff member {name2}: IBAN {ib}. Reach me at {em}.\n"
         f"Thanks,\n{name}", [name2, f2, ib, em, name, f]),
        (f"Ms. {name2} has not received her end-of-service statement. Her Emirates ID is {eid}. "
         f"Please call 0{ph}.\nRegards,\n{f}", [name2, f2, eid, ph, f]),
    ]
    body, raw = bodies[i % 3]
    return ticket(i, "en", "AE", name, em, "+971" + ph, body, raw)


def hinglish(i):
    f, last = rng.choice(IN_FIRST), rng.choice(IN_LAST)
    f2, l2 = rng.choice(IN_FIRST), rng.choice(IN_LAST)
    name, name2 = f"{f} {last}", f"{f2} {l2}"
    a, u, ph, em, acct = aadhaar(), uan(), phone_in(), email(f, last), digits(13)
    bodies = [
        (f"Namaste, mera naam {name} hai. Meri salary abhi tak nahi aayi, account {acct} hai. "
         f"Mera number {ph} hai.\nShukriya,\n{f}", [name, f, last, acct, ph]),
        (f"Hi team, employee {name2} ka UAN {u} galat dikh raha hai. Aadhaar {a} hai. Please check karo.\n"
         f"Thanks,\n{name}", [name2, f2, l2, u, a, name, f, last]),
        (f"Bhai mera form 16 nahi mila. Mail karo {em} pe ya call karo +91-{ph[:5]}-{ph[5:]}.\n"
         f"Regards,\n{name}", [em, ph, name, f, last]),
    ]
    body, raw = bodies[i % 3]
    return ticket(i, "hi-Latn", "IN", name, em, "+91" + ph, body, raw)


def hindi(i):
    f, last = rng.choice(HI_FIRST), rng.choice(HI_LAST)
    f2, l2 = rng.choice(HI_FIRST), rng.choice(HI_LAST)
    name, name2 = f"{f} {last}", f"{f2} {l2}"
    a, p, ph, acct = aadhaar(), pan("S"), phone_in(), digits(12)
    em = email(rng.choice(IN_FIRST), rng.choice(IN_LAST))
    while len(acct) == 12:
        acct = digits(rng.choice([11, 13, 14]))
    bodies = [
        (f"नमस्ते,\nमेरा नाम {name} है। मेरा वेतन खाता {acct.translate(DEVA)} में जमा नहीं हुआ। "
         f"मेरा मोबाइल नंबर {ph.translate(DEVA)} है।\nधन्यवाद,\n{f}", [name, f, last, acct, ph]),
        (f"कर्मचारी {name2} का आधार {a[:4]} {a[4:8]} {a[8:]} और पैन {p} है। कृपया पीएफ ठीक करें। "
         f"ईमेल: {em}\nसादर,\n{name}", [name2, f2, l2, a, p, em, name, f, last]),
        (f"मुझे फॉर्म 16 नहीं मिला। आधार {a.translate(DEVA)}, फोन +91 {ph}।\nधन्यवाद,\n{name}",
         [a, ph, name, f, last]),
    ]
    body, raw = bodies[i % 3]
    return ticket(i, "hi", "IN", name, em, "+91" + ph, body, raw)


def arabic(i):
    f, last = rng.choice(AR_FIRST), rng.choice(AR_LAST)
    f2, l2 = rng.choice(AR_FIRST), rng.choice(AR_LAST)
    name, name2 = f"{f} {last}", f"{f2} {l2}"
    ib, eid, ph = iban_ae(), emirates_id(), phone_ae()
    em = email(rng.choice(AR_FIRST_LAT), rng.choice(AR_LAST_LAT))
    eid_fmt = f"{eid[:3]}-{eid[3:7]}-{eid[7:14]}-{eid[14]}"
    bodies = [
        (f"مرحبا،\nاسمي {name}. لم يصل راتبي إلى الحساب {ib}. رقم الهوية {eid_fmt.translate(ARAB)}. "
         f"هاتفي {('0' + ph).translate(ARAB)}.\nمع التحية\n{name}", [name, f, last, ib, eid, ph]),
        (f"الموظف {name2} لا يرى قسيمة الراتب. البريد {em}. رقم الجوال +971 {ph[:2]} {ph[2:5]} {ph[5:]}.\n"
         f"شكرا\n{name}", [name2, f2, l2, em, ph, name, f, last]),
        (f"السيدة {name2} تحتاج شهادة راتب. رقم الهوية {eid}، الآيبان {fmt_iban(ib)}.\nمع خالص التحيات\n{f}",
         [name2, f2, l2, eid, ib, f]),
    ]
    body, raw = bodies[i % 3]
    return ticket(i, "ar", "AE", name, em, "+971" + ph, body, raw)


MID_SENTENCE = [
    ("en", "Yesterday I spoke with {n2} about the bonus and {f2} said it would be fixed this week."),
    ("en", "Can you check why {n2}'s payslip still shows the old address?"),
    ("en", "{n2} joined in March, but the joining bonus is missing from the October run."),
    ("en", "Our manager {n2} approved the leave encashment, yet nothing was paid."),
    ("en", "The reimbursement for {n2} was rejected twice. {f2} has the original receipts."),
    ("en", "Please share the revised CTC letter with {n2} before Friday."),
    ("en", "We hired {n2} last month and the offer letter has the wrong designation."),
    ("en", "Both {n2} and I were charged professional tax twice in September."),
    ("hi-Latn", "Kal {n2} ne bola tha ki arrears is mahine aa jayenge, par abhi tak kuch nahi aaya."),
    ("hi-Latn", "Humare team mein {n2} ka bonus galat calculate hua hai, please dekh lo."),
    ("hi-Latn", "Maine {n2} ko mail kiya tha but koi reply nahi aaya, ab kya karun?"),
    ("hi-Latn", "Is baar {n2} aur mera dono ka PF deduct nahi hua."),
]


def mid_sentence_tickets() -> list[dict]:
    """12 tickets whose only names sit mid-sentence, with no 'my name is' or sign-off."""
    r = random.Random(7)
    out = []
    for n, (lang, template) in enumerate(MID_SENTENCE, start=1):
        f2, l2 = r.choice(IN_FIRST), r.choice(IN_LAST)
        sender = f"{r.choice(IN_FIRST)} {r.choice(IN_LAST)}"
        body = template.format(n2=f"{f2} {l2}", f2=f2)
        out.append({"id": f"NER-{n:03d}", "language": lang, "tenant_region": "IN", "sender_name": sender,
                    "sender_email": None, "sender_phone": None, "body": body,
                    "raw_values": sorted({f"{f2} {l2}", f2, l2})})
    return out


def main() -> None:
    tickets, n = [], 1
    for make in (english, hinglish, hindi, arabic):
        for k in range(15):
            t = make(k)
            t["id"] = f"SEED-{n:03d}"
            tickets.append(t)
            n += 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(tickets, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(tickets)} tickets to {OUT}")
    ner = mid_sentence_tickets()
    OUT_NER.write_text(json.dumps(ner, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(ner)} tickets to {OUT_NER}")


if __name__ == "__main__":
    main()
