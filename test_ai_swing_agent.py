import os
import sys
import pandas as pd
import json
from pprint import pprint

from core.encoding_setup import setup_utf8_stdout
setup_utf8_stdout()

# Ensure the core module is in the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.analysis.ai_swing_agent import AISwingAgent

def main():
    print("🔥 AISwingAgent 테스트 시작...")
    
    agent = AISwingAgent()
    
    # 1. Mock OHLC Data (DataFrame)
    dates = pd.date_range(end=pd.Timestamp.today(), periods=10)
    ohlc_data = pd.DataFrame({
        "open": [70000 + i*100 for i in range(10)],
        "high": [71000 + i*100 for i in range(10)],
        "low": [69000 + i*100 for i in range(10)],
        "close": [70500 + i*100 for i in range(10)],
        "volume": [1000000 + i*10000 for i in range(10)]
    }, index=dates)
    
    # 2. Mock Supply Data (DataFrame) -> To test our recent fix
    supply_data = pd.DataFrame([
        {"date": "2026-02-18", "foreign_buy": 50000, "inst_buy": 30000, "sentiment": "BULLISH"},
        {"date": "2026-02-19", "foreign_buy": 60000, "inst_buy": 40000, "sentiment": "BULLISH"},
        {"date": "2026-02-20", "foreign_buy": 120000, "inst_buy": 80000, "sentiment": "STRONG_BULLISH"}
    ])
    
    # 3. Market Temp & News & Current Data
    current_data = {"price": 71400}
    market_temp = {
        "temperature": 45.5,
        "level": "WARM",
        "components": {"macro": 20, "sentiment": 15, "econ": 10}
    }
    news = [
        {"title": "[특징주] 삼성전자, AI 반도체 수요 폭발에 강세", "link": "http://example.com/1", "time": "10:00:00"},
        {"title": "외국인 3일 연속 순매수... 삼전 목표가 상향", "link": "http://example.com/2", "time": "11:30:00"}
    ]
    screener_score = 88.5
    
    data = {
        "ohlc": ohlc_data,
        "supply": supply_data,
        "current_data": current_data,
        "market_temp": market_temp,
        "news": news,
        "screener_score": screener_score
    }
    
    print("\\n[Mock Data 준비 완료]")
    print(f"- 종목명: 삼성전자 (005930)")
    print(f"- 현재가: {current_data['price']}")
    print(f"- 스크리너 점수: {screener_score}")
    print(f"- 시장 온도: {market_temp['level']} ({market_temp['temperature']})")
    print(f"- 수급 데이터 형식: {type(supply_data)} (수정된 JSON 파싱 테스트용)\\n")
    
    print("🤖 Claude AI 판단 요청 중... (CLI Fallback일 경우 약 30~60초 소요될 수 있습니다.)\\n")
    
    try:
        result = agent.analyze_trading_opportunity("005930", "삼성전자", data)
        print("✅ 판독 완료! 결과 JSON:\\n")
        print(json.dumps(result, indent=4, ensure_ascii=False))
        
        print("\\n📝 요약:")
        print(f"결정: {result.get('decision')}")
        print(f"전략: {result.get('strategy_type')}")
        print(f"확신도: {result.get('confidence')}%")
        print(f"목표가: {result.get('target_price')}원 / 손절가: {result.get('stop_loss')}원")
        print(f"이유: {result.get('reasoning')}")
        
    except Exception as e:
        print(f"\\n❌ 테스트 실행 중 오류 발생: {e}")

if __name__ == "__main__":
    main()
