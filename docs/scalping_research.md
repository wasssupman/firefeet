# 스캘핑 전략 리서치 — 유명 트레이더 & 커뮤니티 검증 기법

> 작성일: 2026-02-19
> 목적: 현재 Firefeet 스캘핑 엔진 개선을 위한 외부 전략 벤치마킹

---

## 1. 유명 트레이더 전략

### 1.1 Ross Cameron (Warrior Trading) — 모멘텀 스캘핑

스몰캡·로우플로트 종목의 모멘텀을 초단기 캐치하는 전략.

**종목 선정 3필터**

| 기준 | 조건 |
|------|------|
| 차트 구조 | 이평선 위, 근거리 저항 없음 |
| RVOL | 일평균 대비 **2배 이상** |
| 카탈리스트 | 공시, 실적, 뉴스 등 실체 있는 재료 |

**1분봉 스캘핑 규칙**
- EMA 9/20 크로스오버 + VWAP 위에서만 롱
- 진입: 눌림목 반등 확인 후 즉시
- 손절: 직전 저점 하향 이탈 시 즉시 청산
- 목표: "Buy the dip, Sell the rip" — 첫 번째 모멘텀 레그 청산

**Firefeet 적용 시사점**
- 현재 스캐너에 RVOL 2배 필터 없음 → `screener_settings.yaml`에 `min_rvol: 2.0` 추가 검토
- 1분봉 캔들 기반 EMA 크로스 시그널 추가 검토

---

### 1.2 Timothy Sykes — 패턴 기반 페이드 전략

급등 후 되돌림(fade)을 노리는 숏·롱 혼합 전략.

**핵심 패턴 — Supernova**
```
갭상승 + 거래량 폭발 → 초기 모멘텀 롱
→ 상승 둔화 + 거래량 감소 → 페이드 진입 (되돌림 캐치)
```

**원칙**
- 빠른 손절 최우선 — 페니스탁은 급락 속도가 극히 빠름
- 거래량 소멸 확인 후 진입 → 거래량 없는 가격 이동은 신뢰 불가
- 포지션 보유 단위: 수분~수십분 (장기 보유 금지)

**Firefeet 적용 시사점**
- 현재 `VWAP Reversion` 시그널이 이 개념과 유사하나, **거래량 소멸 조건**이 빠져있음
- `signal_volume_surge`를 페이드 진입 시 역방향으로 활용 검토

---

### 1.3 Momo Traders / Chat with Traders 커뮤니티

**공통 설정**
- 1분봉 + EMA 9/20 크로스오버 — 스캘핑 최범용 조합
- 거래량 급증 확인 필수 (거래량 없는 돌파는 신뢰 불가)
- **일간 목표금액** 미리 설정 → 목표 달성 시 당일 거래 완전 중단

**한국 단타 커뮤니티 (주식갤, 클리앙, 나무위키) 검증 원칙**

| 원칙 | 내용 |
|------|------|
| 장 초반 집중 | 09:00~09:30이 거래량 최다, 이후 감소 |
| 동시호가 주의 | 08:50 이전 호가는 허수 비율 높음 — 08:55 이후 진짜 호가 확인 |
| 거래대금 기준 | 10분봉 거래대금 **50억 원 이상** 종목만 진입 |
| 갭상승 돌파 지양 | 이미 저항 돌파한 종목 진입 회피 — 쫓아가기 금지 |
| 손절 최우선 | 미리 설정한 손절선 이탈 시 감정 배제하고 즉시 컷 |

---

## 2. 기술적 지표 기반 기법

### 2.1 VWAP 활용 — Bounce vs Rejection

**VWAP Bounce (추세 지속장)**
```
조건:
  1. 현재가 VWAP 위 (강세 바이어스)
  2. 가격이 VWAP까지 눌림목
  3. VWAP 근처에서 핀바 캔들 + 거래량 증가
  4. 롱 진입 → VWAP 아래 이탈 시 즉시 손절
  목표: 직전 고점 또는 R:R 1:1.5
```

