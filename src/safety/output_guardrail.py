"""
Layer 3: Output Guardrail — async, rule-based, runs post-stream in parallel with Final NLI.
Checks the final synthesised answer for PII leakage, compliance keywords, security issues.
"""
import re
from langsmith import traceable

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

_PII_LABELS        = ["pii:account_id", "pii:card_number", "pii:credential"]
_COMPLIANCE_LABELS = [
    "compliance:guaranteed_return",
    "compliance:buy_now",
    "compliance:no_risk",
    "compliance:guaranteed_profit",
]


def _preceded_by_negation(text: str, match: re.Match, window: int = 40) -> bool:
    """True if a Vietnamese negation word appears within `window` chars before the match."""
    before = text[max(0, match.start() - window): match.start()].lower()
    return any(neg in before for neg in _VN_NEGATIONS)


@traceable(name="NLI·OutputGuardrail", run_type="chain")
def _log_guardrail(answer_chars: int, passed: bool, triggered_rule: str | None, warning: str | None) -> dict:
    """LangSmith span — records which rule fired (if any)."""
    return {
        "answer_chars":   answer_chars,
        "passed":         passed,
        "triggered_rule": triggered_rule,
        "warning":        warning,
    }


async def check(answer: str) -> tuple[bool, str | None]:
    """
    Returns (passed: bool, warning: str | None).
    passed=False means the answer contains a compliance or PII issue.
    """
    triggered_rule: str | None = None

    for i, pattern in enumerate(_COMPILED_PII):
        if pattern.search(answer):
            warning = "Câu trả lời có thể chứa thông tin nhạy cảm — vui lòng kiểm tra trước khi chia sẻ."
            triggered_rule = _PII_LABELS[i]
            _log_guardrail(len(answer), False, triggered_rule, warning)
            return False, warning

    for i, pattern in enumerate(_COMPILED_COMPLIANCE):
        match = pattern.search(answer)
        if match and not _preceded_by_negation(answer, match):
            warning = "Câu trả lời chứa từ ngữ không phù hợp với quy định tuân thủ ngân hàng."
            triggered_rule = _COMPLIANCE_LABELS[i]
            _log_guardrail(len(answer), False, triggered_rule, warning)
            return False, warning

    _log_guardrail(len(answer), True, None, None)
    return True, None
