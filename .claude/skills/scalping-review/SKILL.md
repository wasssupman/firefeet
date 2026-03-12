---
name: scalping-review
description: >
  스캘핑 거래 리뷰. "스캘핑 분석", "scalping review", "스캘핑 로그" 요청 시 사용.
---

# Scalping Review

## 실행 절차
1. `.claude/rules/scalping.md` 읽고 제약사항 확인
2. MEMORY.md ## Scalping 섹션 확인
3. **scalping-analyzer** 에이전트 스폰 → 로그 분석
4. 분석 결과 기반으로 인사이트 제공
5. 필요 시 **scalping-strategist** 에이전트 스폰 → 파라미터 제안

## 참조
- 기존 trade-review 스킬의 `scripts/analyze_trades.py --strategy scalp` 활용
