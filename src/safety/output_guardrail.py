"""
Layer 3: Output Guardrail — async, rule-based, runs post-stream in parallel with Final NLI.
Checks the final synthesised answer for PII leakage, compliance keywords, security issues.
"""
import re

# PII that should never appear in an outbound response (always block, even in negation)
_PII_PATTERNS = [
    r"\b\d{9,12}\b",                                      # account / national ID numbers
    r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",         # card numbers
    r"(?i)(password|mật\s*khẩu|otp|pin)\s*[:=]\s*\S+",  # credential values
]

# Compliance: phrases that are prohibited UNLESS preceded by a negation within 40 chars.
# "không có lợi nhuận đảm bảo" is a correct compliance disclaimer — do not block it.
_COMPLIANCE_PATTERNS = [
    r"(?i)(guaranteed\s+return|lợi\s+nhuận\s+đảm\s+bảo|cam\s+kết\s+lãi)",
    r"(?i)(buy\s+now|mua\s+ngay|đầu\s+tư\s+ngay\s+đi)",
    r"(?i)(không\s+rủi\s+ro|risk[\s-]free|zero[\s-]risk)",
    r"(?i)(chắc\s+chắn\s+thắng|guaranteed\s+profit)",
]

_VN_NEGATIONS = ("không", "chưa", "chưa có", "không có", "không phải", "không được")

_COMPILED_PII        = [re.compile(p) for p in _PII_PATTERNS]
_COMPILED_COMPLIANCE = [re.compile(p) for p in _COMPLIANCE_PATTERNS]


def _preceded_by_negation(text: str, match: re.Match, window: int = 40) -> bool:
    """True if a Vietnamese negation word appears within `window` chars before the match."""
    before = text[max(0, match.start() - window): match.start()].lower()
    return any(neg in before for neg in _VN_NEGATIONS)


async def check(answer: str) -> tuple[bool, str | None]:
    """
    Returns (passed: bool, warning: str | None).
    passed=False means the answer contains a compliance or PII issue.
    """
    for pattern in _COMPILED_PII:
        if pattern.search(answer):
            return False, "Câu trả lời có thể chứa thông tin nhạy cảm — vui lòng kiểm tra trước khi chia sẻ."

    for pattern in _COMPILED_COMPLIANCE:
        match = pattern.search(answer)
        if match and not _preceded_by_negation(answer, match):
            return False, "Câu trả lời chứa từ ngữ không phù hợp với quy định tuân thủ ngân hàng."

    return True, None
