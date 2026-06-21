"""
Layer 3: Output Guardrail — async, rule-based, runs post-stream in parallel with Final NLI.
Checks the final synthesised answer for PII leakage, compliance keywords, security issues.
"""
import re

# PII that should never appear in an outbound response
_PII_PATTERNS = [
    r"\b\d{9,12}\b",                                      # account / national ID numbers
    r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",         # card numbers
    r"(?i)(password|mật\s*khẩu|otp|pin)\s*[:=]\s*\S+",  # credential values
]

# Compliance: phrases a bank rep's AI assistant must never output
_COMPLIANCE_PATTERNS = [
    r"(?i)(guaranteed\s+return|lợi\s+nhuận\s+đảm\s+bảo|cam\s+kết\s+lãi)",   # guaranteed returns (MAS/SBV prohibited)
    r"(?i)(buy\s+now|mua\s+ngay|đầu\s+tư\s+ngay\s+đi)",                       # high-pressure sales
    r"(?i)(không\s+rủi\s+ro|risk[\s-]free|zero[\s-]risk)",                    # false risk claims
    r"(?i)(chắc\s+chắn\s+thắng|guaranteed\s+profit)",
]

_COMPILED_PII        = [re.compile(p) for p in _PII_PATTERNS]
_COMPILED_COMPLIANCE = [re.compile(p) for p in _COMPLIANCE_PATTERNS]


async def check(answer: str) -> tuple[bool, str | None]:
    """
    Returns (passed: bool, warning: str | None).
    passed=False means the answer contains a compliance or PII issue.
    Runs async for consistency with the aggregator's gather() call,
    but the actual check is synchronous (regex, ~0ms).
    """
    for pattern in _COMPILED_PII:
        if pattern.search(answer):
            return False, "Câu trả lời có thể chứa thông tin nhạy cảm — vui lòng kiểm tra trước khi chia sẻ."

    for pattern in _COMPILED_COMPLIANCE:
        if pattern.search(answer):
            return False, "Câu trả lời chứa từ ngữ không phù hợp với quy định tuân thủ ngân hàng."

    return True, None
