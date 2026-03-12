---
name: scalping-strategy
description: >
  스캘핑 전략 분석·튜닝. "스캘핑 전략", "scalping strategy", "파라미터 튜닝" 요청 시 사용.
---

# Scalping Strategy

## 실행 절차
1. `.claude/rules/scalping.md` 읽고 제약사항 확인
2. MEMORY.md ## Scalping 섹션 확인 (특히 "시도하고 실패한 것")
3. **scalping-strategist** 에이전트 스폰 → 전략 분석
4. 필요 시 config-check 스킬 호출 → 설정 정합성 검증
5. 필요 시 **param-tune** 에이전트 스폰 → 파라미터 제안

## 금지
- momentum 관련 전략 제안 금지 (폐기됨)
- 한 번에 3개 초과 파라미터 변경 금지
