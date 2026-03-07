from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

def is_analysis_hours():
    """분석 허용 시간: 평일 08:00~15:00 KST"""
    now = datetime.now(KST)
    if now.weekday() >= 5:  # 주말
        return False
    return 800 <= (now.hour * 100 + now.minute) <= 1500

# Ensure backend can import core modules when run directly
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(backend_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from bot_manager import BotManager
from core.analysis.market_temperature import MarketTemperature
from core.news_analyzer import NewsAnalyzer
from core.config_loader import ConfigLoader
from core.discord_client import DiscordClient

async def _call_claude_cli(prompt: str, timeout: int = 120, tools=None) -> str:
    """Claude CLI를 비동기로 호출. tools로 허용 도구 지정 가능 (e.g. ['WebSearch'])"""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = ["claude", "-p", "--output-format", "text"]
    for tool in (tools or []):
        cmd.extend(["--allowedTools", tool])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=timeout,
        )
        return stdout.decode("utf-8", errors="replace").strip()
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Claude CLI timed out after {timeout}s")

app = FastAPI(title="Firefeet API Backend")

# Initialize Process Manager giving it the context of the main project root
manager = BotManager(base_dir=project_root)

# Allow CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "Firefeet Backend is running!"}

# --- Bot Controller Logic ---
BOTS = {
    "scalping": {"script": "run_scalper.py", "args": []},
    "swing": {"script": "run_firefeet.py", "args": []},
    "ai_swing": {"script": "run_ai_swing_bot.py", "args": []},
    "batch_reports": {"script": "run_batch_reports.py", "args": ["--limit", "3", "--batch", "3"]}
}

@app.get("/api/bots/status")
def get_all_bot_statuses():
    statuses = {}
    for bot_id in BOTS.keys():
        statuses[bot_id] = manager.get_status(bot_id)
    return statuses

class AISettingsUpdate(BaseModel):
    compact_prompt: bool = None

@app.get("/api/config/ai-settings")
def get_ai_settings():
    import yaml
    path = os.path.join(project_root, "config/deep_analysis.yaml")
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    orch = config.get("orchestrator", {})
    return {"compact_prompt": orch.get("compact_prompt", False)}

@app.post("/api/config/ai-settings")
def update_ai_settings(payload: AISettingsUpdate):
    import yaml
    path = os.path.join(project_root, "config/deep_analysis.yaml")
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    if "orchestrator" not in config:
        config["orchestrator"] = {}
    if payload.compact_prompt is not None:
        config["orchestrator"]["compact_prompt"] = payload.compact_prompt
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    return {"status": "ok", "compact_prompt": config["orchestrator"]["compact_prompt"]}

class StartBotRequest(BaseModel):
    args: list[str] = None

@app.post("/api/bots/{bot_id}/start")
async def start_bot(bot_id: str, payload: StartBotRequest = None):
    if bot_id not in BOTS:
        raise HTTPException(status_code=404, detail="Bot ID not found")
        
    script = BOTS[bot_id]["script"]
    # Allow overriding args from UI, otherwise default
    args = payload.args if payload and payload.args else BOTS[bot_id]["args"]
        
    import traceback
    try:
        success, msg = await manager.start_bot(bot_id, script, args)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal error: {repr(e)}")
    if not success:
        raise HTTPException(status_code=400, detail=msg or "Unknown error")
    return {"status": "started", "message": msg}

@app.post("/api/bots/{bot_id}/stop")
async def stop_bot(bot_id: str):
    success, msg = await manager.stop_bot(bot_id)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "stopped", "message": msg}

@app.websocket("/ws/bots/{bot_id}")
async def websocket_bot_logs(websocket: WebSocket, bot_id: str):
    await manager.connect(bot_id, websocket)
    try:
        while True:
            # Keep connection alive but don't expect messages from client
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(bot_id, websocket)

# --- Market Insights Logic ---
MARKET_CACHE = {
    "temperature": {"data": None, "timestamp": 0},
    "summary": {"data": None, "timestamp": 0},
    "prediction": {"data": None, "timestamp": 0}
}
CACHE_TTL = 900  # 15 minutes

