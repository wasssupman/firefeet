import os
import subprocess
import tempfile
import yaml
import json
import numpy as np
from datetime import datetime, timezone, timedelta

from core.config_loader import ConfigLoader

KST = timezone(timedelta(hours=9))


class _NumpyEncoder(json.JSONEncoder):
    """numpy 타입을 JSON 직렬화 가능하게 변환"""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _dumps(obj) -> str:
    """numpy 호환 JSON 직렬화"""
    return json.dumps(obj, ensure_ascii=False, indent=2, cls=_NumpyEncoder)


class DeepAgent:
    """섹션별 Claude 딥 분석 에이전트"""

    SECTIONS = [
        "company_overview",
        "financial_analysis",
        "valuation",
        "industry_competition",
        "supply_technical",
        "news_disclosure",
        "consensus",
        "investment_thesis",
    ]

    SECTION_NAMES = {
        "company_overview": "기업 개요",
        "financial_analysis": "재무 분석",
        "valuation": "밸류에이션",
        "industry_competition": "산업 및 경쟁 분석",
        "supply_technical": "수급 및 기술적 분석",
        "news_disclosure": "뉴스 및 공시",
        "consensus": "증권사 컨센서스",
        "investment_thesis": "AI 종합 투자 의견",
    }

    def __init__(self, config_path="config/deep_analysis.yaml"):
        self.config = self._load_config(config_path)
        self.model = self.config.get("model", "claude-sonnet-4-6")
        self.max_tokens = self.config.get("max_tokens_per_section", 2048)
        self.max_tokens_synthesis = self.config.get("max_tokens_synthesis", 4096)
        self.temperature = self.config.get("temperature", 0.2)
        self.synthesis_temperature = self.config.get("synthesis_temperature", 0.3)

        # Anthropic 클라이언트
        self.client = None
        self.use_cli = False
        loader = ConfigLoader()
        secrets = loader.load_config()
        api_key = secrets.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if api_key:
            import anthropic
            # OAuth 토큰(sk-ant-oat)이면 auth_token으로, 일반 키면 api_key로
            if api_key.startswith("sk-ant-oat"):
                self.client = anthropic.Anthropic(auth_token=api_key)
            else:
                self.client = anthropic.Anthropic(api_key=api_key)
        else:
            print("[DeepAgent] API 키 없음 — claude CLI 모드로 전환")
            self.use_cli = True

        # 데이터 수집기 초기화 (lazy)
        self._collectors = {}

    def _load_config(self, path):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def analyze(self, code: str, name: str, sections_filter: list = None, data_provider_fn=None) -> dict:
        """전체 딥 분석 실행

        Args:
            code: 종목코드 (예: "005930")
            name: 종목명 (예: "삼성전자")
            sections_filter: 특정 섹션만 분석 (None이면 전체)
            data_provider_fn: 콜백 함수, code 파라미터 반환

        Returns: {"company_overview": "...", "financial_analysis": "...", ...}
        """
        print(f"\n[DeepAgent] {name}({code}) 딥 리서치 시작")

        # 1. 데이터 수집
        data = self._collect_all_data(code, name, data_provider_fn)

        # 2. 활성 섹션 결정
        cfg_sections = self.config.get("sections", {})
        active_sections = [
            s for s in self.SECTIONS
            if cfg_sections.get(s, True)
            and (sections_filter is None or s in sections_filter)
        ]

        # 3. 섹션별 분석 (마지막 investment_thesis 제외)
        sections = {}
        analysis_sections = [s for s in active_sections if s != "investment_thesis"]

        cli_auth_failed = False
        for section in analysis_sections:
            section_name = self.SECTION_NAMES.get(section, section)
            if cli_auth_failed:
                sections[section] = "Claude CLI 인증 필요: 터미널에서 'claude login'을 먼저 실행하세요."
                continue
            print(f"  📝 {section_name} 분석 중...")
            try:
                result = self._analyze_section(section, code, name, data)
                sections[section] = result
                # CLI 인증 실패 감지 → 나머지 섹션 skip
                if "Claude CLI 인증 필요" in result:
                    print("  ❌ Claude CLI 인증 실패 — 나머지 AI 분석 섹션 건너뜀")
                    print("     → 터미널에서 'claude login' 실행 후 다시 시도하세요")
                    cli_auth_failed = True
            except Exception as e:
                print(f"  ⚠️ {section_name} 분석 실패: {e}")
                sections[section] = f"분석 중 오류 발생: {e}"

        # 4. 최종 종합 (모든 섹션 요약 → Claude)
        if "investment_thesis" in active_sections:
            if cli_auth_failed:
                sections["investment_thesis"] = "Claude CLI 인증 필요: 터미널에서 'claude login'을 먼저 실행하세요."
            else:
                print("  🤖 AI 종합 투자 의견 생성 중...")
                try:
                    sections["investment_thesis"] = self._synthesize(code, name, sections)
                except Exception as e:
                    print(f"  ⚠️ 종합 의견 생성 실패: {e}")
                    sections["investment_thesis"] = f"종합 분석 중 오류 발생: {e}"

        print(f"[DeepAgent] {name}({code}) 딥 리서치 완료\n")
        return sections

    def _collect_all_data(self, code: str, name: str, data_provider_fn=None) -> dict:
        """모든 데이터 소스에서 데이터 수집"""
        data = {"code": code, "name": name}
        ds = self.config.get("data_sources", {})

        # Naver 재무데이터
        if ds.get("naver_fundamental", True):
            print("  📊 재무데이터 수집 중...")
            try:
                from core.deep_analysis.fundamental_scraper import FundamentalScraper
                scraper = FundamentalScraper()
                data["overview"] = scraper.get_company_overview(code)
                data["financials_annual"] = scraper.get_financial_statements(code, "annual")
                data["financials_quarterly"] = scraper.get_financial_statements(code, "quarterly")
                data["profitability"] = scraper.get_profitability(code)
                data["stability"] = scraper.get_stability(code)
            except Exception as e:
                print(f"  ⚠️ 재무데이터 수집 실패: {e}")

        # DART 공시
        if ds.get("dart_api", True):
            print("  📋 DART 공시 수집 중...")
            try:
                from core.deep_analysis.dart_client import DartClient
                dart = DartClient()
                if dart.available:
                    corp_code = dart.get_corp_code(code)
                    if corp_code:
                        data["dart_company"] = dart.get_company_info(corp_code)
                        data["dart_disclosures"] = dart.get_recent_disclosures(corp_code, months=6)
                        year = str(datetime.now(KST).year - 1)
                        data["dart_financials"] = dart.get_financial_statements(corp_code, year)
                    else:
                        print("  ⚠️ DART 고유번호 매핑 실패")
                else:
                    print("  ⚠️ DART API 비활성")
            except Exception as e:
                print(f"  ⚠️ DART 수집 실패: {e}")

        # 증권사 컨센서스
        if ds.get("naver_consensus", True):
            print("  🎯 컨센서스 수집 중...")
            try:
                from core.deep_analysis.consensus_scraper import ConsensusScraper
                cs = ConsensusScraper()
                data["target_prices"] = cs.get_target_prices(code)
                data["earnings_estimates"] = cs.get_earnings_estimates(code)
            except Exception as e:
                print(f"  ⚠️ 컨센서스 수집 실패: {e}")

        # 기술적 분석
        if ds.get("technical_yfinance", True):
            print("  📈 기술적 분석 중...")
            try:
                from core.deep_analysis.technical_analyzer import TechnicalAnalyzer
                ta = TechnicalAnalyzer()
                data["technical"] = ta.analyze(code)
            except Exception as e:
                print(f"  ⚠️ 기술적 분석 실패: {e}")

        # 동종업계 비교
        if ds.get("peer_comparison", True):
            print("  🏭 동종업계 비교 중...")
            try:
                from core.deep_analysis.peer_analyzer import PeerAnalyzer
                pa = PeerAnalyzer()
                data["peers"] = pa.compare_metrics(code)
            except Exception as e:
                print(f"  ⚠️ 동종업계 비교 실패: {e}")

        # 수급 분석 (기존 SupplyAnalyzer)
        if ds.get("supply_kis", True) and data_provider_fn:
            print("  💹 수급 데이터 수집 중...")
            try:
                from core.analysis.supply import SupplyAnalyzer
                sa = SupplyAnalyzer()
                
                # Fetch dynamically using injected callback
                ohlc, investor_trend, current_data = data_provider_fn(code)
                if investor_trend is not None:
                    data["supply"] = sa.analyze_supply(investor_trend)
            except Exception as e:
                print(f"  ⚠️ 수급 수집 실패: {e}")

        # 뉴스 (기존 NewsScraper)
        if ds.get("news_naver", True):
            print("  📰 뉴스 수집 중...")
            try:
                from core.news_scraper import NewsScraper
                ns = NewsScraper()
                all_news = ns.fetch_news()
                data["news"] = ns.filter_news(all_news, [name, code])
                if not data["news"]:
                    data["news"] = all_news[:10]
            except Exception as e:
                print(f"  ⚠️ 뉴스 수집 실패: {e}")

        # 글로벌 매크로 (기존 MacroAnalyzer)
        if ds.get("macro_global", True):
            print("  🌍 매크로 분석 중...")
            try:
                from core.analysis.macro import MacroAnalyzer
                ma = MacroAnalyzer()
                data["macro"] = {
                    "us_indices": ma.get_us_indices(),
                    "fx": ma.get_fx_rates(),
                    "vix": ma.get_vix(),
                }
            except Exception as e:
                print(f"  ⚠️ 매크로 분석 실패: {e}")

        return data

    def _analyze_section(self, section: str, code: str, name: str, data: dict) -> str:
        """섹션별 Claude 호출 — 해당 섹션에 필요한 데이터만 전달"""

        prompt_builders = {
            "company_overview": self._prompt_company_overview,
            "financial_analysis": self._prompt_financial_analysis,
            "valuation": self._prompt_valuation,
            "industry_competition": self._prompt_industry_competition,
            "supply_technical": self._prompt_supply_technical,
            "news_disclosure": self._prompt_news_disclosure,
            "consensus": self._prompt_consensus,
        }

        builder = prompt_builders.get(section)
        if not builder:
            return ""

        prompt = builder(code, name, data)
        return self._call_claude(prompt, self.max_tokens, self.temperature)

    def _synthesize(self, code: str, name: str, sections: dict) -> str:
        """전 섹션 요약을 받아 최종 투자 의견 생성"""
        section_summaries = []
        for key, content in sections.items():
            section_name = self.SECTION_NAMES.get(key, key)
            # 각 섹션 내용을 적당히 요약 (너무 길면 잘라냄)
            truncated = content[:1500] if len(content) > 1500 else content
            section_summaries.append(f"### {section_name}\n{truncated}")

        all_summaries = "\n\n".join(section_summaries)

        prompt = f"""당신은 전문 주식 분석가 'Firefeet AI'입니다.
아래는 {name}({code})에 대해 7개 분야에서 분석한 결과입니다.
이를 종합하여 최종 투자 의견을 작성하세요.

{all_summaries}

---

### 작성 가이드라인:
1. **투자 의견**: [적극 매수 / 매수 / 중립 / 매도 / 적극 매도] 중 하나를 선택하고 별점(★)으로 표시
2. **적정 주가 범위**: 밸류에이션 분석과 컨센서스를 기반으로 추정
3. **투자 시나리오**: 낙관/기본/비관 3가지 시나리오로 구분
   - 🟢 낙관 시나리오: 조건 + 예상 주가
   - 🟡 기본 시나리오: 조건 + 예상 주가
   - 🔴 비관 시나리오: 조건 + 예상 주가
4. **핵심 리스크**: 3-5개 핵심 리스크 요인
5. **최종 추천**: 2-3문장으로 결론

한국어로 작성하세요. 마크다운 형식을 사용하세요.
전문적이고 객관적인 어조를 유지하세요.
숫자와 근거를 반드시 포함하세요."""

        return self._call_claude(prompt, self.max_tokens_synthesis, self.synthesis_temperature)

    def _call_claude(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Claude API 호출 — SDK 또는 CLI fallback"""
        if self.use_cli:
            return self._call_claude_cli(prompt, max_tokens)
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except Exception as e:
            return f"Claude API 호출 실패: {e}"

    def _call_claude_cli(self, prompt: str, max_tokens: int) -> str:
        """claude CLI를 통한 호출 (Max 플랜 인증 활용)"""
        try:
            env = os.environ.copy()
            env.pop("CLAUDECODE", None)

            result = subprocess.run(
                ["claude", "-p", "--output-format", "text"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )

            output = result.stdout.strip()
            stderr = result.stderr.strip()

            # 로그인 안 된 경우 감지
            if "Not logged in" in output or "Not logged in" in stderr or "/login" in output:
                return ("Claude CLI 인증 필요: 터미널에서 'claude login'을 먼저 실행하세요.\n"
                        "(Max 플랜이면 'claude login' → 브라우저 인증)")

            if result.returncode != 0 and stderr:
                return f"Claude CLI 호출 실패: {stderr}"

            return output or stderr
        except subprocess.TimeoutExpired:
            return "Claude CLI 호출 타임아웃 (180초)"
        except FileNotFoundError:
            return "claude CLI를 찾을 수 없습니다. Claude Code가 설치되어 있는지 확인하세요."
        except Exception as e:
            return f"Claude CLI 호출 실패: {e}"

    # ──────────────────────────────────────────────────────────────
    # 섹션별 프롬프트 빌더
    # ──────────────────────────────────────────────────────────────

    def _prompt_company_overview(self, code: str, name: str, data: dict) -> str:
        overview = data.get("overview", {})
        dart_info = data.get("dart_company", {})

        return f"""당신은 전문 주식 분석가입니다.
{name}({code})의 기업 개요를 분석하세요.

### 기업 기본 정보
{_dumps(overview)}

### DART 기업 정보
{_dumps(dart_info)}

### 작성 가이드라인:
- 사업 모델과 주요 매출원 요약 (1-2문단)
- 핵심 경쟁력 (기술, 브랜드, 시장 지위 등)
- 업종 내 위치
- 시가총액, PER, PBR 등 기본 밸류에이션 수치 정리
- 한국어로 작성, 마크다운 형식"""

    def _prompt_financial_analysis(self, code: str, name: str, data: dict) -> str:
        annual = data.get("financials_annual", {})
        quarterly = data.get("financials_quarterly", {})
        profitability = data.get("profitability", {})
        stability = data.get("stability", {})
        dart_fin = data.get("dart_financials", {})

        return f"""당신은 전문 주식 분석가입니다.
{name}({code})의 재무 상태를 분석하세요.

### 연간 재무제표
{_dumps(annual)}

### 분기 재무제표
{_dumps(quarterly)}

### 수익성 지표 추세
{_dumps(profitability)}

### 안정성 지표 추세
{_dumps(stability)}

### DART 재무제표 (전년도)
{_dumps(dart_fin) if dart_fin else "데이터 없음"}

### 작성 가이드라인:
1. **수익성 분석**: 매출 성장률, 영업이익률, ROE 추세를 테이블로 정리하고 해석
2. **성장성 분석**: 매출/이익 성장 트렌드, 가속/둔화 여부
3. **안정성 분석**: 부채비율, 유동비율 추세
4. **핵심 변화 포인트**: 전년 대비 가장 크게 변한 지표와 원인 추정
5. 숫자를 포함한 테이블 형식 적극 활용
- 한국어로 작성, 마크다운 형식"""

    def _prompt_valuation(self, code: str, name: str, data: dict) -> str:
        overview = data.get("overview", {})
        annual = data.get("financials_annual", {})
        peers = data.get("peers", {})
        estimates = data.get("earnings_estimates", {})

        return f"""당신은 전문 주식 분석가입니다.
{name}({code})의 밸류에이션을 분석하세요.

### 현재 밸류에이션
- 현재가: {overview.get('current_price', 'N/A')}
- PER: {overview.get('per', 'N/A')}
- PBR: {overview.get('pbr', 'N/A')}
- 배당수익률: {overview.get('dividend_yield', 'N/A')}%
- 업종 PER: {overview.get('sector_per', 'N/A')}

### 연간 재무 (PER/PBR/EPS/BPS 추세)
{_dumps(annual)}

### 동종업계 비교
{_dumps(peers)}

### 실적 추정치
{_dumps(estimates)}

### 작성 가이드라인:
1. **현재 밸류에이션 수준**: PER/PBR 과거 밴드 대비 위치, 업종 평균 대비
2. **적정가 추정**: EPS × 적정 PER 범위 기반 적정 주가 레인지
3. **비교 밸류에이션**: 동종업계 대비 프리미엄/디스카운트 정도
4. 비교표 형식 적극 활용
- 한국어로 작성, 마크다운 형식"""

    def _prompt_industry_competition(self, code: str, name: str, data: dict) -> str:
        peers = data.get("peers", {})
        overview = data.get("overview", {})

        return f"""당신은 전문 주식 분석가입니다.
{name}({code})의 산업 및 경쟁 환경을 분석하세요.

### 기업 개요
업종: {overview.get('sector', 'N/A')}

### 동종업계 비교 데이터
{_dumps(peers)}

### 작성 가이드라인:
1. **업종 현황**: 산업 트렌드, 시장 규모/성장성
2. **시장 내 위치**: 시가총액 기준 순위, 주요 지표 백분위
3. **SWOT 분석**: 표 형식으로 강점/약점/기회/위협 정리
4. **경쟁 우위**: 해자(moat), 차별화 요인
5. **위협 요인**: 경쟁 심화, 규제, 기술 변화
- 한국어로 작성, 마크다운 형식"""

    def _prompt_supply_technical(self, code: str, name: str, data: dict) -> str:
        supply = data.get("supply", {})
        technical = data.get("technical", {})

        return f"""당신은 전문 주식 분석가입니다.
{name}({code})의 수급과 기술적 분석을 수행하세요.

### 수급 데이터 (외국인/기관 순매수)
{_dumps(supply) if isinstance(supply, dict) else supply}

### 기술적 분석
{_dumps(technical)}

### 작성 가이드라인:
1. **수급 분석**: 외국인/기관 최근 동향, 수급 방향성
2. **추세 분석**: 이동평균선 정배열/역배열, 중장기 추세 방향
3. **모멘텀 지표**: RSI, MACD 상태 + 매매 시그널
4. **지지/저항**: 주요 가격대, 52주 고저 대비 위치
5. **거래량**: 최근 거래량 변화와 의미
6. **매수 타이밍 판단**: 기술적으로 진입하기 좋은 시점인지
- 한국어로 작성, 마크다운 형식"""

    def _prompt_news_disclosure(self, code: str, name: str, data: dict) -> str:
        news = data.get("news", [])
        disclosures = data.get("dart_disclosures", [])

        return f"""당신은 전문 주식 분석가입니다.
{name}({code})의 최근 뉴스와 공시를 분석하세요.

### 최근 뉴스
{_dumps(news[:15]) if news else "뉴스 데이터 없음"}

### 최근 DART 공시 (6개월)
{_dumps(disclosures[:20]) if disclosures else "공시 데이터 없음"}

### 작성 가이드라인:
1. **주요 뉴스 분류**: 호재/악재/중립으로 분류하고 주가 영향 평가
2. **공시 분석**: 중요도 높은 공시 하이라이트 (유상증자, M&A, 실적 등)
3. **이벤트 캘린더**: 향후 예상 이벤트 (실적 발표, 배당 등)
4. **시장 반응 예측**: 뉴스/공시가 주가에 미칠 영향 평가
- 한국어로 작성, 마크다운 형식"""

    def _prompt_consensus(self, code: str, name: str, data: dict) -> str:
        target_prices = data.get("target_prices", {})
        estimates = data.get("earnings_estimates", {})

        return f"""당신은 전문 주식 분석가입니다.
{name}({code})에 대한 증권사 컨센서스를 분석하세요.

### 증권사 목표가
{_dumps(target_prices)}

### 실적 추정치 (컨센서스)
{_dumps(estimates)}

### 작성 가이드라인:
1. **목표가 분석**: 평균/최고/최저 목표가, 현재가 대비 상승 여력
2. **투자의견 분포**: 매수/보유/매도 비율
3. **실적 전망**: 향후 매출/영업이익 컨센서스 추세
4. **서프라이즈 가능성**: 컨센서스 대비 실적 상회/하회 가능성
5. **시장 기대 vs 현실 괴리**: 목표가와 현재가의 갭이 큰 이유 분석
- 한국어로 작성, 마크다운 형식"""


if __name__ == "__main__":
    agent = DeepAgent()
    sections = agent.analyze("005930", "삼성전자")
    for key, content in sections.items():
        print(f"\n{'='*60}")
        print(f"[{agent.SECTION_NAMES.get(key, key)}]")
        print(f"{'='*60}")
        print(content[:500])
