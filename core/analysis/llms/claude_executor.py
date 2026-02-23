import os
import json
import logging
from core.interfaces.llm import IExecutorLLM
from core.config_loader import ConfigLoader

class ClaudeExecutor(IExecutorLLM):
    """
    Adapter for Anthropic Claude APIs.
    Responsible for acting as the strict Chief Risk Officer (CRO), parsing the Analyst Memo,
    cross-checking hard facts, and generating a strictly typed JSON decision.
    """
    def __init__(self, model_name="claude-3-5-sonnet-20241022", temperature=0.0):
        self.logger = logging.getLogger("ClaudeExecutor")
        self.model_name = model_name
        self.temperature = temperature # 0.0 for strict decision making
        
        loader = ConfigLoader()
        secrets = loader.load_config()
        api_key = secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
        
        self.client = None
        self.use_cli = False
        
        if api_key:
            import anthropic
            if api_key.startswith("sk-ant-oat"):
                self.client = anthropic.Anthropic(auth_token=api_key)
            else:
                self.client = anthropic.Anthropic(api_key=api_key)
        else:
            self.logger.warning("No ANTHROPIC_API_KEY found. Falling back to Claude CLI.")
            self.use_cli = True

    def execute_decision(self, code: str, name: str, memo: str, facts: dict) -> dict:
        self.logger.info(f"[{name}({code})] Claude Executor: Starting Cross-Check & JSON Parsing (Orchestration Phase 2)...")
        prompt = self._build_executor_prompt(code, name, memo, facts)
        
        response_text = self._call_claude(prompt)
        if isinstance(response_text, dict):
            return response_text
        return self._parse_json(response_text)

    def _build_executor_prompt(self, code: str, name: str, memo: str, facts: dict) -> str:
        
        curr_price = facts.get("current_price", 0)
        score = facts.get("score", 0)
        
        prompt = f"""당신은 최고 리스크 관리자(Chief Risk Officer)이자 최종 매매 집행기(Trade Executor)입니다.
아래는 수석 애널리스트가 보낸 타겟 종목 [ {name} ({code}) ]에 대한 상세 분석 마크다운 리포트(Investment Committee Memo)입니다.

### 1. Analyst Report (Memo)
<MEMO>
{memo}
</MEMO>

### 2. Hard Facts (절대 불변 사실)
애널리스트의 계산 실수나 환각(Hallucination)을 막기 위해 아래의 하드 팩트를 제공합니다. 모든 판단은 이 수치를 우선해야 합니다.
- **현재가**: {curr_price}
- **퀀트 스코어**: {score}

### 지시사항
1. 위 메모의 내용을 바탕으로 최종 스윙 매매 판단을 내리십시오.
2. 단, 애널리스트가 제시한 `target_price`(목표가)나 `stop_loss`(손절가)가 '현재가' 대비 비상식적이라면(수학오류, 오표기 등), 당신의 자체 권한으로 매매를 기각(`WAIT` 또는 `HOLD`)하고 그 이유를 적으십시오. 목표가는 보통 현재가의 1.05~1.3배, 손절가는 0.95~0.9배 사이여야 현실적입니다.
3. 당신의 출력은 **반드시 100% 순수한 JSON 형식이어야만 합니다.** 그 어떤 마크다운 코드블록(` ```json `)이나 추가 설명도 붙여서는 안 됩니다.

### 출력 JSON 스키마
{{
    "decision": "BUY", // BUY, HOLD, WAIT, SELL 중 택 1
    "confidence": 85, // 0에서 100 사이의 정수 (확신도)
    "strategy_type": "BREAKOUT", // BREAKOUT, PULLBACK, MEAN_REVERSION, TREND_FOLLOWING 중 택 1
    "target_price": 55000, // 익절 목표가 (현재가 대비 타당한 정수)
    "stop_loss": 48000, // 손절가 (정수)
    "reasoning": "애널리스트의 리포트를 검토한 결과 차트 추세가 유리하며, 제안된 목표가격(55000원)이 현재가(50000원) 대비 적절한 10% 업사이드로 검증되었으므로 승인함." // 검증 로직 요약
}}
"""
        return prompt

    def _call_claude(self, prompt: str) -> str:
        """Call Claude implementation (CLI or API)"""
        if self.use_cli:
            import subprocess
            try:
                env = os.environ.copy()
                env.pop("CLAUDECODE", None)
                result = subprocess.run(
                    ["claude", "-p", prompt],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env
                )
                if result.returncode == 0:
                    return result.stdout.strip()
                else:
                    self.logger.error(f"Claude CLI Error: {result.stderr}")
                    return self._fallback_json()
            except FileNotFoundError:
                self.logger.error("Claude CLI tool not found.")
                return self._fallback_json()
            except subprocess.TimeoutExpired:
                self.logger.error("Claude CLI timed out.")
                return self._fallback_json()
        
        elif self.client:
            try:
                response = self.client.messages.create(
                    model=self.model_name,
                    max_tokens=1024,
                    temperature=self.temperature,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                return response.content[0].text
            except Exception as e:
                self.logger.error(f"Claude API Error: {e}")
                return self._fallback_json()
        
        return self._fallback_json()

    def _parse_json(self, text: str) -> dict:
        """Extracts JSON from text, strips markdown if accidentally present."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            self.logger.error(f"Executor failed to output valid JSON: {text}. Error: {e}")
            return self._fallback_json()

    def _fallback_json(self):
        """Ultimate safe fallback if execution crashes to prevent system halt."""
        return {
            "decision": "HOLD",
            "confidence": 0,
            "strategy_type": "WAITING",
            "target_price": 0,
            "stop_loss": 0,
            "reasoning": "Fallback triggered due to Executor LLM parsing or connection failure."
        }
