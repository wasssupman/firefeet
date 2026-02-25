import asyncio
import os
import subprocess
import sys
import threading
from typing import Dict, List
from fastapi import WebSocket


class BotManager:
    """Manages python bot processes and broadcasts their stdout to connected clients."""
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.processes: Dict[str, subprocess.Popen] = {}
        self.log_buffers: Dict[str, List[str]] = {}
        self.connections: Dict[str, List[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop = None

    def _get_loop(self):
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.get_event_loop()
        return self._loop

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
        if proc.poll() is None:
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
            cmd = [sys.executable, script_name] + args

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            # Prevent claude subprocess conflicts
            env.pop("CLAUDECODE", None)

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.base_dir,
                env=env,
            )

            self.processes[bot_id] = proc

            # Monitor stdout in a background thread, push to asyncio loop
            loop = self._get_loop()
            thread = threading.Thread(
                target=self._read_stdout_thread,
                args=(bot_id, proc, loop),
                daemon=True,
            )
            thread.start()
            return True, "Bot started successfully"
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f"{type(e).__name__}: {e}"

    def _read_stdout_thread(self, bot_id: str, proc: subprocess.Popen, loop: asyncio.AbstractEventLoop):
        """Reads stdout from the subprocess in a thread and schedules broadcasts on the event loop."""
        try:
            for raw_line in iter(proc.stdout.readline, b''):
                text = raw_line.decode('utf-8', errors='replace').rstrip('\n').rstrip('\r')
                asyncio.run_coroutine_threadsafe(self.broadcast(bot_id, text), loop)
            proc.wait()
            status_msg = f"\n[SYSTEM] Process exited with code: {proc.returncode}\n"
            asyncio.run_coroutine_threadsafe(self.broadcast(bot_id, status_msg), loop)
        except Exception:
            pass

    async def stop_bot(self, bot_id: str):
        proc = self.processes.get(bot_id)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            await self.broadcast(bot_id, f"\n[SYSTEM] Process {bot_id} terminated by user.\n")
            return True, "Bot stopped"
        return False, "Bot is not running"
