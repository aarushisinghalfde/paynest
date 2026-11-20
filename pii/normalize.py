"""Digit normaliser: Arabic-Indic, Eastern Arabic-Indic and Devanagari digits -> 0-9.

Each native digit is one character and maps to one ASCII digit, so positions in the
normalised text match the original exactly; matches found on the normalised text can be
masked in the original.
"""
_DIGITS = {}
for _base in (0x0660, 0x06F0, 0x0966):  # Arabic-Indic, Eastern Arabic-Indic (Persian/Urdu), Devanagari
    for _i in range(10):
        _DIGITS[_base + _i] = ord("0") + _i

_TABLE = dict(_DIGITS)


def normalize_digits(text: str) -> str:
    """Return text with every native digit replaced by its ASCII digit (same length)."""
    return text.translate(_TABLE)