**VWAP Rejection (박스권/역추세장)**
```
조건:
  1. 현재가 VWAP 아래 (약세 바이어스)
  2. 가격이 VWAP까지 반등
  3. VWAP 저항에서 음봉 + 매도 거래량 증가
  4. 숏 진입 → VWAP 돌파 시 즉시 손절
```

**현재 Firefeet 구현 vs 권장 개선**

| 항목 | 현재 | 권장 |
|------|------|------|
| VWAP 거리 기준 | -0.3% 이상 이탈 시 시그널 | VWAP Bounce는 바이어스 방향 확인 후 진입 |
| 거래량 확인 | `vol_accel` 단독 사용 | VWAP 근처 캔들 패턴 + 거래량 조합 |
| 타임프레임 | 틱 단위 | 1분봉 VWAP 기준으로 전환 검토 |

---

### 2.2 오더북 분석 — Iceberg Order & Spoofing

**Iceberg Order (빙산 주문) 식별**

대형 기관이 수량을 숨기고 일부만 노출하는 주문.

| 신호 | 설명 |
|------|------|
| 체결량 > 호가 노출량 | 호가에 500주 표시 → 650주 체결 → 숨겨진 물량 존재 |
| 리필(refill) 반복 | 같은 가격에 주문이 계속 보충됨 |
| 대량 체결 후 가격 불변 | 강한 지지/저항 존재 신호 |

스캘핑 활용: 빙산 주문 확인된 가격대 = 강한 지지/저항 → 손절 기준으로 활용

**Spoofing (허위 주문) 대응**
```
패턴: 대량 호가 출현 → 가격 접근 시 사라짐 (반복)
의미: 방향 조작 시도
대응: 사라진 방향으로 진입 검토 (역방향 모멘텀)
```

**Firefeet 적용 시사점**
- 현재 `OrderbookAnalyzer`가 불균형(imbalance)만 분석
- Iceberg 탐지: 체결량 vs 호가 노출량 비교 로직 추가 필요
- Spoofing 탐지: 단시간 내 대량 호가 출현→소멸 패턴 감지 검토

---

### 2.3 테이프 리딩 (Time & Sales)

체결 내역 실시간 스트림으로 기관 개입 감지.

| 신호 | 의미 |
|------|------|
| 대량 체결 출현 | 기관/세력 개입 |
| 연속 상향 체결 | 공격적 매수 → 단기 상승 모멘텀 |
| 연속 하향 체결 | 공격적 매도 → 단기 하락 모멘텀 |
| 테이프 속도 급증 | 변동성 폭발 직전 |
| 거래량 없는 가격 이동 | 신뢰도 낮음 — 진입 보류 |

**원칙**: 차트로 셋업 식별 → 테이프로 진입/청산 타이밍 정밀 조정

**Firefeet 적용**: 현재 틱 방향(1/-1/0) 집계 → 체결 크기별 가중치 추가로 정확도 향상 가능

---

### 2.4 Opening Range Breakout (ORB)

**설정별 특성**

| ORB 단위 | 장점 | 단점 |
|----------|------|------|
| 1분 ORB (09:00~09:01) | 신호 많음 | 허위 돌파 많음 |
| 5분 ORB (09:00~09:05) | 범용 균형 | — |
| 15분 ORB (09:00~09:15) | 안정적 | 신호 적음 |

**진입 조건**
```
1. 레인지 고점 위 캔들 종가 클로즈 (롱)
2. 돌파 시 RVOL 1.5 이상 동반
3. 직전 5~10봉 대비 거래량 증가 확인
4. 일봉 추세 방향 일치 여부 확인
손절: 레인지 반대편
목표: 레인지 폭의 1~2배
```

**Firefeet 적용 시사점**
- 장 시작 후 5분간 레인지 형성 → 돌파 시 변동성 돌파 k값 조합 가능
- 현재 변동성 돌파가 전일 레인지 기반인데, ORB(당일 초반 레인지)를 보조 시그널로 추가 검토

---

## 3. Reddit 커뮤니티 검증 전략

### 3.1 r/Daytrading 공통 합의

**가장 많이 검증된 조합**
- 3~5분봉 스캘핑 + ORB
- 지표: MACD(5,15,1) + EMA 9/200 + VWAP + RSI + 볼린저밴드

