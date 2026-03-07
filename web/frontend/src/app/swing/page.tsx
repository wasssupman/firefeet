/* eslint-disable */
"use client";

import { useState, useEffect } from "react";
import { BotCard } from "@/components/dashboard/BotCard";
import { LineChart, Loader2 } from "lucide-react";

const API_BASE = "http://localhost:8000/api";

export default function SwingDashboard() {
  const [statuses, setStatuses] = useState<Record<string, any> | null>(null);

  const fetchStatuses = async () => {
    try {
      const res = await fetch(`${API_BASE}/bots/status`);
      const data = await res.json();
      setStatuses(data);
    } catch (e) {
      console.error("Could not reach backend API");
    }
  };

  useEffect(() => {
    fetchStatuses();
    const interval = setInterval(fetchStatuses, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-8 py-8 animate-in fade-in duration-500">
      <header className="flex items-center justify-between pb-6 mb-6 border-b border-border/40">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <LineChart className="text-blue-500" />
            Swing & Reports Engine
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Volatility breakout swing trading and AI-driven deep research tasks.</p>
        </div>
      </header>

      {!statuses ? (
        <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
          <p className="text-sm text-center px-4">Establishing uplink to Firefeet Backend...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
          <BotCard botId="swing" status={statuses["swing"]} onStatusChange={fetchStatuses} />
          <BotCard botId="ai_swing" status={statuses["ai_swing"]} onStatusChange={fetchStatuses} />
          <BotCard botId="batch_reports" status={statuses["batch_reports"]} onStatusChange={fetchStatuses} />
        </div>
      )}
    </div>
  );
}
