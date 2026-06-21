"""
Layer 2: Per-agent NLI — checks that an agent answer is grounded in its sources.
Uses lightweight heuristics (zero token cost, ~1ms).
Production upgrade path: swap _heuristic_check for mDeBERTa-v3-base-mnli-xnli
when PyTorch >= 2.4 is available.
"""
import re


def _key_terms(text: str) -> set[str]:
    """Extract meaningful tokens (ignore stopwords and punctuation)."""
    stopwords = {
        "và", "của", "trong", "là", "có", "không", "với", "được", "cho",
        "này", "đó", "một", "các", "những", "tại", "từ", "để", "theo",
        "the", "is", "in", "of", "to", "and", "a", "an", "that",
    }
    tokens = re.findall(r"[a-zA-ZÀ-ỹ0-9]{2,}", text.lower())
    return {t for t in tokens if t not in stopwords}


def _heuristic_check(answer: str, context_chunks: list[str]) -> tuple[bool, str | None]:
    """
    Lightweight faithfulness check:
    1. Key numerical facts in the answer must appear in at least one chunk.
    2. Overall term overlap between answer and all chunks must be > 20%.
    """
    if not context_chunks:
        return False, "Không có nguồn dữ liệu để xác minh câu trả lời."

    full_context = " ".join(context_chunks)
    context_terms = _key_terms(full_context)
    answer_terms  = _key_terms(answer)

    if not answer_terms:
        return True, None   # trivially grounded (empty answer)

    overlap = len(answer_terms & context_terms) / len(answer_terms)
    if overlap < 0.20:
        return False, f"Câu trả lời chứa thông tin không có trong nguồn dữ liệu (overlap={overlap:.0%})."

    # Check specific numbers in answer appear somewhere in context
    answer_numbers = set(re.findall(r"\d[\d.,]+", answer))
    for num in answer_numbers:
        # Allow slight formatting variation (12.000.000 vs 12,000,000)
        normalised = re.sub(r"[.,]", "", num)
        found = any(
            re.sub(r"[.,]", "", n) == normalised
            for n in re.findall(r"\d[\d.,]+", full_context)
        )
        if not found and len(num) > 3:      # ignore small numbers like "10", "3"
            return False, f"Số liệu '{num}' trong câu trả lời không có trong nguồn dữ liệu."

    return True, None


def check(answer: str, context_chunks: list[str]) -> tuple[bool, str | None]:
    """
    Public interface.
    Returns (verified: bool, warning: str | None).
    """
    return _heuristic_check(answer, context_chunks)
