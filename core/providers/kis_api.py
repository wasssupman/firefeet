import requests
import json
import enum
import datetime
import time
import pandas as pd

class OrderType(enum.Enum):
    BUY = "2"
    SELL = "1"

class KISManager:
    def __init__(self, auth, account_info, mode="PAPER"):
        self.auth = auth
        self.cano = account_info["CANO"]
        self.acnt_prdt_cd = account_info["ACNT_PRDT_CD"]
        self.mode = mode
        self.url_base = auth.url_base

    def _request(self, method, url, tr_id, hashkey=None, **kwargs):
        """API 요청 + 401/토큰만료 시 갱신 후 1회 재시도, 속도제한 시 대기"""
        import time as _time
        headers = self.auth.get_headers(tr_id=tr_id)
        if hashkey:
            headers["hashkey"] = hashkey
        res = requests.request(method, url, headers=headers, **kwargs)

        # 속도제한 (초당 거래건수 초과) — 토큰 문제가 아님, 대기 후 재시도
        if res.status_code == 500:
            body = res.text[:300]
            if "EGW00201" in body:
                print(f"[KISManager] 속도 제한 — 1초 대기 후 재시도")
                _time.sleep(1)
                res = requests.request(method, url, headers=headers, **kwargs)
            elif "EGW00123" in body:
                # 토큰 만료 — 갱신 후 재시도
                print(f"[KISManager] 토큰 만료 — 갱신 후 재시도")
                self.auth.invalidate_token()
                headers = self.auth.get_headers(tr_id=tr_id)
                if hashkey:
                    headers["hashkey"] = hashkey
                res = requests.request(method, url, headers=headers, **kwargs)
            else:
                print(f"[KISManager] 500 응답: {body}")

        if res.status_code == 401:
            print(f"[KISManager] 401 — 토큰 갱신 후 재시도")
            self.auth.invalidate_token()
            headers = self.auth.get_headers(tr_id=tr_id)
            if hashkey:
                headers["hashkey"] = hashkey
            res = requests.request(method, url, headers=headers, **kwargs)

        res.raise_for_status()
        return res.json()

    def get_daily_ohlc(self, code):
        """
        Fetches daily OHLC data (30 days).
        Returns a DataFrame with columns: date, open, high, low, close, volume.
        """
        path = "uapi/domestic-stock/v1/quotations/inquire-daily-price"
        url = f"{self.url_base}/{path}"

        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": code,
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "1" # Adjusted Price
        }

        try:
            data = self._request("GET", url, "FHKST01010400", params=params)

            if data['rt_cd'] != '0':
                print(f"[KISManager] API Error: {data['msg1']}")
                return None

            items = []
            for item in data['output']:
                items.append({
                    "date": item['stck_bsop_date'],
                    "open": int(item['stck_oprc']),
                    "high": int(item['stck_hgpr']),
                    "low": int(item['stck_lwpr']),
                    "close": int(item['stck_clpr']),
                    "volume": int(item['acml_vol'])
                })

            df = pd.DataFrame(items)
            if not df.empty and 'date' in df.columns:
                df = df.sort_values('date', ascending=False).reset_index(drop=True)
            return df
        except Exception as e:
            print(f"[KISManager] Failed to fetch daily OHLC for {code}: {e}")
            return None

    def get_current_price(self, code):
        """
        Fetches the current price of a stock.
        code: Stock code (e.g., "005930" for Samsung Electronics)
        """
        path = "uapi/domestic-stock/v1/quotations/inquire-price"
        url = f"{self.url_base}/{path}"

        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": code
        }

        try:
            data = self._request("GET", url, "FHKST01010100", params=params)

            return {
                "code": code,
                "price": int(data['output']['stck_prpr']),
                "change": int(data['output']['prdy_vrss']),
                "change_rate": float(data['output'].get('prdy_ctrt', 0)),
                "volume": int(data['output']['acml_vol']),
                "high": int(data['output'].get('stck_hgpr', 0)),
            }
        except Exception as e:
            print(f"[KISManager] Failed to fetch price for {code}: {e}")
            return None

    def get_investor_trend(self, code, _retried=False):
        """
        Fetches daily investor trading trend (Individual, Foreigner, Institution).
        code: Stock code (e.g., "005930")
        """
        path = "uapi/domestic-stock/v1/quotations/inquire-investor"
        url = f"{self.url_base}/{path}"

        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": code
        }

        def safe_int(val):
            try:
                if val is None or val == '': return 0
                return int(val)
            except (ValueError, TypeError):
                return 0

        try:
            data = self._request("GET", url, "FHKST01010900", params=params)

            if data['rt_cd'] != '0':
                print(f"[KISManager] API Error: {data['msg1']}")
                return None

            # Process output
            records = []
            for item in data['output']:
                records.append({
                    "date": item['stck_bsop_date'],
                    "price": safe_int(item['stck_clpr']),
                    "individual": safe_int(item['prsn_ntby_qty']), # 개인 순매수
                    "foreigner": safe_int(item['frgn_ntby_qty']), # 외국인 순매수
                    "institution": safe_int(item['orgn_ntby_qty']), # 기관 순매수
                })

            return pd.DataFrame(records)

        except Exception as e:
            print(f"[KISManager] Failed to fetch data: {e}")
            return None

    def get_balance(self):
        """
        Fetches the account balance and holdings.
        """
        path = "uapi/domestic-stock/v1/trading/inquire-balance"
        url = f"{self.url_base}/{path}"

        # Determine TR_ID based on mode
        tr_id = "VTTC8434R" if self.mode == "PAPER" else "TTTC8434R"

        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }

        try:
            data = self._request("GET", url, tr_id, params=params)

            if 'output1' not in data:
                print(f"[KISManager] Balance API Error: {data}")
                return None

            holdings = []
            for item in data['output1']:
                if int(item['hldg_qty']) > 0:
                    holdings.append({
                        "code": item['pdno'],
                        "name": item['prdt_name'],
                        "qty": int(item['hldg_qty']),
                        "orderable_qty": int(item.get('ord_psbl_qty', item['hldg_qty'])),
                        "buy_price": float(item.get('pchs_avg_pric', 0)),
                        "current_price": int(item.get('prpr', 0)),
                        "profit_rate": float(item['evlu_pfls_rt'])
                    })

            return {
                "total_asset": int(data['output2'][0]['tot_evlu_amt']),
                "deposit": int(data['output2'][0]['dnca_tot_amt']),
                "holdings": holdings
            }
        except Exception as e:
            print(f"[KISManager] Failed to fetch balance: {e}")
            return None

    def place_order(self, code, qty, price, order_type):
        """
        Places a buy or sell order.
        order_type: OrderType.BUY or OrderType.SELL
        price: "0" for Market Price (시장가), otherwise specific price
        """
        path = "uapi/domestic-stock/v1/trading/order-cash"
        url = f"{self.url_base}/{path}"

        # Determine TR_ID based on mode and order type
        if self.mode == "PAPER":
            tr_id = "VTTC0802U" if order_type == OrderType.BUY else "VTTC0801U"
        else:
            tr_id = "TTTC0802U" if order_type == OrderType.BUY else "TTTC0801U"

        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": code,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price)
        }
        if int(price) == 0:
            body["ORD_DVSN"] = "01" # Market Price
            body["ORD_UNPR"] = "0"
        else:
            body["ORD_DVSN"] = "00" # Limit Price

        # POST 요청용 hashkey 생성
        hashkey = self.auth.get_hashkey(body)

        try:
            data = self._request("POST", url, tr_id, hashkey=hashkey, data=json.dumps(body))

            if data['rt_cd'] != '0':
                print(f"[KISManager] Order Failed: {data['msg1']}")
                return None

            # ODNO = 실제 주문번호, KRX_FWDG_ORD_ORGNO = 거래소 위탁번호 (모의투자에서 항상 00950)
            return data['output'].get('ODNO') or data['output']['KRX_FWDG_ORD_ORGNO']
        except Exception as e:
            print(f"[KISManager] Order API failed for {code}: {e}")
            return None

    def cancel_order(self, order_no, code, qty):
        """미체결 주문 취소"""
        path = "uapi/domestic-stock/v1/trading/order-rvsecncl"
        url = f"{self.url_base}/{path}"

        tr_id = "VTTC0803U" if self.mode == "PAPER" else "TTTC0803U"

        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": str(order_no),
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",  # 02: 취소
            "ORD_QTY": str(qty),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }

        hashkey = self.auth.get_hashkey(body)

        try:
            data = self._request("POST", url, tr_id, hashkey=hashkey, data=json.dumps(body))
            if data['rt_cd'] != '0':
                print(f"[KISManager] 주문 취소 실패: {data['msg1']}")
                return None
            return data['output'].get('KRX_FWDG_ORD_ORGNO')
        except Exception as e:
            print(f"[KISManager] 주문 취소 API 실패 ({order_no}): {e}")
            return None

    def get_order_status(self, order_date=None):
        """당일 주문 내역 조회 (미체결 확인용)"""
        path = "uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        url = f"{self.url_base}/{path}"

        if order_date is None:
            order_date = datetime.date.today().strftime("%Y%m%d")

        tr_id = "VTTC8001R" if self.mode == "PAPER" else "TTTC8001R"

        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "INQR_STRT_DT": order_date,
            "INQR_END_DT": order_date,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        try:
            data = self._request("GET", url, tr_id, params=params)
            if data.get('rt_cd') != '0':
                print(f"[KISManager] 주문내역 조회 실패: {data.get('msg1')}")
                return []
            return data.get('output1', [])
        except Exception as e:
            print(f"[KISManager] 주문내역 조회 API 실패: {e}")
            return []

    @staticmethod
    def get_tick_size(price):
        """가격대별 호가단위 반환 (KRX 규정)"""
        if price < 2000:
            return 1
        elif price < 5000:
            return 5
        elif price < 20000:
            return 10
        elif price < 50000:
            return 50
        elif price < 200000:
            return 100
        elif price < 500000:
            return 500
        else:
            return 1000

    def round_to_tick(self, price, direction="down"):
        """가격을 호가단위로 반올림/내림"""
        tick = self.get_tick_size(price)
        if direction == "up":
            return ((price + tick - 1) // tick) * tick
        else:
            return (price // tick) * tick

    def get_top_volume_stocks(self, limit=10, min_price=1000):
        """KIS 거래량순위 API (KOSPI + KOSDAQ 병합)"""
        kospi = self._get_volume_rank("0001", limit=limit*2, min_price=min_price)
        time.sleep(0.5)
        kosdaq = self._get_volume_rank("1001", limit=limit*2, min_price=min_price)
        
        merged = kospi + kosdaq
        merged.sort(key=lambda s: s['volume'], reverse=True)
        return merged[:limit]

    def _get_volume_rank(self, iscd, limit=30, min_price=1000):
        """KIS 거래량순위 API 단일 시장 호출"""
        path = "uapi/domestic-stock/v1/quotations/volume-rank"
        url = f"{self.auth.url_base}/{path}"
        tr_id = "FHPST01710000"
        
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20171",
            "fid_input_iscd": iscd,
            "fid_div_cls_code": "0",
            "fid_blng_cls_code": "0",
            "fid_trgt_cls_code": "111111111",
            "fid_trgt_exls_cls_code": "000000",
            "fid_input_price_1": str(min_price),
            "fid_input_price_2": "",
            "fid_vol_cnt": "0",
            "fid_input_date_1": "",
            "fid_input_iscd_2": "",
        }
        
        try:
            data = self._request("GET", url, tr_id, params=params)
            
            if data.get('rt_cd') != '0':
                market_name = "KOSPI" if iscd == "0001" else "KOSDAQ"
                print(f"[KISManager] 거래량 순위 조회 API 에러 ({market_name}): {data.get('msg1')}")
                return []
                
            stocks = []
            for item in data.get('output', [])[:limit]:
                code = item.get('mksc_shrn_iscd') or item.get('stck_shrn_iscd')
                if not code:
                    continue
                price = int(item.get('stck_prpr', 0))
                volume = int(item.get('acml_vol', 0))
                
                if price < min_price or volume <= 0:
                    continue
                    
                stocks.append({
                    "code": code,
                    "name": item.get('hts_kor_isnm', 'Unknown'),
                    "price": price,
                    "volume": volume,
                    "change_rate": float(item.get('prdy_ctrt', 0)),
                })
            return stocks
            
        except Exception as e:
            market_name = "KOSPI" if iscd == "0001" else "KOSDAQ"
            print(f"[KISManager] 거래량 순위 조회 API 예외 ({market_name}): {e}")
            return []

class DummyManager(KISManager):
    """
    모의투자 예수금 부족 문제를 우회하기 위한 가상 주문 매니저.
    주문 요청 시 즉시 체결된 것으로 간주하고 가상 주문번호를 반환하며, 
    주문 상태 조회 시 전량 체결된 상태로 내려줍니다.
    """
    def __init__(self, auth, account_info, mode="PAPER"):
        super().__init__(auth, account_info, mode)
        self._virtual_odno = 100000
        self._dummy_orders = {}

    def place_order(self, code, qty, price, order_type):
        self._virtual_odno += 1
        odno = str(self._virtual_odno)
        
        # 시장가(0)인 경우 현재가 조회가 필요할 수 있으나, ScalpEngine는 체결가(avg_prvs)가 0이면 pending_orders["price"]를 사용하므로 0 유지
        avg_price = price if price > 0 else 0 

        self._dummy_orders[odno] = {
            "odno": odno,
            "pdno": code,
            "ord_qty": str(qty),
            "tot_ccld_qty": str(qty),  # 즉시 전량 체결
            "avg_prvs": str(avg_price),
            "sll_buy_dvsn_cd": "02" if order_type == OrderType.BUY else "01",
        }
        print(f"[DummyManager] {'매수' if order_type == OrderType.BUY else '매도'} 주문 접수 완료: {code} {qty}주 @ {price} (가상주문번호: {odno})")
        return odno

    def get_order_status(self, order_date=None):
        """가상 매니저에 저장된 모든 주문을 체결 완료 상태로 반환"""
        return list(self._dummy_orders.values())

    def cancel_order(self, order_no, code, qty):
        """이미 전량 체결 처리되므로 취소 기능은 동작하지 않음"""
        print(f"[DummyManager] 취소 요청 무시 (이미 전량 체결 처리됨): {order_no}")
        return str(order_no)
