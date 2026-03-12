#!/usr/bin/env node
import { readFileSync } from 'fs';

const BOTS = {
  scalping: {
    keywords: ['스켈핑', '스캘핑', 'scalp', 'vwap', 'reversion', 'tick_buffer',
               'regime', 'momentum_burst', 'ScalpEngine', 'scalp_signal'],
    context: `[SCALPING CONTEXT]
FORBIDDEN: momentum 시그널 폐기됨 (386건 분석, 엣지 없음). 재활성화 금지.
FORBIDDEN: check_buy_signal()은 변동성 돌파 전용.
ACTIVE: VWAP Deviation Reversion 단독.
THRESHOLD: 3곳 충돌. 우선순위: 전략 프로필 > 온도 > 글로벌.
→ .claude/rules/scalping.md 참조`
  },
  swing: {
    keywords: ['스윙', 'swing', 'SwingTrader', 'ai_swing', 'overnight', '오버나잇'],
    context: `[SWING CONTEXT]
FORBIDDEN: check_buy_signal()/should_sell() EOD는 데이트레이딩 전용.
FORBIDDEN: ScalpSignals/ScalpEngine은 스캘핑 전용.
NOTE: SwingTrader는 FirefeetTrader 상속하나 진입/청산 완전 오버라이드.
NOTE: AI 모드 현재 비활성 (2026-03-11).
→ .claude/rules/swing.md 참조`
  },
  volatility: {
    keywords: ['변동성', 'volatility', 'breakout', 'FirefeetTrader',
               'check_buy_signal', 'should_sell', 'EOD', 'run_firefeet'],
    context: `[VOLATILITY CONTEXT]
NOTE: 당일 15:20 EOD 강제 청산. 오버나잇 금지.
NOTE: trader.py 변경 시 SwingTrader 상속 영향 확인 필수.
FORBIDDEN: VWAP/orderbook/tick_buffer는 스캘핑 전용.
→ .claude/rules/volatility.md 참조`
  }
};

try {
  const input = JSON.parse(readFileSync('/dev/stdin', 'utf8'));
  const prompt = (input.prompt || '').toLowerCase();

  for (const [name, bot] of Object.entries(BOTS)) {
    if (bot.keywords.some(kw => prompt.includes(kw.toLowerCase()))) {
      console.log(bot.context);
      break; // 한 봇만 매칭
    }
  }
} catch {}
