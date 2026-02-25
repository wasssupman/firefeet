import os
import yaml
from core.analysis.macro import MacroAnalyzer
from core.econ_calendar import EconCalendar
from core.analysis.supply import SupplyAnalyzer
from core.reddit_analyzer import RedditAnalyzer
from core.news_analyzer import NewsAnalyzer

class StockAgent:
    def __init__(self, auth, config_loader, agent_settings_path="config/agent_settings.yaml"):
        self.auth = auth
        self.config_loader = config_loader
        self.settings = self._load_settings(agent_settings_path)

        # Initialize Analyzers
        self.macro = MacroAnalyzer()
        self.econ = EconCalendar()
        self.supply = SupplyAnalyzer(auth)

        # Reddit may fail if API keys are missing
        secrets = config_loader.load_config()
        reddit_cfg = secrets.get("REDDIT", {})
        self.reddit = RedditAnalyzer(
            client_id=reddit_cfg.get("CLIENT_ID"),
            client_secret=reddit_cfg.get("CLIENT_SECRET")
        )

        self.news = NewsAnalyzer()

        # Claude Client (lazy import + CLI fallback)
        api_key = secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or None
        self.client = None
        self.use_cli = False

        if api_key:
            try:
                import anthropic
                if api_key.startswith("sk-ant-oat"):
                    self.client = anthropic.Anthropic(auth_token=api_key)
                else:
                    self.client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                print("[StockAgent] anthropic 패키지 미설치. Claude CLI fallback 사용.")
                self.use_cli = True
        else:
            print("[StockAgent] ANTHROPIC_API_KEY 미설정. Claude CLI fallback 사용.")
            self.use_cli = True

    def _load_settings(self, path):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {"weights": {"macro": 0.2, "econ": 0.2, "supply": 0.4, "news": 0.2}}

    def collect_data(self, stock_code):
        """각 분석도구로부터 데이터를 수집합니다."""
        data = {}
        weights = self.settings.get("weights", {})

        # 1. Macro (Global)
        data['macro'] = self.macro.generate_report_section()

        # 2. Econ (Calendar)
        events = self.econ.fetch_all()
        data['econ'] = events[:10]

        # 3. Supply (Stock Specific)
        data['supply'] = self.supply.analyze_supply(stock_code)

        # 4. Social/News
        if self.reddit.available:
            data['reddit'] = self.reddit.get_market_sentiment()
        else:
            data['reddit'] = "API Key missing. Falling back to Global News."

        data['news'] = self.news.fetch_global_news(limit=5)

        return data, weights

    def analyze(self, stock_code, stock_name=""):
        """Claude를 이용해 종합 분석을 수행합니다."""
        data, weights = self.collect_data(stock_code)

        prompt = f"""
당신은 전문 주식 분석 에이전트 'Firefeet AI'입니다.
제공된 데이터와 가중치를 바탕으로 {stock_name}({stock_code})에 대한 종합 투자 분석 리포트를 작성하세요.

### 분석 데이터 및 가중치 (Weights)
1. **거시 경제 (Weight: {weights.get('macro')})**: {data['macro']}
2. **경제 지표/일정 (Weight: {weights.get('econ')})**: {data['econ']}
3. **수급 상황 (Weight: {weights.get('supply')})**: {data['supply']}
4. **해외 커뮤니티 (Weight: {weights.get('reddit')})**: {data['reddit']}
5. **글로벌 뉴스 (Weight: {weights.get('news')})**: {data['news']}

### 작성 가이드라인:
- 제공된 가중치가 높은 항목에 더 큰 비중을 두어 분석하세요.
- 전문적이고 객관적인 어조를 유지하세요.
- 최종 의견은 [적극 매수 / 매수 / 관망 / 매도 / 적극 매도] 중 하나를 선택하고 그 이유를 요약하세요.
- 한국어로 작성하세요.
- 리포트는 Markdown 형식을 사용하세요.

### 리포트 구성:
## {stock_name} ({stock_code}) 종합 분석 리포트
1. **요약 및 최종 의견** (가장 먼저 제시)
2. **부문별 상세 분석** (가중치 순서대로)
3. **향후 리스크 및 기회 요인**
"""

        # 1차: API 호출
        if self.client:
            try:
                message = self.client.messages.create(
                    model=self.settings.get("claude_model", "claude-3-5-sonnet-20240620"),
                    max_tokens=self.settings.get("max_tokens", 2000),
                    temperature=self.settings.get("temperature", 0.2),
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                return message.content[0].text
            except Exception as e:
                print(f"[StockAgent] API 호출 실패: {e}. CLI fallback 시도...")

        # 2차: CLI fallback
        try:
            from core.analysis.llms.claude_cli import call_claude
            return call_claude(prompt, timeout=120)
        except Exception as cli_err:
            return f"에이전트 분석 중 오류가 발생했습니다: API와 CLI 모두 실패. (CLI: {cli_err})"


if __name__ == "__main__":
    # Test/Example Usage
    from core.config_loader import ConfigLoader
    from core.kis_auth import KISAuth

    loader = ConfigLoader()
    try:
        config = loader.get_kis_config(mode='PAPER')
        auth = KISAuth(config)
        agent = StockAgent(auth, loader)
        print(agent.analyze("005930", "삼성전자"))
    except Exception as e:
        print(f"StockAgent Test Failed: {e}")
