# Trade Review Skill

거래 로그 CSV를 분석하여 정량적 성과 리포트를 생성합니다.

## 사용 시점
- "거래 분석", "성과 리뷰", "trade review" 요청 시
- 기간/봇 타입 미지정 시 최근 7일 + 전체 봇 기본값 사용

## 실행 방법

분석 스크립트를 실행합니다:
```bash
python3 .claude/skills/trade-review/scripts/analyze_trades.py [--days N] [--strategy scalp|swing|main]
```

스크립트 출력을 기반으로 추가 인사이트와 파라미터 조정 제안을 덧붙이세요.

## 참조
- @references/csv_format.md — CSV 컬럼 설명 및 수수료 구조