@app.get("/api/market/temperature")
def get_market_temperature(force: bool = False):
    now = time.time()
    if not force and MARKET_CACHE["temperature"]["data"] and (now - MARKET_CACHE["temperature"]["timestamp"] < CACHE_TTL):
        return MARKET_CACHE["temperature"]["data"]

    try:
        mt = MarketTemperature(config_path=os.path.join(project_root, "config/temperature_config.yaml"))
        result = mt.calculate()
        result["discord_report"] = mt.generate_report(result)
        # Frontend expects "score" (not "temperature") and per-module scores inside details
        result["score"] = result.get("temperature", 0)
        for name, score in result.get("components", {}).items():
            if name in result.get("details", {}):
                result["details"][name]["score"] = score
            else:
                result["details"][name] = {"score": score}
        MARKET_CACHE["temperature"] = {"data": result, "timestamp": now}
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate temperature: {str(e)}")

@app.get("/api/market/summary")
async def get_market_summary(force: bool = False):
    now = time.time()
    if not force and MARKET_CACHE["summary"]["data"] and (now - MARKET_CACHE["summary"]["timestamp"] < CACHE_TTL):
        return MARKET_CACHE["summary"]["data"]

    try:
        # Fetch latest news
        analyzer = NewsAnalyzer()
        news_titles = analyzer.fetch_global_news_titles(limit=10)
        news_text = "\n".join([f"- {t}" for t in news_titles])

        prompt = f'''당신은 여의도의 탑티어 시황 분석가입니다.
방금 수집된 최신 뉴스 헤드라인들을 바탕으로, 현재 시장을 관통하는 '핵심 내러티브(테마)' 1~2가지를 파악하고
현재 시장이 긍정적인지(Risk-On) 부정적인지(Risk-Off) 아주 간결하게 요약해주세요.

[최신 뉴스 헤드라인]
{news_text}

출력 형식:
반드시 아래 JSON 형식으로만 반환하십시오.
{{
  "narrative": "시황 분석 및 핵심 테마 요약 (2~3문장)",
  "sentiment": "Bullish" 혹은 "Bearish" 혹은 "Neutral"
}}
'''
        output = await _call_claude_cli(prompt)
        if "```" in output:
             output = output.replace("```json", "").replace("```", "").strip()

        parsed = {"narrative": "분석 실패", "sentiment": "Unknown"}
        if "{" in output and "}" in output:
            try:
                json_str = output[output.find("{"):output.rfind("}")+1]
                parsed = json.loads(json_str)
            except (json.JSONDecodeError, ValueError):
                pass

        MARKET_CACHE["summary"] = {"data": parsed, "timestamp": now}
        return parsed

    except Exception as e:
        print(f"[Summary] Error: {e}")
        fallback = {"narrative": f"AI 요약 일시 불가: {type(e).__name__}", "sentiment": "Unknown"}
        return fallback

@app.get("/api/market/prediction")
async def get_market_prediction(force: bool = False):
    now = time.time()
    # Cache prediction for longer (e.g. 1 hour) as it's a daily forecast
    if not force and MARKET_CACHE["prediction"]["data"] and (now - MARKET_CACHE["prediction"]["timestamp"] < 3600):
        return MARKET_CACHE["prediction"]["data"]

    try:
        prompt = '''당신은 여의도의 탑티어 시황 분석가입니다.
웹 검색을 활용하여 최신 글로벌 뉴스, 미국 증시 마감 결과, 주요 경제 지표를 직접 조사한 뒤,
내일 한국(KOSPI/KOSDAQ) 시초가 분위기, 장중 핵심 테마, 종합 투자 전략을 마크다운 포맷의 리포트로 예측해주세요.
'''
        output = await _call_claude_cli(prompt, timeout=300, tools=["WebSearch"])
        parsed = {"prediction": output if output else "Prediction unavailable."}

        MARKET_CACHE["prediction"] = {"data": parsed, "timestamp": now}
        return parsed

    except Exception as e:
        print(f"[Prediction] Error: {e}")
        fallback = {"prediction": f"AI 예측 일시 불가: {type(e).__name__}"}
        return fallback


# --- Portfolio & Calibration APIs ---
_kis_cache = {}

def _get_kis_manager(mode: str):
    """Return a cached KISManager for the given mode to avoid token re-issue."""
    if mode not in _kis_cache:
        from core.providers.kis_api import KISManager
        from core.kis_auth import KISAuth
        loader = ConfigLoader()
        config = loader.get_kis_config(mode=mode)
        auth = KISAuth(config)
        account = loader.get_account_info(mode=mode)
        _kis_cache[mode] = KISManager(auth, account, mode=mode)
    return _kis_cache[mode]

