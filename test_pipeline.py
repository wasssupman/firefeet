"""Claude 전환 후 전체 파이프라인 통합 테스트 (API 키 없이 mock/fallback 검증)"""
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')

def main():
    print('=' * 60)
    print('Firefeet AI Swing Bot — Pipeline Integration Test')
    print('=' * 60)

    # Phase 0: Import
    print('\n[Phase 0] 모듈 로딩...')
    from core.analysis.ai_swing_agent import AISwingAgent
    from core.analysis.llms.claude_analyst import ClaudeAnalyst
    from core.analysis.llms.claude_executor import ClaudeExecutor
    from core.analysis.llms.vision_analyst import VisionAnalyst
    from core.analysis.ai_thematic_filter import AIThematicFilter
    from core.temperature.ai_macro_module import AIMacroModule
    print('  OK: AISwingAgent, ClaudeAnalyst, ClaudeExecutor, VisionAnalyst, AIThematicFilter, AIMacroModule')

    # Phase 1: Agent composition
    print('\n[Phase 1] AI Agent 구성 확인...')
    agent = AISwingAgent()
    print(f'  Analyst : {type(agent.analyst).__name__} (model={agent.analyst.model_name})')
    print(f'  Executor: {type(agent.executor).__name__} (model={agent.executor.model_name})')
    print(f'  Vision  : {type(agent.vision).__name__} (model={agent.vision.model_name})')
    assert type(agent.analyst).__name__ == 'ClaudeAnalyst', "Analyst should be ClaudeAnalyst"
    assert type(agent.executor).__name__ == 'ClaudeExecutor', "Executor should be ClaudeExecutor"
    assert type(agent.vision).__name__ == 'VisionAnalyst', "Vision should be VisionAnalyst"
    print('  PASS: 구성 정상 (ClaudeAnalyst -> ClaudeExecutor -> VisionAnalyst)')

    # Phase 2: ClaudeAnalyst mock memo
    print('\n[Phase 2] ClaudeAnalyst -> 투자 메모 생성 (mock)...')
    mock_data = {
        'current_data': {'price': 82500},
        'screener_score': 78,
        'market_temp': {'score': 45, 'level': 'WARM'},
        'news': [{'title': 'AI 반도체 수주', 'date': '2026-02-23'}],
        'supply': {'foreign_net': 50000},
    }
    memo = agent.analyst.analyze('005930', '삼성전자', mock_data)
    assert len(memo) > 50, "Memo should have content"
    assert '삼성전자' in memo, "Memo should contain stock name"
    print(f'  OK: {len(memo)}자 생성')
    print(f'  첫줄: {memo.strip().splitlines()[0]}')

    # Phase 3: ClaudeExecutor fallback JSON (skip CLI to avoid 60s timeout)
    print('\n[Phase 3] ClaudeExecutor -> JSON 매매 결정 (fallback)...')
    executor = ClaudeExecutor()
    # Directly test fallback path instead of CLI
    fallback = executor._fallback_json()
    assert fallback['decision'] == 'HOLD'
    print(f'  OK: fallback decision={fallback["decision"]}, confidence={fallback["confidence"]}')
    # Test JSON parser
    test_json = '{"decision":"BUY","confidence":80,"strategy_type":"BREAKOUT","target_price":90000,"stop_loss":78000,"reasoning":"test"}'
    parsed = executor._parse_json(test_json)
    assert parsed['decision'] == 'BUY'
    print(f'  OK: JSON parser works (decision={parsed["decision"]})')
    # Test with markdown fences
    fenced = f'```json\n{test_json}\n```'
    parsed2 = executor._parse_json(fenced)
    assert parsed2['decision'] == 'BUY'
    print(f'  OK: Markdown fence stripping works')

    # Phase 4: VisionAnalyst mock
    print('\n[Phase 4] VisionAnalyst -> 차트 검증 (Gemini, mock)...')
    vr = agent.vision.validate(b'', '005930', '삼성전자')
    assert vr['action'] == 'CONFIRM'
    print(f'  OK: action={vr["action"]}, confidence={vr["confidence"]}%, risk={vr["risk_level"]}')

    # Phase 5: AIThematicFilter disabled passthrough
    print('\n[Phase 5] AIThematicFilter 비활성 패스스루...')
    tf = AIThematicFilter({'enabled': True, 'model': 'claude-sonnet-4-20250514'})
    print(f'  model={tf.model_name}, client_ready={tf.client_ready}')
    stocks = [{'code': '005930', 'name': '삼성전자', 'total_score': 85}]
    result = tf.filter_candidates(stocks)
    assert len(result) == 1
    print(f'  OK: passthrough 정상 ({len(result)}종목 반환)')

    # Phase 6: AIMacroModule disabled fallback
    print('\n[Phase 6] AIMacroModule 비활성 fallback...')
    am = AIMacroModule({'enabled': True, 'model': 'claude-sonnet-4-20250514'})
    print(f'  model={am.model_name}, client_ready={am.client_ready}')
    override = am.evaluate_override(50.0)
    assert override['multiplier'] == 1.0
    print(f'  OK: multiplier={override["multiplier"]}')

    # Phase 7: Sanity check
    print('\n[Phase 7] AISwingAgent sanity check 로직...')
    good = agent._sanity_check(
        {'decision': 'BUY', 'target_price': 90000, 'stop_loss': 78000},
        {'current_price': 82500}, '005930', '삼성전자'
    )
    assert good['decision'] == 'BUY', "Valid BUY should pass"
    print('  OK: 유효한 BUY 통과')
    bad = agent._sanity_check(
        {'decision': 'BUY', 'target_price': 70000, 'stop_loss': 90000},
        {'current_price': 82500}, '005930', '삼성전자'
    )
    assert bad['decision'] == 'WAIT', "Invalid BUY should be overridden to WAIT"
    print('  OK: 비정상 BUY -> WAIT 오버라이드')

    print('\n' + '=' * 60)
    print('ALL 7 PHASES PASSED')
    print('  ClaudeAnalyst   (Phase 1 투자 메모)     -> OK')
    print('  ClaudeExecutor  (Phase 2 JSON 결정)     -> OK')
    print('  VisionAnalyst   (Phase 3 차트, Gemini)  -> OK')
    print('  AIThematicFilter (뉴스 테마 필터)       -> OK')
    print('  AIMacroModule    (블랙스완 감지)        -> OK')
    print('  Sanity Check     (LLM 출력 검증)        -> OK')
    print('=' * 60)

if __name__ == "__main__":
    main()