**실전 사례 (The1Matthan)**
- 조건: 고거래량 + 뉴스 카탈리스트 종목 집중
- 결과: 2023년 승률 71%, 수익:손실 = 77:23

---

### 3.2 손익비 (R:R) 권장값

| 전략 유형 | R:R | 필요 최소 승률 |
|-----------|-----|---------------|
| 순수 스캘핑 | 1:1 | 55%+ (수수료 감안) |
| 모멘텀 스캘핑 | 1:1.5 | 40%+ |
| 스윙 혼합 | 1:2+ | 34%+ |

**한국 주식 수수료 현실**
- 왕복 수수료: ~0.21%
- TP 0.5%면 실질 이익: 0.29% → 손익분기 승률이 매우 높아야 함
- **TP는 최소 수수료의 3배 이상(0.63%+) 권장**

**현재 Firefeet 문제**
```
NEUTRAL 모드: TP 1.0%, SL -0.5%
실질 TP: 0.79%, 실질 SL: -0.71%
R:R ≈ 1:1.1 → 승률 최소 48% 필요
현재 승률: 0% (6/6 손실) ← SCALP_SELL_SIGNAL로 TP/SL 도달 전 청산
```

---

### 3.3 진입/청산 타이밍 원칙

**진입**
- 셋업 확인 후 즉시 실행 (완벽한 진입 기다리다 기회 놓치지 말 것)
- 진입 전 손절가 반드시 확정 — 감정 개입 차단

**청산**
- TP 도달 즉시 전량 또는 부분 청산
- SL 이탈 시 이유 불문 즉시 청산 (재검토 금지)
- 트레일링 스탑으로 모멘텀 지속 시 수익 극대화

---

## 4. 시간대별 전략 (KST 기준)

| 시간대 | 특성 | 권장 전략 |
|--------|------|-----------|
| 08:50~09:00 | 동시호가 — 허수 주문 다수 | 관찰만. 09:00 이후 진입 |
| **09:00~09:30** | 거래량 최대, 변동성 최고 | **모멘텀 스캘핑 황금 시간대** |
| 09:30~10:30 | 변동성 안정화, 추세 결정 | ORB 전략, 추세 추종 |
| 10:30~12:00 | 거래량 감소, 횡보 증가 | VWAP 리버전 (선택적) |
| **12:00~13:30** | 거래량 최저 "죽음의 구간" | **신규 진입 자제/중단** |
| 13:30~14:30 | 거래량 소폭 회복 | 뉴스/수급 확인 후 선택적 |
| **14:30~15:20** | 거래량 재급증, 마감 정리 | **2차 황금 시간대** |
| 15:20~15:30 | 마감 동시호가 | 신규 진입 금지 |

**현재 Firefeet 문제**: `no_entry_after: "1525"` — 점심 구간 필터링 없음

---

## 5. 리스크 관리 표준

### 5.1 손실 한도 기준

| 구분 | 기준 | Firefeet 현재 |
|------|------|--------------|
| 일간 최대 손실 | 계좌의 2~3% | **제한 해제 (999,999원)** |
| 개별 거래 손실 | 계좌의 0.5~1% | **제한 해제 (99%)** |
| 연속 손실 서킷브레이커 | 3~5회 | **해제 (999회)** |

→ **모의투자 용으로 제한 해제된 상태. 실매매 전환 시 반드시 재설정 필요**

### 5.2 재진입 룰

**허용**
- 동일 방향 새 셋업 형성 시
- 직전 손절 후 **최소 5~10분** 경과
- 시장 구조(지지/저항)가 여전히 유효

**금지**
- 손절 직후 감정적 복수 매매 (Revenge Trade)
- 일간 손실 한도 도달 후
- 같은 가격대 3회 연속 손절 → 구조 재분석 필요
- 점심 구간(12:00~13:30) 억지 진입

**현재 Firefeet 문제**: 쿨다운 없이 청산 직후 즉시 재매수 가능 — 한온시스템 사례에서 실제로 발생

---

## 6. Firefeet 스캘핑 개선 우선순위

