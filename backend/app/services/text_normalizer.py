"""Text normalization shared by transcription, summaries, and exports."""

from functools import lru_cache
import re


# Whisper occasionally emits 幺 (U+5E7A) for the grammatical particle 么
# (U+4E48).  Correct only unambiguous interrogative/adverbial compounds so
# genuine words such as 幺鸡 and 幺妹 remain unchanged.
_ASR_HOMOPHONE_REPAIRS = (
    (re.compile(r"怎幺"), "怎么"),
    (re.compile(r"什幺"), "什么"),
    (re.compile(r"这幺"), "这么"),
    (re.compile(r"那幺"), "那么"),
    (re.compile(r"多幺"), "多么"),
)


@lru_cache
def _traditional_to_simplified_converter():
    from opencc import OpenCC

    # ASR frequently emits Taiwan-style traditional Chinese.  ``tw2sp`` also
    # applies phrase-level conversions (for example, 「寫著」→「写着」), unlike
    # the character-only ``t2s`` profile.
    return OpenCC("tw2sp")


def is_chinese_language(language: str | None) -> bool:
    value = (language or "").strip().lower()
    return value == "zh" or value.startswith("zh-") or value in {"chinese", "中文", "简体中文", "繁体中文"}


def normalize_simplified_chinese(text: str, language: str | None) -> str:
    """Convert Chinese text to simplified Chinese without affecting other languages."""
    if not text or not is_chinese_language(language):
        return text
    normalized = _traditional_to_simplified_converter().convert(text)
    for pattern, replacement in _ASR_HOMOPHONE_REPAIRS:
        normalized = pattern.sub(replacement, normalized)
    return normalized
