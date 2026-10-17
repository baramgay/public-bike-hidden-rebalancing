"""LLM 호출 공통부: Claude Code CLI(헤드리스)로 Anthropic Claude를 부른다.

- 기본: `claude -p`(사용자 Claude 구독 인증). MCP·도구 없이, 전용 시스템 프롬프트로 호출해 부가 문맥을 최소화
- ANTHROPIC_API_KEY가 있으면 anthropic SDK로 직접 호출(결선 재현용)
- 모든 요청·응답은 호출자가 원문 그대로 보존한다(감사용)
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}
_EMPTY_MCP = Path(tempfile.gettempdir()) / "empty_mcp_config.json"


def call(prompt: str, system: str, model: str = "haiku", timeout: int = 300) -> dict:
    """반환: {"text": 응답 문자열, "model": 실제 모델, "usage": {...}, "cost_usd": float}"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()
        r = client.messages.create(model=MODELS.get(model, model), max_tokens=8000, system=system,
                                   messages=[{"role": "user", "content": prompt}])
        return {"text": r.content[0].text, "model": r.model, "usage": r.usage.model_dump(), "cost_usd": None}
    _EMPTY_MCP.write_text('{"mcpServers":{}}', encoding="utf-8")
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--system-prompt", system,
           "--tools", "", "--strict-mcp-config", "--mcp-config", str(_EMPTY_MCP), "--no-session-persistence"]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI 실패({r.returncode}): {r.stderr[:500]}")
    d = json.loads(r.stdout)
    if d.get("is_error"):
        raise RuntimeError(f"claude CLI 오류: {d.get('result')}")
    used = list(d.get("modelUsage", {}).keys())
    return {"text": d["result"], "model": used[0] if used else model, "usage": d.get("usage", {}),
            "cost_usd": d.get("total_cost_usd")}


def parse_json_block(text: str):
    """응답에서 첫 JSON 배열/객체를 꺼낸다(코드펜스 허용)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1].rsplit("```", 1)[0]
    start = min([i for i in (t.find("["), t.find("{")) if i >= 0])
    return json.loads(t[start:])
