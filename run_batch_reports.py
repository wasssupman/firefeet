import os
import sys
import time
import argparse
import pandas as pd
import json
import subprocess
from datetime import datetime

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.analysis.scoring_engine import StockScreener
from core.deep_analysis.deep_agent import DeepAgent
from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.news_scraper import NewsScraper

def _startup_health_check():
    """배치 리포트 시작 전 필수 의존성 점검"""
    import subprocess

    warnings = []

    # 1. Claude CLI 사용 가능 여부
    try:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=10,
            env=env, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            warnings.append("Claude CLI 실행 불가")
    except FileNotFoundError:
        warnings.append("Claude CLI 미설치 — API 전용 모드로 동작")
    except Exception:
        warnings.append("Claude CLI 확인 실패")

    # 2. config 파일 확인
    if not os.path.exists("config/secrets.yaml"):
        print("[FATAL] config/secrets.yaml 누락. 종료합니다.")
        sys.exit(1)

    # 3. logs/reports 디렉토리
    os.makedirs("logs", exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    if warnings:
        for w in warnings:
            print(f"  [WARN] {w}")

    print("[Health Check] 통과.")


def get_top_stocks(limit=20, use_ai=True):
    """
    1. 거래량 상위 종목 추출
    2. 수급 필터링 (외국인/기관 순매수) 및 스코어링 (기술적 지표)
    3. AI 테마 필터 (Claude CLI)를 통한 최종 종목 선정
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 고급 종목 스크리닝 파이프라인 시작 (목표: {limit}개)...")
    
    loader = ConfigLoader()
    kis_config = loader.get_kis_config(mode="REAL")
    account_info = loader.get_account_info()
    auth = KISAuth(kis_config)
    manager = KISManager(auth, account_info, mode="REAL")
        
    print("1. KOSPI & KOSDAQ 거래량 상위 100개 종목 추출 중...")
    try:
        volume_top = manager.get_top_volume_stocks(limit=50) # 50 returns 50 kospi + 50 kosdaq
    except Exception as e:
        print(f"[오류] 거래량 순위 조회 실패: {e}")
        return []

    if not volume_top:
        print("[오류] 거래량 상위 종목 응답이 비어있습니다.")
        return []
        
    print(f"2. {len(volume_top)}개 종목 대상 수급 및 기술적 스코어링 진행 중...")
    screener = StockScreener(strategy="deep_batch")
    
    filtered_stocks = []
    for i, stock_info in enumerate(volume_top):
        try:
            code = stock_info['code']
            name = stock_info['name']
            
            if (i+1) % 10 == 0:
                print(f"   - 필터링 진행 중: {i+1}/{len(volume_top)}")
                
            time.sleep(0.5) 
            
            # [수급 필터] 최근 3일 외국인 또는 기관 순매수 합계 체크
            trend = manager.get_investor_trend(code)
            if trend is None or trend.empty or len(trend) < 3:
                continue
                
            recent_3d = trend.head(3)
            foreign_buy = recent_3d['foreigner'].sum()
            inst_buy = recent_3d['institution'].sum()
            
            # 둘 다 매도중이면 탈락
            if foreign_buy <= 0 and inst_buy <= 0:
                continue
                
            time.sleep(0.5)
            # 데이터 조회
            ohlc = manager.get_daily_ohlc(code)
            if ohlc is None or ohlc.empty:
                continue
                
            current_price = int(ohlc.iloc[0]['close'])
            change_rate = float((ohlc.iloc[0]['close'] - ohlc.iloc[1]['close']) / ohlc.iloc[1]['close'] * 100) if len(ohlc) > 1 else 0
            volume = int(ohlc.iloc[0]['volume'])
            
            stock_data = {
                "code": code,
                "name": name,
                "price": current_price,
                "change_rate": change_rate,
                "volume": volume
            }
            
            supply_data = {
                "foreign_3d": int(foreign_buy),
                "institution_3d": int(inst_buy),
                "sentiment": "BULLISH (Double Buy)" if foreign_buy > 0 and inst_buy > 0 else "NEUTRAL"
            }
            
            current_data = {
                "high": int(ohlc.iloc[0]['high'])
            }
            
            score_detail = screener.score_stock(stock_data, ohlc, supply_data, current_data)
            total_score = score_detail.get("total_score", 0)
            
            # 기술적 스코어 컷오프
            # screener.settings["output"]["min_score"] 활용
            if total_score >= 15: # 기본 컷오프 조금 완화 (AI가 최종 판단하므로)
                filtered_stocks.append({
                    "code": code,
                    "name": name,
                    "score": total_score,
                    "price": current_price,
                    "foreign_buy": int(foreign_buy),
                    "inst_buy": int(inst_buy)
                })
                
        except Exception as e:
            continue
            
    print(f"   => 수급 및 기본 필터링 통과 종목: {len(filtered_stocks)}개")
    
    if not filtered_stocks:
        print("조건을 만족하는 종목이 없어 스크리닝을 종료합니다.")
        return []

    if not use_ai:
        print(f"\n3. AI 필터링 생략 (--no-ai). 기술적/수급 스코어 기반 상위 {limit}개 추출...")
        df_results = pd.DataFrame(filtered_stocks).sort_values(by="score", ascending=False)
        final_stocks = df_results.head(limit).to_dict('records')
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 스크리닝 완료. 최종 {len(final_stocks)}개 종목 선정.")
        return final_stocks, "AI 개입 없이 순수 데이터로만 추출되었습니다."

    print(f"3. AI 시장 트렌드 및 테마 기반 최종 타겟 {limit}개 선정 (Claude CLI)...")
    try:
        # 뉴스 가져오기 (시황 파악용)
        ns = NewsScraper()
        recent_news = ns.fetch_news()
        news_summary = json.dumps(recent_news[:10], ensure_ascii=False) if recent_news else "뉴스 정보 없음."
        
        # 종목 리스트 텍스트화
        stock_list_text = "\n".join([f"- {s['name']} ({s['code']}) | 퀀트점수: {s['score']:.1f} | 수급: 외인 {s['foreign_buy']} / 기관 {s['inst_buy']}" for s in filtered_stocks])
        
        prompt = f'''당신은 최고 수준의 주식 펀드매니저입니다.
        
오늘의 주요 시장 뉴스 헤드라인:
{news_summary}

다음은 수급(외국인/기관 순매수)과 차트 기초 점수를 통과한 우량/모멘텀 종목 후보군입니다:
{stock_list_text}

지시사항:
위 뉴스를 기반으로 "현재 시장을 주도하고 있는 테마와 가장 부합하며, 수급 흐름까지 탄탄한" 종목 상위 {limit}개를 엄선해 주십시오. 
배경 지식과 뉴스 모멘텀을 총동원하여 단순 차트 테크니컬이 아닌 '내러티브(통신, 원전, AI, 실적 개선 등)'가 훌륭한 종목을 1순위로 고려하세요.

출력 형식:
반드시 아래 JSON 형식으로만 반환하십시오. 다른 문장이나 설명은 절대 추가하지 마십시오.
{{
  "reasoning": "왜 이 테마와 종목들을 선정했는지에 대한 2~3줄의 핵심 시장 요약",
  "codes": ["005930", "000660"]
}}
'''     
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        result = subprocess.run(
            ["claude", "-p", "--output-format", "text"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
            encoding="utf-8",
            errors="replace"
        )
        
        output = result.stdout.strip()
        print(f"   => AI 응답 완료. 파싱 중...")
        
        # JSON 문자열 추출 및 클렌징
        selected_codes = []
        ai_reasoning = ""
        if "```" in output: # 혹시 마크다운 블록이 있으면 제거
             output = output.replace("```json", "").replace("```", "").strip()

        if "{" in output and "}" in output:
            try:
                json_str = output[output.find("{"):output.rfind("}")+1]
                parsed = json.loads(json_str)
                selected_codes = parsed.get("codes", [])[:limit]
                ai_reasoning = parsed.get("reasoning", "이유가 제공되지 않음.")
            except Exception as e:
                print(f"   => JSON 파싱 에러: {e}")
        
        if not selected_codes:
            print("   => AI 응답 파싱 실패 또는 빈 목록. 점수 순으로 대체합니다.")
            df_results = pd.DataFrame(filtered_stocks).sort_values(by="score", ascending=False)
            return df_results.head(limit).to_dict('records'), "AI 파싱 실패로 점수 순 대체됨."
            
        final_stocks = [s for s in filtered_stocks if s['code'] in selected_codes]
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 스크리닝 완료. 최종 {len(final_stocks)}개 종목 선정.")
        return final_stocks, ai_reasoning
        
    except Exception as e:
        print(f"AI 테마 필터링 중 오류 발생: {e}. 점수 순으로 대체합니다.")
        df_results = pd.DataFrame(filtered_stocks).sort_values(by="score", ascending=False)
        return df_results.head(limit).to_dict('records'), f"AI 오류 발생: {e}"

from core.deep_analysis.report_builder import ReportBuilder
import yaml

def load_config(path="config/deep_analysis.yaml"):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def run_batch_analysis(stocks, batch_size=3, sleep_between_stocks=15, sleep_between_batches=300):
    """선정된 종목들을 배치(묶음)로 나누어 순차 분석합니다."""
    
    total_stocks = len(stocks)
    print(f"\n🚀 총 {total_stocks}개 종목에 대한 딥 리서치 봇 배치를 시작합니다.")
    print(f"   - 배치 단위: {batch_size}개")
    print(f"   - 종목 간 대기: {sleep_between_stocks}초")
    print(f"   - 배치 간 휴식: {sleep_between_batches}초\n")
    
    config = load_config()
    agent = DeepAgent()
    builder = ReportBuilder(config)
    
    loader = ConfigLoader()
    kis_config = loader.get_kis_config(mode="REAL")
    account_info = loader.get_account_info()
    auth = KISAuth(kis_config)
    manager = KISManager(auth, account_info, mode="REAL")
    
    def data_provider(code):
        ohlc = manager.get_daily_ohlc(code)
        time.sleep(0.5)
        investor_trend = manager.get_investor_trend(code)
        time.sleep(0.5)
        current_data = manager.get_current_price(code)
        return ohlc, investor_trend, current_data
    
    for i in range(0, total_stocks, batch_size):
        batch = stocks[i:i+batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_stocks + batch_size - 1) // batch_size
        
        print(f"[" + "="*40 + "]")
        print(f"📦 배치 #{batch_num}/{total_batches} 시작 ({len(batch)}개 종목)")
        print(f"[" + "="*40 + "]\n")
        
        for j, stock in enumerate(batch):
            code = stock['code']
            name = stock['name']
            score = stock['score']
            
            current_idx = i + j + 1
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚙️ 진행률: {current_idx}/{total_stocks} | 분석 대상: {name}({code}) [점수: {score:.1f}]")
            
            try:
                # 딥 리서치 실행
                sections = agent.analyze(code, name, None, data_provider_fn=data_provider)
                
                # 리포트 조립 및 저장
                report = builder.build(code, name, sections, model=agent.model)
                summary = builder.build_summary(code, name, sections)
                
                output_cfg = config.get("output", {})
                if output_cfg.get("save_file", True):
                    filepath = builder.save_to_file(report, code, name)
                    print(f"  └─ ✅ 리포트 저장 완료: {filepath}")
                else:
                    print(f"  └─ ✅ 분위기 요약: {summary[:100]}...")
            except Exception as e:
                print(f"  └─ ❌ [오류] {name}({code}) 분석 중 예외 발생: {e}")
            
            # 다음 종목이 남아 있다면 종목 간 쿨다운 대기
            if j < len(batch) - 1:
                print(f"  (봇 탐지 방지를 위해 {sleep_between_stocks}초 대기 중...)\n")
                time.sleep(sleep_between_stocks)
                
        # 배치가 완료되었고, 아직 전체 루프가 남았다면 길게 휴식
        if batch_num < total_batches:
            print(f"\n💤 배치 #{batch_num} 완료. 서버 과부하 방지를 위해 {sleep_between_batches/60:.1f}분({sleep_between_batches}초)간 긴 휴식에 들어갑니다...")
            for remaining in range(sleep_between_batches, 0, -10):
                sys.stdout.write(f"\r  남은 대기 시간: {remaining}초  ")
                sys.stdout.flush()
                time.sleep(min(10, remaining))
            print("\n")

if __name__ == "__main__":
    _startup_health_check()
    parser = argparse.ArgumentParser(description="수십 개의 종목을 자동으로 필터링 및 리포팅하는 배치 스크립트")
    parser.add_argument("--limit", type=int, default=10, help="스크리닝할 총 종목 수 (기본 10)")
    parser.add_argument("--batch", type=int, default=3, help="한 번에 연속으로 분석할 묶음 개수 (기본 3)")
    parser.add_argument("--delay", type=int, default=15, help="종목 간 대기 시간 초 (기본 15)")
    parser.add_argument("--rest", type=int, default=300, help="배치와 배치 사이 긴 대기 시간 초 (기본 300초 = 5분)")
    parser.add_argument("--no-ai", action="store_true", help="AI 딥 리서치 및 테마 필터링을 생략하고 스크리닝 결과만 출력/저장합니다.")
    parser.add_argument("--stage2-only", action="store_true", help="2단계(AI 테마 스크리닝)까지만 진행하고 3단계(딥 리서치)는 생략합니다.")
    
    args = parser.parse_args()
    
    # 1. 대상 종목 추출
    target_stocks, ai_reasoning = get_top_stocks(limit=args.limit, use_ai=not args.no_ai)
    
    # 2. 분석 실행
    if target_stocks:
        if args.no_ai:
            print(f"\n🚀 AI 분석이 모두 생략되었습니다. 순수 데이터 필터링 선정된 {len(target_stocks)}개 종목 리스트:")
            df = pd.DataFrame(target_stocks)
            print(df.to_string(index=False))
            os.makedirs("reports", exist_ok=True)
            csv_path = f"reports/filtered_stocks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')
            print(f"\n📄 스크리닝 결과가 CSV로 저장되었습니다: {csv_path}")
        elif args.stage2_only:
            print(f"\n🚀 3단계(AI 딥 리서치)가 생략되었습니다. 2단계 테마 선별 통과 {len(target_stocks)}개 종목 리스트:")
            
            os.makedirs("reports", exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            md_path = f"reports/Stage2_Thematic_Screening_{timestamp}.md"
            
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(f"# 🎯 Stage 2: AI Thematic Screening Report\n\n")
                f.write(f"**생성 일시:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                f.write(f"## 🤖 AI 시장 요약 및 테마 선정 사유\n")
                f.write(f"> {ai_reasoning}\n\n")
                
                f.write(f"## 🏆 선정 종목 Top {len(target_stocks)}\n")
                f.write("| 순위 | 종목명 | 종목코드 | 퀀트 점수 | 외인 순매수(3일) | 기관 순매수(3일) |\n")
                f.write("|---|---|---|---|---|---|\n")
                for idx, s in enumerate(target_stocks):
                    f.write(f"| {idx+1} | **{s['name']}** | `{s['code']}` | {s['score']:.1f} | {s['foreign_buy']:,} | {s['inst_buy']:,} |\n")
            
            print(f"\n📄 파이어피트 AI 테마 스크리닝 결과가 마크다운으로 저장되었습니다: {md_path}")
        else:
            run_batch_analysis(
                target_stocks, 
                batch_size=args.batch, 
                sleep_between_stocks=args.delay, 
                sleep_between_batches=args.rest
            )
    else:
        print("분석할 종목을 찾지 못해 스크립트를 종료합니다.")
