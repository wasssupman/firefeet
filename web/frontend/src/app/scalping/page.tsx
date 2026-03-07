/* eslint-disable */
"use client";
import { useState, useEffect } from "react";
import { BotCard } from "@/components/dashboard/BotCard";
import { Zap, Loader2, Activity } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const API_BASE = "http://localhost:8000/api";

export default function ScalpingDashboard() {
  const [statuses, setStatuses] = useState<Record<string, any> | null>(null);
  const [calibration, setCalibration] = useState<any>(null);

  const fetchStatuses = async () => {
    try {
      const res = await fetch(`${API_BASE}/bots/status`);
      const data = await res.json();
      setStatuses(data);
    } catch (e) {
      console.error("Could not reach backend API");
    }
  };

  const fetchCalibration = async () => {
    try {
      const res = await fetch(`${API_BASE}/calibration/latest`);
      const data = await res.json();
      setCalibration(data);
    } catch (e) {
      console.error("Could not fetch calibration data", e);
    }
  };

  useEffect(() => {
    fetchStatuses();
    fetchCalibration();
    const interval = setInterval(fetchStatuses, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-8 py-8 animate-in fade-in duration-500">
      <header className="flex items-center justify-between pb-6 mb-6 border-b border-border/40">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Zap className="text-rose-500" />
            Scalping Engine
          </h1>
          <p className="text-sm text-muted-foreground mt-1">High-frequency momentum and volume scalping control center.</p>
        </div>
      </header>

      {!statuses ? (
        <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-rose-500" />
          <p className="text-sm text-center px-4">Establishing uplink to Firefeet Backend...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <div className="lg:col-span-1">
            <BotCard botId="scalping" status={statuses["scalping"]} onStatusChange={fetchStatuses} />
          </div>

          <div className="lg:col-span-1 flex flex-col">
            <Card className="bg-card/40 backdrop-blur-xl border-border/50 shadow-xl flex-1 flex flex-col">
              <CardHeader className="pb-2 border-b border-border/40 bg-muted/10">
                <CardTitle className="text-lg flex items-center gap-2 text-foreground">
                  <Activity size={18} className="text-indigo-400" />
                  Self-Calibration Curves
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-6 flex-1 min-h-[300px]">
                {!calibration || !calibration.confidence_curve || calibration.confidence_curve.length === 0 ? (
                   <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                     <Activity className="w-10 h-10 mb-3 opacity-20" />
                     <p className="font-medium">No calibration data yet</p>
                     <p className="text-xs opacity-60 mt-1">Run post-trade calibration batch to generate curves.</p>
                   </div>
                ) : (
                  <div className="w-full h-full min-h-[250px] -ml-4 mt-2">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={calibration.confidence_curve}
                        margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                        <XAxis dataKey="bin" stroke="rgba(255,255,255,0.3)" tick={{fill: "rgba(255,255,255,0.5)", fontSize: 12}} dy={10} />
                        <YAxis stroke="rgba(255,255,255,0.3)" tick={{fill: "rgba(255,255,255,0.5)", fontSize: 12}} dx={-10} domain={[0, 100]} />
                        <Tooltip 
                          contentStyle={{ backgroundColor: 'rgba(9, 9, 11, 0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.5)' }}
                          itemStyle={{ color: '#fff' }}
                        />
                        <Legend wrapperStyle={{ paddingTop: '20px' }}/>
                        <Line type="monotone" dataKey="win_rate" name="Win Rate (%)" stroke="#6366f1" strokeWidth={3} dot={{r: 4, fill: "#6366f1", strokeWidth: 2, stroke: "#18181b"}} activeDot={{r: 6}} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
