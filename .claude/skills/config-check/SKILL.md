# Config Check Skill

트레이딩 봇의 config/*.yaml 설정 파일을 교차 검증하여 실매매 사고를 방지합니다.

## 사용 시점
- "설정 확인", "config check" 요청 시
- 봇 시작 전 안전 점검으로 사용
- YAML 설정 변경 후 검증

## 실행 방법

검증 스크립트를 실행합니다:
```bash
python3 .claude/skills/config-check/scripts/validate_config.py
```

FAIL 항목이 있으면 수정 방법을 구체적으로 안내하세요.

## 핵심 검증 규칙

### 3중 충돌 (최우선)
스캘핑 threshold가 3곳에 분산되어 하나만 수정하면 다른 경로가 덮어쓰는 문제:
1. `scalping_settings.yaml` → `default_confidence_threshold` (글로벌 기본값)
2. `scalping_strategies.yaml` → 전략별 `confidence_threshold` (전략 오버라이드)
3. `scalping_rules.yaml` → `max_loss_pct` vs `stop_loss_pct` 정합성

**우선순위**: 전략(profile) > 온도 오버라이드 > 글로벌 기본값

### 수수료 바닥선
왕복 수수료 ~0.21%. TP가 이 값 이하면 구조적 손실.

## 참조
- @references/config_schema.md — 각 YAML 파일의 필수 키와 값 범위
