import json
import time
import threading
import websocket  # websocket-client library


class KISWebSocket:
    """KIS 실시간 WebSocket 클라이언트 (체결가 + 호가 + 체결통보)"""

    # Field index constants (H0STCNT0 체결가 데이터)
    FIELD_TICK_DIRECTION = 21  # 체결구분 (1:매수, 5:매도)
    FIELD_SELL_COUNT = 15      # 매도체결건수 (체결구분 아님!)
    FIELD_BUY_COUNT = 16       # 매수체결건수
    FIELD_STRENGTH = 18        # 체결강도

    # WebSocket endpoints
    WS_URL_REAL = "ws://ops.koreainvestment.com:21000"
    WS_URL_PAPER = "ws://ops.koreainvestment.com:31000"

    # TR codes
    TR_TICK = "H0STCNT0"      # 실시간 체결가
    TR_ORDERBOOK = "H0STASP0"  # 실시간 호가
    TR_NOTICE = "H0STCNI9"     # 실시간 체결통보 (실전)
    TR_NOTICE_PAPER = "H0STCNI0"  # 실시간 체결통보 (모의)

    def __init__(self, auth, mode="PAPER", hts_id="", max_subscriptions=41):
        self.auth = auth
        self.mode = mode
        self.hts_id = hts_id  # HTS ID for 체결통보
        self.ws_url = self.WS_URL_REAL if mode == "REAL" else self.WS_URL_PAPER
        self.approval_key = None
        self.ws = None
        self._thread = None
        self._running = False
        self._connected = False

        # Subscription management (KIS API max 41)
        self._subscriptions = {}  # {f"{tr_id}|{code}": True}
        self._desired_subscriptions = []  # 재접속 시 복원할 구독 목록
        self._max_subscriptions = max_subscriptions

        # Callbacks: {tr_id: [callback_fn, ...]}
        self._callbacks = {
            self.TR_TICK: [],
            self.TR_ORDERBOOK: [],
            self.TR_NOTICE: [],
            self.TR_NOTICE_PAPER: [],
        }

        # Reconnect
        self._reconnect_delay = 5
        self._max_reconnect_delay = 60

    @property
    def subscription_count(self):
        return len(self._subscriptions)

    def connect(self):
        """WebSocket 접속 시작 (별도 스레드)"""
        self.approval_key = self.auth.get_approval_key()
        if not self.approval_key:
            print("[KISWebSocket] Approval key 발급 실패 — 접속 불가")
            return False

        self._running = True
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

        # Wait for connection (max 10s)
        for _ in range(100):
            if self._connected:
                return True
            time.sleep(0.1)
        print("[KISWebSocket] 접속 타임아웃")
        return False

    def disconnect(self):
        """WebSocket 접속 종료"""
        self._running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self._connected = False
        self._subscriptions.clear()
        print("[KISWebSocket] 접속 종료")

    def _run_forever(self):
        """WebSocket 이벤트 루프 (자동 재접속)"""
        delay = self._reconnect_delay
        while self._running:
            try:
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                print(f"[KISWebSocket] 연결 예외: {e}")

            if self._running:
                print(f"[KISWebSocket] {delay}초 후 재접속...")
                time.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)

    def _on_open(self, ws):
        self._connected = True
        self._reconnect_delay = 5
        # 재접속 시 approval key 재발급 (만료된 키로 구독하면 OPSP0011)
        new_key = self.auth.get_approval_key()
        if new_key:
            self.approval_key = new_key
        print("[KISWebSocket] 접속 완료")
        # Re-subscribe after reconnection (_desired가 우선, 없으면 _subscriptions)
        resub_keys = self._desired_subscriptions or list(self._subscriptions.keys())
        self._subscriptions.clear()
        if resub_keys:
            # KIS 서버: appkey당 세션 1개 제한 → 직전 세션이 정리되기 전에 폭탄처럼
            # 보내면 OPSP8996 재발. 접속 직후 1.5초 대기 후 구독 시작.
            time.sleep(1.5)
            for i, key in enumerate(resub_keys):
                tr_id, code = key.split("|", 1)
                if self._send_subscribe(tr_id, code):
                    self._subscriptions[key] = True
                # 구독 요청 간 100ms 간격 — 서버 레이트리밋 회피
                if i < len(resub_keys) - 1:
                    time.sleep(0.1)
        print(f"[KISWebSocket] 재구독 완료: {self.subscription_count}개")

    def _on_message(self, ws, message):
        """메시지 수신 처리"""
        # Encrypted check (first char check)
        if message[0] in ('0', '1'):
            # Real-time data: "encrypted|tr_id|count|data"
            parts = message.split("|", 3)
            if len(parts) < 4:
                return
            encrypted = parts[0]
            tr_id = parts[1]
            count = parts[2]
            raw_data = parts[3]

            # Parse pipe-delimited data
            if tr_id == self.TR_TICK:
                self._handle_tick(raw_data)
            elif tr_id == self.TR_ORDERBOOK:
                self._handle_orderbook(raw_data)
            elif tr_id in (self.TR_NOTICE, self.TR_NOTICE_PAPER):
                self._handle_notice(raw_data)
        else:
            # JSON response (subscribe/unsubscribe confirmation)
            try:
                data = json.loads(message)
                if data.get("header", {}).get("tr_id") == "PINGPONG":
                    # Respond to PINGPONG
                    ws.send(message)
                    return
                msg_cd = data.get("body", {}).get("msg_cd", "")
                msg1 = data.get("body", {}).get("msg1", "")
                if msg_cd:
                    print(f"[KISWebSocket] 응답: {msg_cd} — {msg1}")
                    # OPSP8996: 동일 appkey 세션 충돌 — 연결이 곧 끊길 것을 미리 인지
                    if msg_cd == "OPSP8996":
                        print("[KISWebSocket] ⚠️ appkey 세션 충돌 감지. 다른 프로세스가 실행 중이거나 "
                              "이전 세션이 서버에서 아직 정리 중입니다. 60초 후 재시도합니다.")
            except json.JSONDecodeError:
                pass

    def _on_error(self, ws, error):
        print(f"[KISWebSocket] 에러: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        self._connected = False
        print(f"[KISWebSocket] 연결 종료 (code={close_status_code}, msg={close_msg})")

    # -- Subscription --

    def subscribe_tick(self, code):
        """체결가 구독"""
        return self._subscribe(self.TR_TICK, code)

    def subscribe_orderbook(self, code):
        """호가 구독"""
        return self._subscribe(self.TR_ORDERBOOK, code)

    def subscribe_notice(self):
        """체결통보 구독"""
        tr_id = self.TR_NOTICE if self.mode == "REAL" else self.TR_NOTICE_PAPER
        return self._subscribe(tr_id, self.hts_id)

    def unsubscribe_tick(self, code):
        """체결가 구독 해제"""
        return self._unsubscribe(self.TR_TICK, code)

    def unsubscribe_orderbook(self, code):
        """호가 구독 해제"""
        return self._unsubscribe(self.TR_ORDERBOOK, code)

    def unsubscribe_all(self):
        """전체 구독 해제"""
        for key in list(self._subscriptions.keys()):
            tr_id, code = key.split("|", 1)
            self._unsubscribe(tr_id, code)

    def _subscribe(self, tr_id, code):
        key = f"{tr_id}|{code}"
        if key in self._subscriptions:
            return True
        if self.subscription_count >= self._max_subscriptions:
            print(f"[KISWebSocket] 구독 한도 초과 ({self._max_subscriptions}개)")
            return False
        if self._send_subscribe(tr_id, code):
            self._subscriptions[key] = True
            return True
        return False

    def _unsubscribe(self, tr_id, code):
        key = f"{tr_id}|{code}"
        if key not in self._subscriptions:
            return True
        if self._send_unsubscribe(tr_id, code):
            self._subscriptions.pop(key, None)
            return True
        return False

    def _send_subscribe(self, tr_id, code):
        return self._send_request(tr_id, code, "1")  # 1: subscribe

    def _send_unsubscribe(self, tr_id, code):
        return self._send_request(tr_id, code, "2")  # 2: unsubscribe

    def _send_request(self, tr_id, code, tr_type):
        if not self._connected or not self.ws:
            return False
        msg = {
            "header": {
                "approval_key": self.approval_key,
                "custtype": "P",
                "tr_type": tr_type,
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": tr_id,
                    "tr_key": code,
                }
            }
        }
        try:
            self.ws.send(json.dumps(msg))
            return True
        except Exception as e:
            print(f"[KISWebSocket] 전송 실패: {e}")
            return False

    # -- Callback Registration --

    def on_tick(self, callback):
        """체결가 콜백 등록: callback(tick_data)"""
        self._callbacks[self.TR_TICK].append(callback)

    def on_orderbook(self, callback):
        """호가 콜백 등록: callback(orderbook_data)"""
        self._callbacks[self.TR_ORDERBOOK].append(callback)

    def on_notice(self, callback):
        """체결통보 콜백 등록: callback(notice_data)"""
        tr_id = self.TR_NOTICE if self.mode == "REAL" else self.TR_NOTICE_PAPER
        self._callbacks[tr_id].append(callback)

    # -- Data Parsing --

    def _handle_tick(self, raw):
        """체결가 데이터 파싱 (H0STCNT0, pipe-delimited ~40 fields)"""
        fields = raw.split("^")
        if len(fields) < 40:
            return

        tick_data = {
            "code": fields[0],            # 종목코드
            "time": fields[1],            # 체결시간 (HHMMSS)
            "price": int(fields[2]),       # 현재가
            "change_sign": fields[3],      # 전일 대비 부호
            "change": int(fields[4]),      # 전일 대비
            "change_rate": float(fields[5]),  # 전일 대비율
            "weighted_avg": float(fields[6]) if fields[6] else 0,  # 가중평균가
            "open": int(fields[7]),        # 시가
            "high": int(fields[8]),        # 고가
            "low": int(fields[9]),         # 저가
            "ask_price": int(fields[10]),  # 매도호가1
            "bid_price": int(fields[11]),  # 매수호가1
            "volume": int(fields[12]),     # 체결량
            "acml_volume": int(fields[13]),  # 누적거래량
            "acml_amount": int(fields[14]),  # 누적거래대금
            "sell_count": int(fields[15]),   # 매도체결건수
            "buy_count": int(fields[16]),    # 매수체결건수
            "strength": float(fields[18]) if fields[18] else 0,  # 체결강도
            "tick_direction": fields[21],    # 체결구분 (1:매수, 5:매도)
        }

        for cb in self._callbacks.get(self.TR_TICK, []):
            try:
                cb(tick_data)
            except Exception as e:
                print(f"[KISWebSocket] 체결가 콜백 에러: {e}")

    def _handle_orderbook(self, raw):
        """호가 데이터 파싱 (H0STASP0, pipe-delimited)"""
        fields = raw.split("^")
        if len(fields) < 50:
            return

        # 매도 10단계 + 매수 10단계 파싱
        orderbook_data = {
            "code": fields[0],
            "time": fields[1],
            "ask_prices": [],   # 매도호가 1~10 (낮은 가격부터)
            "ask_volumes": [],  # 매도잔량 1~10
            "bid_prices": [],   # 매수호가 1~10 (높은 가격부터)
            "bid_volumes": [],  # 매수잔량 1~10
            "total_ask_volume": 0,
            "total_bid_volume": 0,
        }

        # Fields layout: 매도호가10~1 (idx 3~12), 매수호가1~10 (idx 13~22)
        # 매도잔량10~1 (idx 23~32), 매수잔량1~10 (idx 33~42)
        try:
            for i in range(10):
                orderbook_data["ask_prices"].append(int(fields[3 + i]))
                orderbook_data["bid_prices"].append(int(fields[13 + i]))
                orderbook_data["ask_volumes"].append(int(fields[23 + i]))
                orderbook_data["bid_volumes"].append(int(fields[33 + i]))

            orderbook_data["total_ask_volume"] = int(fields[43]) if len(fields) > 43 else sum(orderbook_data["ask_volumes"])
            orderbook_data["total_bid_volume"] = int(fields[44]) if len(fields) > 44 else sum(orderbook_data["bid_volumes"])
        except (ValueError, IndexError) as e:
            print(f"[KISWebSocket] 호가 파싱 에러: {e}")
            return

        for cb in self._callbacks.get(self.TR_ORDERBOOK, []):
            try:
                cb(orderbook_data)
            except Exception as e:
                print(f"[KISWebSocket] 호가 콜백 에러: {e}")

    def _handle_notice(self, raw):
        """체결통보 파싱 (H0STCNI0/9)"""
        fields = raw.split("^")
        if len(fields) < 15:
            return

        notice_data = {
            "code": fields[1],            # 종목코드
            "order_no": fields[2],        # 주문번호
            "order_type": fields[4],      # 매수/매도 (02:매수, 01:매도)
            "order_status": fields[6],    # 주문상태
            "price": int(fields[7]) if fields[7] else 0,  # 체결단가
            "qty": int(fields[8]) if fields[8] else 0,    # 체결수량
        }

        tr_id = self.TR_NOTICE if self.mode == "REAL" else self.TR_NOTICE_PAPER
        for cb in self._callbacks.get(tr_id, []):
            try:
                cb(notice_data)
            except Exception as e:
                print(f"[KISWebSocket] 체결통보 콜백 에러: {e}")

    # -- Subscription Rotation --

    def rotate_subscriptions(self, priority_codes, tick_slots=10, orderbook_slots=5):
        """
        우선순위 기반 구독 로테이션.
        priority_codes: 우선순위순 종목 코드 리스트
        기존 구독 중 우선순위 밖 종목 해제 -> 새 종목 구독
        """
        target_tick = priority_codes[:tick_slots]
        target_ob = priority_codes[:orderbook_slots]

        # 재접속 시 복원용 목록을 먼저 저장 (연결 성공 여부와 무관하게 '의도한' 구독 목록으로)
        # 버그 수정: 이전 코드는 실제 _subscriptions 성공 목록으로 덮어써서
        # 단절 중 호출 시 빈 목록이 저장되어 재접속 후 구독 복원 실패했음
        desired = []
        for code in target_tick:
            desired.append(f"{self.TR_TICK}|{code}")
        for code in target_ob:
            desired.append(f"{self.TR_ORDERBOOK}|{code}")
        self._desired_subscriptions = desired

        # 단절 중이면 목록 저장만 하고 실제 구독 변경 없이 반환
        if not self._connected:
            print(f"[KISWebSocket] WS 미연결 — 구독 목록 저장됨 (재접속 시 자동 복원): "
                  f"체결 {len(target_tick)}개, 호가 {len(target_ob)}개")
            return

        # 현재 체결가/호가 구독 종목 추출
        current_tick_codes = []
        current_ob_codes = []
        for key in self._subscriptions:
            tr_id, code = key.split("|", 1)
            if tr_id == self.TR_TICK:
                current_tick_codes.append(code)
            elif tr_id == self.TR_ORDERBOOK:
                current_ob_codes.append(code)

        # 해제: 우선순위 밖 종목
        for code in current_tick_codes:
            if code not in target_tick:
                self.unsubscribe_tick(code)
        for code in current_ob_codes:
            if code not in target_ob:
                self.unsubscribe_orderbook(code)

        # 신규 구독
        for code in target_tick:
            if code not in current_tick_codes:
                self.subscribe_tick(code)
        for code in target_ob:
            if code not in current_ob_codes:
                self.subscribe_orderbook(code)

        print(f"[KISWebSocket] 구독 로테이션 완료: 체결 {len(target_tick)}개, 호가 {len(target_ob)}개 "
              f"(총 {self.subscription_count}/{self._max_subscriptions})")
