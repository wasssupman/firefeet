import asyncio
import os
from typing import Dict, List
from fastapi import WebSocket

class BotManager:
    """Manages python bot processes and broadcasts their stdout to connected clients."""
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.processes: Dict[str, asyncio.subprocess.Process] = {}
        self.log_buffers: Dict[str, List[str]] = {}
        self.connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, bot_id: str, websocket: WebSocket):
        await websocket.accept()
        if bot_id not in self.connections:
            self.connections[bot_id] = []
        self.connections[bot_id].append(websocket)
        
        # Send buffered logs upon connection
        if bot_id in self.log_buffers:
            for log_line in self.log_buffers[bot_id]:
                await websocket.send_text(log_line)

    def disconnect(self, bot_id: str, websocket: WebSocket):
        if bot_id in self.connections and websocket in self.connections[bot_id]:
            self.connections[bot_id].remove(websocket)

    async def broadcast(self, bot_id: str, message: str):
        if bot_id not in self.log_buffers:
            self.log_buffers[bot_id] = []
        
        self.log_buffers[bot_id].append(message)
        # Keep buffer size manageable
        if len(self.log_buffers[bot_id]) > 1000:
            self.log_buffers[bot_id] = self.log_buffers[bot_id][-1000:]
            
        if bot_id in self.connections:
            for connection in self.connections[bot_id].copy():
                try:
                    await connection.send_text(message)
                except Exception:
                    self.disconnect(bot_id, connection)

    def get_status(self, bot_id: str) -> str:
        proc = self.processes.get(bot_id)
        if proc is None:
            return "STOPPED"
        if proc.returncode is None:
            return "RUNNING"
        return "STOPPED"

    async def start_bot(self, bot_id: str, script_name: str, args: List[str] = None):
        if self.get_status(bot_id) == "RUNNING":
            return False, "Bot is already running"
            
        if not args:
            args = []

        # Reset buffer for new run
        self.log_buffers[bot_id] = []
        
        try:
            # We must run python via sys.executable to ensure we use the same venv
            import sys
            cmd = [sys.executable, script_name] + args
            
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.base_dir,
                env=env
            )
            
            self.processes[bot_id] = proc
            
            # Start a background task to read stdout and broadcast
            asyncio.create_task(self._monitor_process(bot_id, proc))
            return True, "Bot started successfully"
        except Exception as e:
            return False, str(e)

    async def stop_bot(self, bot_id: str):
        proc = self.processes.get(bot_id)
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            
            await self.broadcast(bot_id, f"\n[SYSTEM] Process {bot_id} terminated by user.\n")
            return True, "Bot stopped"
        return False, "Bot is not running"

    async def _monitor_process(self, bot_id: str, proc: asyncio.subprocess.Process):
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            # decode and strip trailing newlines but keep whitespace
            text = line.decode('utf-8', errors='replace').rstrip('\n')
            await self.broadcast(bot_id, text)
        
        await proc.wait()
        status_msg = f"\n[SYSTEM] Process exited with code: {proc.returncode}\n"
        await self.broadcast(bot_id, status_msg)
