/* eslint-disable */
"use client";

import { useState, useEffect } from "react";
import { Database, BarChart, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const API_BASE = "http://localhost:8000/api";

export default function TradesLog() {
  const [scalpLogs, setScalpLogs] = useState<any[]>([]);
  const [swingLogs, setSwingLogs] = useState<any[]>([]);
  const [tradeDate, setTradeDate] = useState<string>("");
  const [loading, setLoading] = useState(true);

  const fetchTradeLogs = async () => {
    try {
      const scalpRes = await fetch(`${API_BASE}/logs/scalp`);
      const scalpData = await scalpRes.json();
      setScalpLogs(Array.isArray(scalpData) ? scalpData : []);
      
      const swingRes = await fetch(`${API_BASE}/logs/swing`);
      const swingData = await swingRes.json();
      setSwingLogs(Array.isArray(swingData) ? swingData : []);
    } catch (e) {
      console.error("Could not fetch logs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTradeLogs();
    const interval = setInterval(fetchTradeLogs, 5000);
    return () => clearInterval(interval);
  }, []);

  const filteredScalp = scalpLogs.filter((log: any) =>
    log.action && log.action.includes('SELL') &&
    (tradeDate === "" || (log.date || log.timestamp?.split(' ')[0] || log.sell_time?.split(' ')[0]) === tradeDate)
  );

  const filteredSwing = swingLogs.filter((log: any) =>
    log.action && log.action.includes('SELL') &&
    (tradeDate === "" || (log.date || log.timestamp?.split(' ')[0] || log.sell_time?.split(' ')[0]) === tradeDate)
  );
  
  const calcSummary = (logs: any[]) => {
    let totalProfit = 0;
    let wins = 0;
    logs.forEach(l => {
       const pnl = parseFloat(l.realized_pnl || '0');
       totalProfit += pnl;
       if (pnl > 0) wins++;
    });
    return { totalProfit, wins, trades: logs.length };
  };
  
  const scalpSummary = calcSummary(filteredScalp);
  const swingSummary = calcSummary(filteredSwing);
  const totalTrades = scalpSummary.trades + swingSummary.trades;
  const totalWins = scalpSummary.wins + swingSummary.wins;
  const totalProfit = scalpSummary.totalProfit + swingSummary.totalProfit;
  const winRate = totalTrades > 0 ? ((totalWins / totalTrades) * 100).toFixed(1) : "0.0";

  return (
    <div className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-8 py-8 animate-in fade-in duration-500">
      <header className="flex items-center justify-between pb-6 mb-6 border-b border-border/40">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Database className="text-foreground" />
            Trade History
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Review realized P&L and daily trade logs.</p>
        </div>
      </header>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
          <p className="text-sm">Loading trade history...</p>
        </div>
      ) : (
        <>
          <div className="flex flex-col md:flex-row gap-6 mb-6">
            <Card className="flex-1 bg-card/50 backdrop-blur-xl border-border/60 shadow-xl">
              <CardContent className="p-6 flex flex-wrap items-center justify-between gap-6">
                <div className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-muted-foreground uppercase tracking-wider">총 매매 횟수</span>
                  <div className="flex items-end gap-2">
                    <span className="text-3xl font-black text-foreground">{totalTrades}</span>
                    <span className="text-sm text-muted-foreground mb-1">건</span>
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-muted-foreground uppercase tracking-wider">승률</span>
                  <div className="flex items-end gap-2">
                    <span className="text-3xl font-black text-blue-400">{winRate}</span>
                    <span className="text-sm text-muted-foreground mb-1">%</span>
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-muted-foreground uppercase tracking-wider">누적 수 익 (₩)</span>
                  <span className={`text-3xl font-black ${totalProfit > 0 ? 'text-green-500 drop-shadow-[0_0_8px_rgba(34,197,94,0.4)]' : totalProfit < 0 ? 'text-rose-500 drop-shadow-[0_0_8px_rgba(244,63,94,0.4)]' : 'text-foreground'}`}>
                    {totalProfit > 0 ? '+' : ''}{totalProfit.toLocaleString()}
                  </span>
                </div>
                <div className="flex flex-col gap-2 min-w-[200px] border-l border-border/40 pl-6">
                  <span className="text-sm font-medium text-muted-foreground uppercase tracking-wider">날짜 필터</span>
                  <input 
                    type="date" 
                    className="flex h-10 w-full rounded-md border border-input bg-background/50 px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-foreground"
                    value={tradeDate}
                    onChange={(e) => setTradeDate(e.target.value)}
                  />
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            <Card className="bg-card/40 backdrop-blur border-border/50 shadow-lg">
              <CardHeader className="bg-muted/20 border-b border-border/30 pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <BarChart size={18} className="text-rose-500" /> Scalping History
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader className="bg-muted/30">
                      <TableRow className="border-border/40 hover:bg-transparent">
                        <TableHead className="text-muted-foreground w-[160px]">Date</TableHead>
                        <TableHead className="text-muted-foreground">Code</TableHead>
                        <TableHead className="text-muted-foreground text-right w-[100px]">P/L %</TableHead>
                        <TableHead className="text-muted-foreground text-right w-[120px]">Profit (₩)</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredScalp.length === 0 ? (
                        <TableRow className="border-border/40 hover:bg-transparent"><TableCell colSpan={4} className="text-center py-10 text-muted-foreground">No scalping trades found.</TableCell></TableRow>
                      ) : (
                        filteredScalp.map((log: any, i: number) => (
                          <TableRow key={i} className="border-border/30 hover:bg-white/5 transition-colors">
                            <TableCell className="text-foreground/80 font-mono text-xs">{log.timestamp || log.sell_time}</TableCell>
                            <TableCell className="text-foreground/90 font-medium">
                              {log.name && log.code ? `${log.name} (${log.code})` : log.code}
                            </TableCell>
                            <TableCell className={`text-right font-medium ${parseFloat(log.pnl_rate) > 0 ? "text-green-400" : "text-rose-400"}`}>
                              {log.pnl_rate !== "" ? `${log.pnl_rate}%` : "-"}
                            </TableCell>
                            <TableCell className={`text-right font-mono ${parseFloat(log.realized_pnl) > 0 ? 'text-green-400' : 'text-rose-400'}`}>
                              {log.realized_pnl !== "" ? parseInt(log.realized_pnl).toLocaleString() : "0"}
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            <Card className="bg-card/40 backdrop-blur border-border/50 shadow-lg">
              <CardHeader className="bg-muted/20 border-b border-border/30 pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <BarChart size={18} className="text-blue-400" /> Swing & Batch History
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader className="bg-muted/30">
                      <TableRow className="border-border/40 hover:bg-transparent">
                        <TableHead className="text-muted-foreground w-[160px]">Date</TableHead>
                        <TableHead className="text-muted-foreground">Code</TableHead>
                        <TableHead className="text-muted-foreground text-right w-[100px]">P/L %</TableHead>
                        <TableHead className="text-muted-foreground text-right w-[120px]">Profit (₩)</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredSwing.length === 0 ? (
                        <TableRow className="border-border/40 hover:bg-transparent"><TableCell colSpan={4} className="text-center py-10 text-muted-foreground">No swing trades found.</TableCell></TableRow>
                      ) : (
                        filteredSwing.map((log: any, i: number) => (
                          <TableRow key={i} className="border-border/30 hover:bg-white/5 transition-colors">
                            <TableCell className="text-foreground/80 font-mono text-xs">{log.timestamp || log.sell_time}</TableCell>
                            <TableCell className="text-foreground/90 font-medium">
                              {log.name && log.code ? `${log.name} (${log.code})` : log.code}
                            </TableCell>
                            <TableCell className={`text-right font-medium ${parseFloat(log.pnl_rate) > 0 ? "text-green-400" : "text-rose-400"}`}>
                              {log.pnl_rate !== "" ? `${log.pnl_rate}%` : "-"}
                            </TableCell>
                            <TableCell className={`text-right font-mono ${parseFloat(log.realized_pnl) > 0 ? 'text-green-400' : 'text-rose-400'}`}>
                              {log.realized_pnl !== "" ? parseInt(log.realized_pnl).toLocaleString() : "0"}
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
