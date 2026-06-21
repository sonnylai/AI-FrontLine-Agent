"""
Layer 4: Final NLI — Haiku verifies the synthesised answer entails all agent results.
Async, runs after streaming completes.
"""
import json
import anthropic
from langsmith import traceable
from src.config import get_settings

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


_SYSTEM = """Bạn là một chuyên gia kiểm tra tính nhất quán thông tin ngân hàng.
Trả lời CHÍNH XÁC bằng JSON, không giải thích thêm."""

_PROMPT = """Kiểm tra xem câu trả lời cuối cùng có nhất quán với các kết quả từ các agent không.

KẾT QUẢ AGENT:
{agent_summaries}

CÂU TRẢ LỜI CUỐI:
{final_answer}

Trả về JSON:
{{"consistent": true/false, "issues": "mô tả vấn đề nếu có hoặc null"}}"""


@traceable(name="NLI·Final", run_type="chain")
async def check(final_answer: str, agent_results: list[dict]) -> tuple[bool, str | None]:
    """
    LangSmith span covers the full Haiku call + verdict.
    Inputs recorded: final_answer preview, agent summaries.
    Outputs recorded: return value (consistent, issues).
    """
    if not agent_results or not final_answer:
        return True, None

    summaries = "\n".join(
        f"[{r['agent'].upper()} verified={r['verified']}]: {r['answer'][:300]}"
        for r in agent_results
    )

    try:
        resp = await get_client().messages.create(
            model=get_settings().anthropic_haiku_model,
            max_tokens=256,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": _PROMPT.format(
                    agent_summaries=summaries,
                    final_answer=final_answer[:1000],
                ),
            }],
        )
        raw = resp.content[0].text.strip()
        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        data       = json.loads(raw)
        consistent = data.get("consistent", True)
        issues     = data.get("issues")
        return consistent, issues if not consistent else None
    except Exception:
        return True, None   # fail open — don't block on NLI errors
