"use client";

import { useState, useEffect, useRef } from "react";
import { Terminal } from "lucide-react";

const WS_BASE = "ws://localhost:8000/ws";

type BotID = "scalping" | "swing" | "ai_swing" | "batch_reports";
type BotStatus = "RUNNING" | "STOPPED";

export function LogViewer({ botId, status }: { botId: BotID; status: BotStatus }) {
  const [logs, setLogs] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Connect websocket
    const ws = new WebSocket(`${WS_BASE}/bots/${botId}`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      setLogs((prev) => {
        const newLogs = [...prev, event.data];
        if (newLogs.length > 500) return newLogs.slice(newLogs.length - 500);
        return newLogs;
      });
    };

    return () => {
      ws.close();
    };
  }, [botId]);

  useEffect(() => {
    // Auto scroll
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="mt-4 bg-[#0a0a0a] border border-border/60 rounded-xl overflow-hidden flex flex-col h-72 font-mono text-xs shadow-inner">
      <div className="bg-[#18181b] border-b border-white/5 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Terminal size={14} className="text-zinc-500" />
          <span className="text-zinc-400 font-medium tracking-wide">Console Output</span>
        </div>
        {status === "RUNNING" && (
          <span className="flex h-2 w-2 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)] animate-pulse"></span>
        )}
      </div>
      <div className="p-4 overflow-y-auto flex-1 text-zinc-300" ref={scrollRef}>
        {logs.length === 0 ? (
          <span className="text-zinc-600 italic">Waiting for telemetry...</span>
        ) : (
          logs.map((log, i) => (
            <div key={i} className="whitespace-pre-wrap break-all leading-relaxed hover:bg-white/5 px-1 -mx-1 rounded">
              {log}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
