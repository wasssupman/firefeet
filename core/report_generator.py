import pandas as pd
from datetime import datetime
import time


class ReportGenerator:
    """
    관심 종목 심층 분석 리포트를 생성합니다.
    - 현재가/등락률
    - 변동성 돌파 신호
    - 수급 동향
    - 종합 의견 (BUY / HOLD / WAIT)
    """

    def __init__(self, strategy, supply_analyzer=None, macro_analyzer=None, econ_calendar=None):
        self.strategy = strategy
        self.supply_analyzer = supply_analyzer
        self.macro_analyzer = macro_analyzer
        self.econ_calendar = econ_calendar

    def generate_stock_report(self, code, name="", data_provider_fn=None):
        """단일 종목 분석 리포트"""
        label = f"{name} ({code})" if name else code

        if not data_provider_fn:
            return f"**{label}**: 데이터 제공자 함수 누락"

        # 1. Fetch Data
        try:
            ohlc, investor_trend, current_data = data_provider_fn(code)
            current_price = current_data['price']
            change_rate = current_data['change_rate']
        except Exception as e:
            return f"**{label}**: 데이터 조회 실패 ({e})"

        # 2. 변동성 돌파 목표가
        target_price = "N/A"
        breakout = False
        try:
            if ohlc is not None:
                target_info = self.strategy.get_target_price(code, ohlc)
                if target_info:
                    target_price = target_info['target_price']
                    breakout = current_price >= target_price
        except Exception:
            pass

        # 3. 수급
        sentiment = "N/A"
        foreign_3d = 0
        inst_3d = 0
        try:
            if investor_trend is not None and self.supply_analyzer:
                supply = self.supply_analyzer.analyze_supply(investor_trend)
                if isinstance(supply, dict):
                    sentiment = supply['sentiment']
                    foreign_3d = supply.get('foreign_3d', 0)
                    inst_3d = supply.get('institution_3d', 0)
        except Exception:
            pass

        # 4. 종합 의견
        opinion = self._judge(breakout, sentiment, change_rate)

        # 5. 포맷
        lines = [
            f"### {label}",
            f"- **현재가**: {current_price:,} KRW ({change_rate:+.2f}%)",
            f"- **목표가 (돌파)**: {target_price:,} KRW {'🚨 **BREAKOUT**' if breakout else ''}",
            f"- **수급**: {sentiment} (외국인 3일: {foreign_3d:+,} / 기관 3일: {inst_3d:+,})",
            f"- **종합 의견**: {opinion}",
        ]
        return "\n".join(lines)

    def _judge(self, breakout, sentiment, change_rate):
        """기술/수급/가격 종합 판정"""
        score = 0
        if breakout:
            score += 2
        if sentiment in ("Strong Buy",):
            score += 2
        elif sentiment in ("Moderate Buy",):
            score += 1
        if change_rate > 2:
            score += 1
        elif change_rate < -2:
            score -= 1

        if score >= 3:
            return "🟢 **BUY** — 적극 매수 시그널"
        elif score >= 1:
            return "🔵 **HOLD** — 보유/관망"
        else:
            return "⚪ **WAIT** — 진입 대기"

    def generate_full_report(self, watchlist, data_provider_fn, include_macro=True):
        """
        전체 리포트 생성: 매크로 + 종목별 분석
        watchlist: [{"code": "005930", "name": "삼성전자"}, ...]
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        sections = [f"# 📝 Firefeet 정기 리포트\n> {now}\n"]

        # 매크로 섹션
        if include_macro and self.macro_analyzer:
            try:
                macro_section = self.macro_analyzer.generate_report_section()
                sections.append(macro_section)
            except Exception as e:
                sections.append(f"### 🌍 글로벌 지표\n> 조회 실패: {e}\n")

        # 경제 캘린더 섹션
        if self.econ_calendar:
            try:
                econ_section = self.econ_calendar.generate_report_section()
                sections.append(econ_section)
            except Exception as e:
                sections.append(f"### 📅 경제 지표\n> 조회 실패: {e}\n")

        # 종목 섹션
        sections.append("---\n## 📊 관심 종목 분석\n")
        for stock in watchlist:
            report = self.generate_stock_report(stock['code'], stock.get('name', ''), data_provider_fn)
            sections.append(report)
            time.sleep(0.5)  # API Rate Limit

        return "\n\n".join(sections)
