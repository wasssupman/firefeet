from core.analysis.ai_thematic_filter import AIThematicFilter
import time

def test_ai_thematic():
    print("Initializing AIThematicFilter...")
    # Give it a tight config for testing
    config = {
        "enabled": True,
        "model": "claude-sonnet-4-20250514",
        "max_workers": 2,
        "top_n": 2
    }

    filter_module = AIThematicFilter(config)

    # Mock some scored stocks
    scored_stocks = [
        {"code": "005930", "name": "삼성전자", "total_score": 85},
        {"code": "000660", "name": "SK하이닉스", "total_score": 82},
        {"code": "035420", "name": "NAVER", "total_score": 70}
    ]

    print(f"\nEvaluating Top 2 out of {len(scored_stocks)} stocks...")
    start_time = time.time()
    results = filter_module.filter_candidates(scored_stocks, top_n=2)
    end_time = time.time()

    print("\n--- Thematic Filter Results ---")
    print(f"Time Taken: {end_time - start_time:.2f} seconds\n")

    for r in results:
        print(f"[{r['name']}] Score: {r['total_score']} | AI Reasoning: {r.get('ai_reasoning', 'N/A')}")

if __name__ == "__main__":
    test_ai_thematic()
