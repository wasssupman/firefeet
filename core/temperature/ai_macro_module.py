import os
import json
import logging
from core.config_loader import ConfigLoader
from core.news_analyzer import NewsAnalyzer

class AIMacroModule:
    """
    AI Macro Sentinel Module.
    Reads top financial headlines and evaluates if there is a severe macro narrative
    (Black Swan, panic) that quant math hasn't priced in.
    Returns a multiplier (e.g., 1.0 = normal, 0.0 = freezing/panic).
    """
    def __init__(self, config: dict = None):
        self.logger = logging.getLogger("AIMacroModule")
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.model_name = self.config.get("model", "claude-sonnet-4-20250514")

        loader = ConfigLoader()
        secrets = loader.load_config()
        api_key = secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))

        self.client = None
        self.client_ready = False
        if api_key:
            try:
                import anthropic
                if api_key.startswith("sk-ant-oat"):
                    self.client = anthropic.Anthropic(auth_token=api_key)
                else:
                    self.client = anthropic.Anthropic(api_key=api_key)
                self.client_ready = True
            except ImportError:
                self.logger.warning("anthropic not installed.")
        else:
            self.logger.warning("ANTHROPIC_API_KEY not found.")

        self.news_analyzer = NewsAnalyzer()

    def evaluate_override(self, current_quant_score: float) -> dict:
        """
        Args:
            current_quant_score (float): The base score calculated by quant modules (-100 to 100).
        Returns:
            dict: {
                "multiplier": float, # 1.0 (agree/neutral), 0.5 (caution), -1.0 (reverse/panic), etc.
                "reasoning": str
            }
        """
        if not self.enabled or not self.client_ready:
            return {"multiplier": 1.0, "reasoning": "AI Macro disabled or API key missing."}

        self.logger.info("AI Macro Sentinel: Fetching top breaking news...")
        headlines = self.news_analyzer.fetch_global_news_titles(limit=15)

        if not headlines:
            self.logger.warning("AI Macro Sentinel: Failed to fetch news. Proceeding without override.")
            return {"multiplier": 1.0, "reasoning": "No news data available."}

        prompt = f"""당신은 글로벌 매크로 헤지펀드의 최고 리스크 관리자(CRO)입니다.
현재 퀀트 알고리즘이 계산한 시장 온도 점수는 {current_quant_score}점 (-100 ~ +100) 입니다.

아래는 방금 스크랩된 글로벌 주요 금융 헤드라인 15개입니다:
{json.dumps(headlines, ensure_ascii=False, indent=2)}

지시사항:
위 뉴스를 기반으로 시장에 '기존 퀀트 점수가 미처 반영하지 못한 거대한 패닉/블랙스완' 또는 '초강력 랠리 모멘텀'이 있는지 평가하십시오.
당신의 임무는 퀀트 점수에 곱할 'multiplier(승수)'를 결정하는 것입니다.
- 1.0: 뉴스가 현재 퀀트 점수와 부합하거나 특이사항 없음 (정상)
- 0.5: 리스크가 감지되어 보수적 접근 필요 (점수 반토막)
- 0.0 또는 음수: 즉각적인 패닉/블랙스완 발생. 모든 매수 중단 필요 (FREEZING).

오직 JSON 형식으로만 응답하십시오.
{{
    "multiplier": 1.0,
    "reasoning": "주요 뉴스에서 특별한 시스템적 리스크가 발견되지 않으며, 연준 발언도 예상에 부합함."
}}
"""
        try:
            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=512,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)

            # Sanity check on multiplier
            multiplier = float(result.get("multiplier", 1.0))
            if multiplier < -1.0 or multiplier > 2.0:
                multiplier = 1.0

            return {
                "multiplier": multiplier,
                "reasoning": result.get("reasoning", "")
            }
        except Exception as e:
            self.logger.error(f"AIMacro Sentinel failed: {e}")
            return {"multiplier": 1.0, "reasoning": f"AI Error: {e}"}
