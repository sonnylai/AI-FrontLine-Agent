"""
Layer 1: Input Guardrail — sync, rule-based, zero latency.
Blocks PII leakage requests, prompt injection, and clearly off-topic queries.
"""
import re

_PII_PATTERNS = [
    r"\b\d{9,12}\b",                        # national ID / account numbers
    r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",  # card numbers
    r"(?i)(password|mật\s*khẩu|otp|pin)\s*[:=\s]\s*\d+",
    r"(?i)(sql\s*inject|'\s*;\s*(drop|delete|truncate|insert|update)\s+|--\s*$|;\s*drop\s+table)",  # SQL injection
    r"(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|prior|above)\s+instruct",  # prompt injection
    r"(?i)(system\s*prompt|jailbreak|bypass\s+(safety|filter|guardrail))",
]

_OFF_TOPIC_PATTERNS = [
    r"(?i)(crypto|bitcoin|ethereum|nft|stock\s+tip|lottery|casino|cờ\s*bạc)",
    r"(?i)(hack|crack|exploit|phishing|malware|virus)",
    r"(?i)(sex|nude|porn|vũ\s*khí|ma\s*túy)",
]

_COMPILED_PII      = [re.compile(p) for p in _PII_PATTERNS]
_COMPILED_OFF_TOPIC = [re.compile(p) for p in _OFF_TOPIC_PATTERNS]


def check(message: str) -> tuple[bool, str | None]:
    """
    Returns (blocked: bool, reason: str | None).
    blocked=True means the pipeline should stop.
    """
    for pattern in _COMPILED_PII:
        if pattern.search(message):
            return True, "Câu hỏi chứa thông tin nhạy cảm hoặc có dấu hiệu tấn công hệ thống."

    for pattern in _COMPILED_OFF_TOPIC:
        if pattern.search(message):
            return True, "Câu hỏi nằm ngoài phạm vi hỗ trợ của trợ lý ngân hàng."

    if len(message.strip()) < 5:
        return True, "Câu hỏi quá ngắn, vui lòng nhập đầy đủ."

    if len(message) > 2000:
        return True, "Câu hỏi quá dài, vui lòng rút gọn."

    return False, None
