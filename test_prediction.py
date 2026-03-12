from core.news_analyzer import NewsAnalyzer
from core.analysis.llms.claude_cli import call_claude

def predict():
    try:
        analyzer = NewsAnalyzer()
        news = analyzer.fetch_global_news_titles(limit=15)
        if not news:
            print("[predict] 뉴스 수집 실패 — 예측 불가")
            return

        news_text = "\n".join([f"- {n}" for n in news])

        prompt = f"""당신은 여의도의 탑티어 시황 분석가입니다.
다음 글로벌 지정학/경제 뉴스를 바탕으로 '내일 한국 주식시장(KOSPI/KOSDAQ)'의 시초가 분위기와 장중 흐름을 폭넓게 예측해주세요.

[최신 글로벌 뉴스 헤드라인]
{news_text}

분석 및 예측할 내용:
1. 전일 밤 미 증시 및 글로벌 이벤트가 한국 증시에 미칠 영향
2. 내일 개장 초(시초가) 예상 분위기 (강세/약세/보합)
3. 내일 장중 주목해야 할 핵심 테마나 주요 섹터 (예: 반도체, 금융 등)
4. 종합 투자 의견 및 전략 (Risk-On / Risk-Off)
"""
        print("Claude CLI 시황 분석 중...\n")
        result = call_claude(prompt, timeout=180)
        print(result)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    predict()
