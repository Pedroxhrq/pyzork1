"""Significant-word rules for Zork I's original six-Z-character vocabulary."""


def dictionary_key(word: str) -> str:
    """Return the text that fits in a version-3 dictionary record.

    Lowercase letters cost one Z-character, punctuation/digits use an alphabet
    shift, and characters outside those alphabets use a four-character escape.
    A truncated final shift is equivalent to the dictionary's padding.
    """
    remaining = 6
    significant = []
    for char in word.lower():
        cost = 1 if 'a' <= char <= 'z' else 2 if char in '\n0123456789.,!?_#\'"/\\-:()' else 4
        if cost > remaining:
            break
        significant.append(char)
        remaining -= cost
    return ''.join(significant)
