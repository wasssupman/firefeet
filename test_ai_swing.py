import pandas as pd
import json
from core.analysis.ai_swing_agent import AISwingAgent

def test_ai_swing_parsing():
    agent = AISwingAgent()
    
    # Mock Response
    mock_claude_response = """
    여기에 분석 내용이 조금 적혀있고 JSON 으로 응답하겠습니다.
    
    ```json
    {
        "decision": "BUY",
        "confidence": 85,
        "strategy_type": "BREAKOUT",
        "target_price": 85000,
        "stop_loss": 78000,
        "reasoning": "외국인 양매수세와 함께 전고점을 돌파하는 흐름이 포착됨. 단기 스윙에 적합."
    }
    ```
    """
    
    # Test Parsing Method directly
    result = agent._parse_response(mock_claude_response, "005930", "삼성전자")
    
    print("Parsed Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    assert result["decision"] == "BUY"
    assert result["confidence"] == 85
    assert result["strategy_type"] == "BREAKOUT"
    assert result["target_price"] == 85000
    assert result["stop_loss"] == 78000
    
    print("✅ Parsing test passed!")

if __name__ == "__main__":
    test_ai_swing_parsing()