리서치 결과를 현재 코드 문제와 연결한 개선 방향.

### 우선순위 HIGH

| 문제 | 원인 | 권장 수정 |
|------|------|-----------|
| `SCALP_SELL_SIGNAL` 100% | 시그널 반전 임계값(composite<30)이 너무 높음 | `should_exit` confidence_threshold를 0.30→0.15로 낮추거나, 최소 보유시간 10s→30s로 연장 |
| 진입 임계값 너무 낮음 | `confidence_threshold: 0.30` | 0.40~0.50으로 상향 — 낮은 신뢰도 종목 걸러내기 |
| 즉시 재매수 | 쿨다운 없음 | 손절 후 해당 종목 최소 5분 재진입 금지 |
| 수수료 대비 TP 부족 | TP가 수수료의 2~3배 수준 | TP 최소 1.0% 이상 (수수료의 5배) 고정 권장 |

### 우선순위 MEDIUM

| 개선 항목 | 내용 |
|-----------|------|
| 점심 구간 진입 차단 | 12:00~13:30 `no_entry_before/after`로 차단 |
| RVOL 필터 | 스캐너에 일평균 대비 2배 이상 필터 추가 |
| 거래대금 기준 | 10분봉 거래대금 50억 이상 조건 추가 |
| ORB 보조 시그널 | 장 시작 후 5분 레인지 돌파 여부 확인 시그널 추가 |

### 우선순위 LOW

| 개선 항목 | 내용 |
|-----------|------|
| Iceberg 탐지 | 체결량 vs 호가 노출량 비교로 숨겨진 매물 감지 |
| 테이프 리딩 강화 | 체결 크기별 가중치 적용 (대량 체결 > 소량 체결) |
| 시간대별 파라미터 | 09:00~09:30은 공격적, 10:30~12:00은 보수적 자동 전환 |
| EMA 크로스 시그널 | 1분봉 EMA 9/20 크로스오버 추가 (Ross Cameron 기법) |

---

## 참고 출처

- [Warrior Trading - Simple Scalping Strategy](https://www.warriortrading.com/the-simple-scalping-strategy-for-day-trading/)
- [Warrior Trading - 1-Minute Scalping Strategy](https://www.warriortrading.com/1-minute-scalping-strategy/)
- [Warrior Trading - Opening Range Breakout](https://www.warriortrading.com/opening-range-breakout/)
- [Timothy Sykes - Tape Reading](https://www.timothysykes.com/blog/tape-reading/)
- [VWAP Bounce + Rejection - Finveroo](https://www.finveroo.com/trading-academy/strategies/volume/vwap-bounce/)
- [Humbled Trader - VWAP Strategy](https://www.humbledtrader.com/blog/vwap-strategy-secrets-boosting-your-trading-skills-to-the-next-level/)
- [Bookmap - Iceberg Orders & Order Flow](https://bookmap.com/blog/advanced-order-flow-trading-spotting-hidden-liquidity-iceberg-orders)
- [StocksToTrade - Tape Reading Guide](https://stockstotrade.com/tape-reading/)
- [LuxAlgo - ORB Trading Strategy](https://www.luxalgo.com/blog/opening-range-breakout-orb-trading-strategy-how-it-works/)
- [Trade That Swing - Win Rate vs R:R](https://tradethatswing.com/win-rate-risk-reward-and-finding-the-profitable-balance/)
- [Trade That Swing - Daily Loss Limit](https://tradethatswing.com/setting-a-daily-loss-limit-when-day-trading/)
- [Brooks Trading Course - Rules for Scalping](https://www.brookstradingcourse.com/trading-strategies/rules-for-scalping/)
- [Reddit Scalping Strategy Insights](https://elevatingforex.com/scalping-strategy-reddit/)
- [나무위키 - 주식투자/단타매매 기법](https://namu.wiki/w/%EC%A3%BC%EC%8B%9D%ED%88%AC%EC%9E%90/%EB%8B%A8%ED%83%80%EB%A7%A4%EB%A7%A4%20%EA%B8%B0%EB%B2%95)
- [전고점 돌파 매매 기법 - Brunch](https://brunch.co.kr/@bjbw/9)
