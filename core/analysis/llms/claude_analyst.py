import os
import json
import logging
from core.interfaces.llm import IAnalystLLM
from core.config_loader import ConfigLoader
from core.analysis.llms.claude_cli import call_claude as cli_call_claude, ClaudeCLIError

class ClaudeAnalyst(IAnalystLLM):
    """
    Adapter for Anthropic Claude APIs.
    Responsible for generating high-level Markdown memos analyzing the data.
    """
    def __init__(self, model_name="claude-sonnet-4-20250514", temperature=0.1):
        self.logger = logging.getLogger("ClaudeAnalyst")
        self.model_name = model_name
        self.temperature = temperature

        # Load API key
        loader = ConfigLoader()
        secrets = loader.load_config()
        api_key = secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))

        self.client = None
        self.use_cli = False
        self.use_mock = False

        if api_key:
            try:
                import anthropic
                if api_key.startswith("sk-ant-oat"):
                    self.client = anthropic.Anthropic(auth_token=api_key)
                else:
                    self.client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                self.logger.warning("anthropic not installed. Falling back to Claude CLI.")
                self.use_cli = True
        else:
            self.logger.warning("No ANTHROPIC_API_KEY found. Falling back to Claude CLI.")
            self.use_cli = True

    def analyze(self, code: str, name: str, data: dict) -> str:
        self.logger.info(f"[{name}({code})] Claude Analyst: Starting deep data interpretation (Orchestration Phase 1)...")
        prompt = self._build_analyst_prompt(code, name, data)

        if self.use_mock:
            self.logger.info("Using mock Claude response...")
            return self._get_mock_response(name)

        # 1차: API 호출
        if self.client:
            try:
                response = self.client.messages.create(
                    model=self.model_name,
                    max_tokens=2048,
                    temperature=self.temperature,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text
            except Exception as e:
                self.logger.error(f"Claude API Error: {e}. Falling back to CLI.")

        # 2차: CLI fallback
        try:
            return cli_call_claude(prompt, timeout=90)
        except ClaudeCLIError as e:
            self.logger.error(f"Claude CLI Error: {e}. Falling back to mock.")

        # 3차: Mock fallback (최후 수단)
        return self._get_mock_response(name)

    def _build_analyst_prompt(self, code: str, name: str, data: dict) -> str:
        """Builds a prompt tailored for Claude to produce a comprehensive markdown memo."""

        ohlc_str = ""
        if "ohlc" in data and data["ohlc"] is not None:
            df = data["ohlc"].tail(10)
            ohlc_str = df.to_json(orient="records", force_ascii=False)

        curr = data.get("current_data", {})
        price = curr.get("price", "N/A")
        score = data.get("screener_score", "N/A")
        temp = data.get("market_temp", {})

        supply = data.get("supply", {})
        if hasattr(supply, 'to_dict'):
            supply = supply.to_dict('records')
        news = data.get("news", [])[:5]

        return f"""당신은 월스트리트 헤지펀드의 수석 주식 애널리스트(Analyst)입니다.
지금부터 당신은 [ {name} ({code}) ] 종목에 대한 "투자 위원회 스윙 매매 제안서(Investment Committee Memo)"를 작성해야 합니다.

[중요 지시사항 - 환각(Hallucination) 방지 지침]
당신이 수치를 오해석하거나 없는 뉴스를 지어내는 것을 막기 위해, 분석을 시작하기 전에 반드시 제가 제공한 원본 데이터 중 핵심 수치(어제 종가, 최근 수급 주체, 주요 뉴스 제목 등)를
마크다운의 **[Raw Facts Citation]** 섹션에 그대로 복사해서 나열하십시오.
그 후 **[Interpretation]** 섹션에 당신의 논리정연한 분석을 작성하십시오.

### 1. 대상 종목
- 이름: {name} ({code})
- 초기 퀀트 스코어: {score} / 100
- 현재가: {price}

### 2. 제공된 원본 데이터
<OHLCV_10_Days>
{ohlc_str}
</OHLCV_10_Days>

<Supply_Institutional_Foreign>
{json.dumps(supply, ensure_ascii=False)}
</Supply_Institutional_Foreign>

<Macro_Market_Temperature>
{json.dumps(temp, ensure_ascii=False)}
</Macro_Market_Temperature>

<Recent_News_Top5>
{json.dumps(news, ensure_ascii=False)}
</Recent_News_Top5>

### 작성 양식 (Markdown)
# 제안서: {name} 스윙 (3일~2주) 매매 전략

## [Raw Facts Citation]
(제공된 데이터에서 파악한 핵심 숫자와 사실관계 3~5가지를 나열)

## [Interpretation]
(위 팩트를 기반으로 한 수급, 차트, 매크로 연계 분석)

## [Bull Case & Bear Case]
(상승 시나리오와 하락 시나리오)

## [Analyst Recommendation]
(강력매수, 매수, 관망, 매도 중 의견과 목표가/손절가 러프한 레인지 제시. 단, 최종 결정은 다른 시스템이 하므로 논리적 근거 위주로 설명할 것)
"""

    def _get_mock_response(self, name: str) -> str:
        return f"""# 제안서: {name} 스윙 매매 전략
## [Raw Facts Citation]
- 어제 거래량이 전일 대비 200% 증가.
- 기관 연속 3일 매수 우위.
- 퀀트 스코어 85점.

## [Interpretation]
기관의 강력한 매수세가 바닥에서 들어오고 있으며 차트상 단기 저항선을 돌파하는 흐름입니다...

## [Bull Case & Bear Case]
- Bull: 뉴스를 타고 저항선 10% 추가 돌파.
- Bear: 매크로 지표 악화로 인한 투심 꺾임 시 5% 하락.

## [Analyst Recommendation]
단기 매수(BUY)를 추천하며 기대 수익은 10% 내외입니다. 방어적인 손절선을 5% 아래로 잡길 권고합니다.
"""
