import os
import json
import logging
import concurrent.futures
from core.config_loader import ConfigLoader
from core.analysis.llms.claude_cli import call_claude as cli_call_claude, ClaudeCLIError

class AIThematicFilter:
    """
    AI Thematic Screener Filter (Phase 2 Funnel)
    Evaluates the top N stocks passed by the Quant Screener.
    Uses Claude to read recent news for each stock and apply a narrative premium (+pts)
    or a trap penalty (-pts) based on the context.
    """
    def __init__(self, config: dict = None):
        self.logger = logging.getLogger("AIThematicFilter")
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.model_name = self.config.get("model", "claude-sonnet-4-20250514")
        self.max_workers = self.config.get("max_workers", 5)

        loader = ConfigLoader()
        secrets = loader.load_config()
        api_key = secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))

        self.client = None
        self.client_ready = False
        self.use_cli = False
        if api_key:
            try:
                import anthropic
                if api_key.startswith("sk-ant-oat"):
                    self.client = anthropic.Anthropic(auth_token=api_key)
                else:
                    self.client = anthropic.Anthropic(api_key=api_key)
                self.client_ready = True
            except ImportError:
                self.logger.warning("anthropic not installed. CLI fallback 사용.")
                self.use_cli = True
        else:
            self.logger.warning("ANTHROPIC_API_KEY not found. CLI fallback 사용.")
            self.use_cli = True

    def filter_candidates(self, scored_stocks: list, top_n: int = 15) -> list:
        """
        Takes a list of dicts: [{"code": "...", "name": "...", "score": 85, ...}]
        Returns the list with modified scores if AI is enabled.
        """
        if not self.enabled or not scored_stocks:
            return scored_stocks
        if not self.client_ready and not self.use_cli:
            return scored_stocks

        # Only evaluate the top_n to save API costs & time
        scored_stocks = sorted(scored_stocks, key=lambda x: x.get("total_score", 0), reverse=True)
        to_evaluate = scored_stocks[:top_n]
        the_rest = scored_stocks[top_n:]

        self.logger.info(f"AI Thematic Filter: Evaluating top {len(to_evaluate)} stocks...")

        # Fetch bulk news first to avoid pinging scraper inside threads
        try:
            from core.news_scraper import NewsScraper
            ns = NewsScraper()
            all_news = ns.fetch_news() # Fetches main page recent news
        except Exception as e:
            self.logger.error(f"Failed to fetch news for filter: {e}")
            return scored_stocks

        # Evaluate concurrently
        evaluated_stocks = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._evaluate_single_stock, stock, all_news, ns): stock
                for stock in to_evaluate
            }
            for future in concurrent.futures.as_completed(futures):
                stock = futures[future]
                try:
                    updated_stock = future.result()
                    evaluated_stocks.append(updated_stock)
                except Exception as e:
                    self.logger.error(f"[{stock.get('name')}] AI Filter Error: {e}")
                    evaluated_stocks.append(stock) # keep original if failed

        # Re-sort combined list with new scores
        final_list = evaluated_stocks + the_rest
        final_list = sorted(final_list, key=lambda x: x.get("total_score", 0), reverse=True)
        return final_list

    def _evaluate_single_stock(self, stock: dict, all_news: list, scraper_instance) -> dict:
        name = stock.get("name")
        code = stock.get("code")
        base_score = stock.get("total_score", 0)

        # Filter news specific to this stock
        stock_news = scraper_instance.filter_news(all_news, [name, code])
        if not stock_news:
             self.logger.debug(f"[{name}] No specific news found. Skipping AI filter.")
             stock["ai_reasoning"] = "관련 뉴스 없음."
             return stock

        news_text = json.dumps(stock_news[:5], ensure_ascii=False)

        prompt = f"""당신은 주식 시장의 테마 및 모멘텀 분석 AI입니다.
종목: {name} ({code})
현재 퀀트 점수: {base_score}점

최근 주요 뉴스:
{news_text}

지시사항:
위 뉴스를 바탕으로 이 종목이 현재 시장의 강력한 주도 테마(예: AI, 반도체 수주, FDA 승인 등 진성 호재)에 속하는지,
아니면 단순 찌라시나 일회성 펌핑(가짜 호재, 덫)인지 판별하십시오.
그 여부에 따라 퀀트 점수에 더할 '가산점(premium)'을 결정하십시오.
- 진성 호재 / 강력한 주도 섹터: +10 ~ +30점
- 중립 / 알 수 없음: 0점
- 악재 섞임 / 찌라시성 폭등 의심 (Trap): -20 ~ -50점

오직 JSON 형식으로만 응답하십시오.
{{
    "premium": 15,
    "reasoning": "해당 뉴스는 단순 기대감이 아닌 실제 대규모 수주 공시를 포함하고 있어 진성 호재로 판단됨."
}}
"""
        text = ""
        if self.client_ready and self.client:
            try:
                response = self.client.messages.create(
                    model=self.model_name,
                    max_tokens=512,
                    temperature=0.1,
                    messages=[{"role": "user", "content": prompt}]
                )
                text = response.content[0].text.strip()
            except Exception as e:
                self.logger.warning(f"[{name}] API failed: {e}. Trying CLI...")
                text = ""

        if not text:
            try:
                text = cli_call_claude(prompt, timeout=60).strip()
            except ClaudeCLIError as e:
                self.logger.warning(f"[{name}] CLI also failed: {e}. Skipping.")
                stock["ai_reasoning"] = f"AI 분석 실패: {e}"
                return stock

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        result = json.loads(text)
        premium = int(result.get("premium", 0))

        # Clamp premium to safe bounds
        premium = max(-50, min(30, premium))

        stock["total_score"] = base_score + premium
        stock["ai_reasoning"] = result.get("reasoning", "")
        self.logger.info(f"[{name}] AI Thematic Filter applied: Premium={premium}, New Score={stock['total_score']}")

        return stock
