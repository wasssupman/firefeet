from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import sys
import glob
from pydantic import BaseModel
import os
import sys
import glob
import time
import subprocess
import json
from datetime import datetime

# Ensure backend can import core modules when run directly
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(backend_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from bot_manager import BotManager
from core.analysis.market_temperature import MarketTemperature
from core.news_analyzer import NewsAnalyzer

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

class StartBotRequest(BaseModel):
    args: list[str] = None

@app.post("/api/bots/{bot_id}/start")
async def start_bot(bot_id: str, payload: StartBotRequest = None):
    if bot_id not in BOTS:
        raise HTTPException(status_code=404, detail="Bot ID not found")
        
    script = BOTS[bot_id]["script"]
    # Allow overriding args from UI, otherwise default
    args = payload.args if payload and payload.args else BOTS[bot_id]["args"]
        
    success, msg = await manager.start_bot(bot_id, script, args)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
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
        MARKET_CACHE["temperature"] = {"data": result, "timestamp": now}
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate temperature: {str(e)}")

@app.get("/api/market/summary")
def get_market_summary(force: bool = False):
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
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        result = subprocess.run(
            ["claude", "-p", "--output-format", "text"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=60,
            env=env
        )
        
        output = result.stdout.strip()
        if "```" in output:
             output = output.replace("```json", "").replace("```", "").strip()

        parsed = {"narrative": "분석 실패", "sentiment": "Unknown"}
        if "{" in output and "}" in output:
            try:
                json_str = output[output.find("{"):output.rfind("}")+1]
                parsed = json.loads(json_str)
            except:
                pass
                
        MARKET_CACHE["summary"] = {"data": parsed, "timestamp": now}
        return parsed
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")

@app.get("/api/market/prediction")
def get_market_prediction(force: bool = False):
    now = time.time()
    # Cache prediction for longer (e.g. 1 hour) as it's a daily forecast
    if not force and MARKET_CACHE["prediction"]["data"] and (now - MARKET_CACHE["prediction"]["timestamp"] < 3600):
        return MARKET_CACHE["prediction"]["data"]
        
    try:
        analyzer = NewsAnalyzer()
        news_titles = analyzer.fetch_global_news_titles(limit=15)
        news_text = "\n".join([f"- {t}" for t in news_titles])
        
        prompt = f'''당신은 여의도의 탑티어 시황 분석가입니다. 
다음 글로벌 뉴스를 바탕으로 내일 한국(KOSPI/KOSDAQ) 시초가 분위기, 장중 핵심 테마, 종합 투자 전략을 마크다운 포맷의 리포트로 예측해주세요.

[최신 뉴스 헤드라인]
{news_text}
'''
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        result = subprocess.run(
            ["claude", "-p", "--output-format", "text"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=60,
            env=env
        )
        
        output = result.stdout.strip()
        parsed = {"prediction": output if output else "Prediction unavailable."}
                
        MARKET_CACHE["prediction"] = {"data": parsed, "timestamp": now}
        return parsed
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate prediction: {str(e)}")


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
        df = pd.read_csv(filepath)
        # NaN safe conversion
        df = df.fillna("")
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse CSV logs: {str(e)}")