@app.get("/api/portfolio")
def get_portfolio():
    try:
        kis_real = _get_kis_manager("REAL")
        real_balance = kis_real.get_balance()

        kis_paper = _get_kis_manager("PAPER")
        paper_balance = kis_paper.get_balance()

        empty = {"total_asset": 0, "deposit": 0, "holdings": []}
        return {
            "real": real_balance or empty,
            "paper": paper_balance or empty
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch portfolio: {str(e)}")

@app.get("/api/calibration/latest")
def get_latest_calibration():
    try:
        import sqlite3
        db_path = os.path.join(project_root, "logs", "firefeet.db")
        if not os.path.exists(db_path):
            return {"confidence_curve": [], "signal_weights": []}
            
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT MAX(date) FROM calibration")
        row = cursor.fetchone()
        latest_date = row[0] if row else None
        if not latest_date:
            return {"confidence_curve": [], "signal_weights": []}
            
        cursor.execute("SELECT metric_type, metric_key, metric_value, sample_count FROM calibration WHERE date = ?", (latest_date,))
        rows = cursor.fetchall()
        
        conf_curve = []
        signal_weights = []
        
        for r in rows:
            if r["metric_type"] == "confidence":
                conf_curve.append({
                    "bin": r["metric_key"],
                    "win_rate": r["metric_value"],
                    "samples": r["sample_count"]
                })
            elif r["metric_type"] == "weight":
                signal_weights.append({
                    "signal": r["metric_key"],
                    "weight": r["metric_value"]
                })
                
        # sort confidence curve
        conf_curve.sort(key=lambda x: float(x["bin"].split('~')[0]) if '~' in x["bin"] else 0)
        
        return {
            "date": latest_date,
            "confidence_curve": conf_curve,
            "signal_weights": signal_weights
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch calibration data: {str(e)}")

# --- Files & Data Logic ---

def safe_read(filepath: str):
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/reports")
def list_reports():
    reports_dir = os.path.join(project_root, "reports")
    if not os.path.exists(reports_dir):
        return []
    
    files = glob.glob(os.path.join(reports_dir, "*.md"))
    # Sort by creation time, descending
    files.sort(key=os.path.getmtime, reverse=True)
    
    return [{"filename": os.path.basename(f), "modified": os.path.getmtime(f), "size": os.path.getsize(f)} for f in files]

@app.get("/api/reports/{filename}")
def get_report(filename: str):
    # Basic path traversal protection
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    filepath = os.path.join(project_root, "reports", filename)
    content = safe_read(filepath)
    return {"filename": filename, "content": content}

@app.get("/api/logs/{log_type}")
def get_logs(log_type: str):
    """Fetch trade logs. Valid types: 'scalp', 'swing'"""
    if log_type not in ["scalp", "swing"]:
        raise HTTPException(status_code=400, detail="Invalid log type")
        
    filename = f"trades_{log_type}.csv"
    filepath = os.path.join(project_root, "logs", filename)
    
    try:
        import pandas as pd
        if not os.path.exists(filepath):
            return []
        df = pd.read_csv(filepath, on_bad_lines="warn")
        df = df.fillna("")
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse CSV logs: {str(e)}")


# --- Discord ---

class DiscordSendRequest(BaseModel):
    message: str
    type: str = "custom"  # "temperature", "summary", "prediction", "custom"

@app.post("/api/discord/send")
def send_discord_message(req: DiscordSendRequest):
    """Discord로 메시지 전송. type으로 캐시된 분석 결과를 보내거나 custom 메시지를 전송."""
    try:
        # 캐시된 분석 결과 전송
        if req.type == "temperature":
            cached = MARKET_CACHE["temperature"].get("data")
            if cached and "discord_report" in cached:
                message = cached["discord_report"]
            else:
                raise HTTPException(status_code=404, detail="온도 분석 캐시 없음. 먼저 /api/market/temperature 호출 필요")
        elif req.type in ("summary", "prediction"):
            cached = MARKET_CACHE[req.type].get("data")
            if cached:
                message = json.dumps(cached, ensure_ascii=False, indent=2)
            else:
                raise HTTPException(status_code=404, detail=f"{req.type} 캐시 없음")
        else:
            message = req.message

        if not message or not message.strip():
            raise HTTPException(status_code=400, detail="빈 메시지")

        discord = DiscordClient()
        discord.send(message)
        return {"status": "sent", "length": len(message)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Discord 전송 실패: {str(e)}")
