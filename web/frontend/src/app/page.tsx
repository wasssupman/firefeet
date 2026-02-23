"use client";

import { useState, useEffect, useRef } from "react";
import { Terminal, Play, Square, Activity, FileText, BarChart, Database, MapPin, Loader2, ArrowRight, ThermometerSun, RefreshCw, TrendingUp, X, ChevronRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { ThemeToggle } from "@/components/theme-toggle";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const API_BASE = "http://localhost:8000/api";
const WS_BASE = "ws://localhost:8000/ws";

type BotID = "scalping" | "swing" | "ai_swing" | "batch_reports";
type BotStatus = "RUNNING" | "STOPPED";

const BOT_LABELS: Record<BotID, { name: string, desc: string }> = {
  scalping: { name: "⚡ 당일 초단타 매매 (Scalping)", desc: "거래량 집중 종목 스캘핑 및 즉시 익/손절" },
  swing: { name: "📈 변동성 돌파 스윙 (Swing)", desc: "수급 기반 우량주 종가 매수 및 단기 보유" },
  ai_swing: { name: "🤖 AI 자동 분석 매매 (AI Swing)", desc: "당일 테마 분석 및 AI 재무/수급 분석 후 익일 매수" },
  batch_reports: { name: "📚 딥 리서치 자동화 (Reporter)", desc: "장 마감 후 주도주 스크리닝 및 심층 마크다운 리포트 생성" },
};

function LogViewer({ botId, status }: { botId: BotID; status: BotStatus }) {
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
    <div className="mt-4 bg-[#0a0a0a] border border-border rounded-md overflow-hidden flex flex-col h-64 font-mono text-xs">
      <div className="bg-muted border-b border-border px-3 py-1.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Terminal size={14} className="text-muted-foreground" />
          <span className="text-muted-foreground font-medium">Console Output</span>
        </div>
        {status === "RUNNING" && (
          <span className="flex h-2 w-2 rounded-full bg-green-500 animate-pulse"></span>
        )}
      </div>
      <div className="p-3 overflow-y-auto flex-1 text-foreground/80" ref={scrollRef}>
        {logs.length === 0 ? (
          <span className="text-muted-foreground/70 italic">Waiting for logs...</span>
        ) : (
          logs.map((log, i) => (
            <div key={i} className="whitespace-pre-wrap break-all leading-relaxed">
              {log}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// 모의투자 지원 봇 목록
const PAPER_TRADABLE: BotID[] = ["scalping", "swing", "ai_swing"];

function BotCard({ botId, status, onStatusChange }: { botId: BotID; status: BotStatus; onStatusChange: () => void }) {
  const [isLoading, setIsLoading] = useState(false);
  const [deepAnalysisEnabled, setDeepAnalysisEnabled] = useState(false);
  const [paperMode, setPaperMode] = useState(false);
  const info = BOT_LABELS[botId];
  const supportsPaper = PAPER_TRADABLE.includes(botId);

  const handleToggle = async () => {
    setIsLoading(true);
    try {
      const isStart = status === "STOPPED";
      const endpoint = isStart ? "start" : "stop";
      
      let payload: { args: string[] } | undefined = undefined;

      if (isStart) {
        if (botId === "batch_reports") {
          const args = ["--limit", "3", "--batch", "3"];
          if (!deepAnalysisEnabled) args.push("--stage2-only");
          payload = { args };
        } else if (supportsPaper && paperMode) {
          payload = { args: ["--paper"] };
        }
      }

      const res = await fetch(`${API_BASE}/bots/${botId}/${endpoint}`, { 
        method: "POST",
        headers: payload ? { "Content-Type": "application/json" } : undefined,
        body: payload ? JSON.stringify(payload) : undefined
      });
      if (res.ok) {
        onStatusChange();
      } else {
        const data = await res.json();
        alert(`Error: ${data.detail}`);
      }
    } catch (e) {
      alert("Failed to connect to backend API.");
    }
    setIsLoading(false);
  };

  return (
    <Card className="bg-card border-border shadow-xl w-full">
      <CardHeader className="pb-3">
        <div className="flex justify-between items-start">
          <div>
            <CardTitle className="text-xl text-foreground">{info.name}</CardTitle>
            <CardDescription className="text-muted-foreground mt-1.5">{info.desc}</CardDescription>
          </div>
          <Badge variant={status === "RUNNING" ? "default" : "secondary"} className={status === "RUNNING" ? "bg-green-500/10 text-green-400 hover:bg-green-500/20" : ""}>
            {status}
          </Badge>
        </div>

        {/* 모의투자 토글 (scalping / swing / ai_swing) */}
        {supportsPaper && (
          <div className="flex items-center gap-3 mt-4 pt-4 border-t border-border/40">
            <Switch
              checked={paperMode}
              onCheckedChange={setPaperMode}
              disabled={status === "RUNNING"}
              id={`paper-switch-${botId}`}
              className="data-[state=checked]:bg-blue-500"
            />
            <label htmlFor={`paper-switch-${botId}`} className="text-sm font-medium text-foreground/80 cursor-pointer select-none">
              모의투자 모드
            </label>
            {paperMode ? (
              <span className="text-xs font-semibold text-blue-400 ml-auto border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 rounded-full">
                PAPER
              </span>
            ) : (
              <span className="text-xs font-semibold text-rose-400 ml-auto border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 rounded-full">
                REAL 💸
              </span>
            )}
          </div>
        )}

        {/* 딥 리서치 토글 (batch_reports) */}
        {botId === "batch_reports" && (
          <div className="flex items-center gap-3 mt-4 pt-4 border-t border-border/40">
            <Switch 
              checked={deepAnalysisEnabled} 
              onCheckedChange={setDeepAnalysisEnabled}
              disabled={status === "RUNNING"}
              id="deep-analysis-switch"
              className="data-[state=checked]:bg-rose-500"
            />
            <label htmlFor="deep-analysis-switch" className="text-sm font-medium text-foreground/80 cursor-pointer">
              3단계 (딥 리서치 심층 분석) 진행
            </label>
            {!deepAnalysisEnabled && <span className="text-xs font-medium text-rose-400 ml-auto border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 rounded-full">2단계(스크리닝)까지만 진행</span>}
          </div>
        )}
      </CardHeader>
      <CardContent>
        <LogViewer botId={botId} status={status} />
      </CardContent>
      <CardFooter className="pt-2">
        <Button 
          variant={status === "RUNNING" ? "destructive" : "default"} 
          className="w-full font-semibold transition-all"
          onClick={handleToggle}
          disabled={isLoading}
        >
          {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : status === "RUNNING" ? <Square className="mr-2 h-4 w-4 fill-current" /> : <Play className="mr-2 h-4 w-4 fill-current" />}
          {status === "RUNNING" ? "Stop Bot" : (supportsPaper && paperMode ? "Start Bot (모의투자)" : "Start Bot")}
        </Button>
      </CardFooter>
    </Card>
  );
}

export default function Dashboard() {
  const [statuses, setStatuses] = useState<Record<BotID, BotStatus> | null>(null);
  
  // Reports State
  const [reports, setReports] = useState<{filename: string, modified: number, size: number}[]>([]);
  const [selectedReport, setSelectedReport] = useState<string | null>(null);
  const [reportContent, setReportContent] = useState<string>("");

  // Logs State
  const [scalpLogs, setScalpLogs] = useState<any[]>([]);
  const [swingLogs, setSwingLogs] = useState<any[]>([]);

  // Market Insights State
  const [marketTemp, setMarketTemp] = useState<any>(null);
  const [marketSummary, setMarketSummary] = useState<any>(null);
  const [marketPrediction, setMarketPrediction] = useState<any>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const [tradeDate, setTradeDate] = useState<string>("");

  const fetchStatuses = async () => {
    try {
      const res = await fetch(`${API_BASE}/bots/status`);
      const data = await res.json();
      setStatuses(data);
    } catch (e) {
      console.error("Could not reach backend API");
    }
  };

  const fetchReportsList = async () => {
    try {
      const res = await fetch(`${API_BASE}/reports`);
      const data = await res.json();
      setReports(data || []);
    } catch (e) {
      console.error("Could not fetch reports", e);
    }
  };

  const viewReport = async (filename: string) => {
    setSelectedReport(filename);
    try {
      const res = await fetch(`${API_BASE}/reports/${filename}`);
      const data = await res.json();
      setReportContent(data.content || "Report is empty.");
    } catch (e) {
      setReportContent("Failed to load report content.");
    }
  };

  const fetchTradeLogs = async () => {
    try {
      const scalpRes = await fetch(`${API_BASE}/logs/scalp`);
      setScalpLogs(await scalpRes.json());
      const swingRes = await fetch(`${API_BASE}/logs/swing`);
      setSwingLogs(await swingRes.json());
    } catch (e) {
      console.error("Could not fetch logs");
    }
  };

  const fetchMarketPrediction = async (force = false) => {
    const qs = force ? "?force=true" : "";
    try {
      const predRes = await fetch(`${API_BASE}/market/prediction${qs}`);
      if (predRes.ok) setMarketPrediction(await predRes.json());
    } catch (e) {
      console.error("Could not fetch prediction", e);
    }
  };

  const fetchMarketInsights = async (force = false) => {
    setMarketLoading(true);
    try {
      const qs = force ? "?force=true" : "";
      
      const [tempRes, sumRes] = await Promise.all([
        fetch(`${API_BASE}/market/temperature${qs}`),
        fetch(`${API_BASE}/market/summary${qs}`),
      ]);
      
      if (tempRes.ok) setMarketTemp(await tempRes.json());
      if (sumRes.ok) setMarketSummary(await sumRes.json());
    } catch (e) {
      console.error("Could not fetch market insights", e);
    } finally {
      setMarketLoading(false);
    }
    // Fetch prediction independently (slow — doesn't block spinner)
    fetchMarketPrediction(force);
  };

  useEffect(() => {
    fetchStatuses();
    fetchReportsList();
    fetchTradeLogs();
    fetchMarketInsights();
    const interval = setInterval(() => {
      fetchStatuses();
      fetchReportsList();
      fetchTradeLogs();
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  // 모달 열릴 때 body 스크롤 잠금
  useEffect(() => {
    if (selectedReport && reportContent) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [selectedReport, reportContent]);

  return (
    <div className="min-h-screen bg-background text-foreground font-sans selection:bg-rose-500/30">
      <Tabs defaultValue="bots" className="w-full">

        {/* ── Sticky Bar: Header + TabsList only ── */}
        <div className="sticky top-0 z-40 bg-background/95 backdrop-blur-sm border-b border-border/60">
          <div className="max-w-7xl mx-auto px-4 sm:px-8 pt-4 sm:pt-5 pb-2">
            <header className="flex items-center justify-between pb-3 border-b border-border/40">
              <div className="flex items-center gap-2 sm:gap-3 min-w-0">
                <div className="h-9 w-9 sm:h-10 sm:w-10 flex-shrink-0 rounded-xl bg-gradient-to-tr from-rose-500 to-orange-400 flex items-center justify-center shadow-lg shadow-rose-500/20">
                  <Activity className="text-white" size={18} />
                </div>
                <div className="min-w-0">
                  <h1 className="text-lg sm:text-2xl font-bold tracking-tight truncate">Firefeet Command Center</h1>
                  <p className="text-xs sm:text-sm text-muted-foreground hidden sm:block">Autonomous Trading &amp; AI Generative Reporting</p>
                </div>
              </div>
              <div className="flex gap-2 flex-shrink-0">
                <Badge variant="outline" className="border-border text-muted-foreground bg-card text-xs hidden sm:flex">
                  {statuses ? (
                    <>
                      <span className="h-2 w-2 rounded-full bg-green-500 mr-2 border border-green-800 animate-pulse"></span>
                      Uplink Active
                    </>
                  ) : "Connecting..."}
                </Badge>
                <ThemeToggle />
              </div>
            </header>

            <TabsList className="bg-muted border border-border w-full justify-start h-auto p-1 overflow-x-auto flex-nowrap gap-0.5 mt-2">
              <TabsTrigger value="bots" className="data-[state=active]:bg-zinc-800 py-2 px-3 text-xs sm:text-sm flex-shrink-0 flex items-center gap-1.5 whitespace-nowrap"><Terminal className="w-4 h-4" />봇 실행 제어</TabsTrigger>
              <TabsTrigger value="market" className="data-[state=active]:bg-zinc-800 py-2 px-3 text-xs sm:text-sm flex-shrink-0 flex items-center gap-1.5 whitespace-nowrap"><ThermometerSun className="w-4 h-4" />시장 시황</TabsTrigger>
              <TabsTrigger value="reports" className="data-[state=active]:bg-zinc-800 py-2 px-3 text-xs sm:text-sm flex-shrink-0 flex items-center gap-1.5 whitespace-nowrap"><FileText className="w-4 h-4" />AI 종목 리포트</TabsTrigger>
              <TabsTrigger value="trades" className="data-[state=active]:bg-zinc-800 py-2 px-3 text-xs sm:text-sm flex-shrink-0 flex items-center gap-1.5 whitespace-nowrap"><Database className="w-4 h-4" />매매 로그</TabsTrigger>
            </TabsList>
          </div>
        </div>

        {/* ── Scrollable Content Area ── */}
        <div className="max-w-7xl mx-auto px-4 sm:px-8 pb-8 mt-4 sm:mt-6">

          {/* TabsContent starts here — all inside the same <Tabs> */}
          <TabsContent value="bots" className="w-full mt-4 sm:mt-6">
            {!statuses ? (
              <div className="flex flex-col items-center justify-center py-16 sm:py-24 text-muted-foreground gap-4">
                <Loader2 className="w-8 h-8 animate-spin text-rose-500" />
                <p className="text-sm text-center px-4">Establishing uplink to Firefeet Backend...</p>
                <p className="text-xs font-mono bg-muted px-3 py-1 rounded-md text-center">uvicorn main:app --port 8000</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
                {(Object.keys(BOT_LABELS) as BotID[]).map((id) => (
                  <BotCard key={id} botId={id} status={statuses[id]} onStatusChange={fetchStatuses} />
                ))}
              </div>
            )}
          </TabsContent>

          <TabsContent value="market" className="w-full mt-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-xl font-bold">Market Temperature & Sentiment</h2>
                <p className="text-sm text-muted-foreground mt-1">AI-driven macro and narrative analysis to gauge market risk.</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => fetchMarketInsights(true)} disabled={marketLoading} className="gap-2 self-start sm:self-auto flex-shrink-0">
                <RefreshCw size={14} className={marketLoading ? "animate-spin" : ""} />
                Force Refresh
              </Button>
            </div>
            
            {marketLoading && !marketTemp ? (
               <div className="flex items-center justify-center h-64 text-muted-foreground gap-3">
                 <Loader2 className="w-6 h-6 animate-spin text-rose-500" />
                 <span>Analyzing market conditions and fetching AI sentiment... This may take up to a minute.</span>
               </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Temperature Overview */}
                <Card className="bg-card border-border lg:col-span-1 shadow-sm">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-lg flex items-center gap-2 text-foreground">
                      <ThermometerSun size={18} className="text-orange-500" />
                      Temperature
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-col items-center justify-center py-8">
                       <span className="text-6xl font-black tracking-tighter mb-2">{marketTemp?.score ?? 0}°</span>
                       <Badge variant="outline" className={`text-md px-4 py-1 font-bold tracking-wider ${
                         marketTemp?.level === 'HOT' ? 'border-red-500 text-red-500 bg-red-500/10' :
                         marketTemp?.level === 'WARM' ? 'border-orange-500 text-orange-500 bg-orange-500/10' :
                         marketTemp?.level === 'COOL' ? 'border-blue-400 text-blue-400 bg-blue-400/10' :
                         marketTemp?.level === 'COLD' ? 'border-blue-600 text-blue-600 bg-blue-600/10' :
                         'border-zinc-500 text-zinc-400 bg-zinc-500/10'
                       }`}>
                         {marketTemp?.level ?? 'UNKNOWN'}
                       </Badge>
                    </div>
                    <div className="space-y-3 mt-4">
                       <div className="flex justify-between items-center text-sm border-b border-border/40 pb-2">
                         <span className="text-muted-foreground">Macro (40%)</span>
                         <span className="font-medium {marketTemp?.details?.macro?.score > 0 ? 'text-green-500' : 'text-red-500'}">{marketTemp?.details?.macro?.score > 0 ? '+' : ''}{marketTemp?.details?.macro?.score ?? 0}</span>
                       </div>
                       <div className="flex justify-between items-center text-sm border-b border-border/40 pb-2">
                         <span className="text-muted-foreground">Econ (30%)</span>
                         <span className="font-medium {marketTemp?.details?.econ?.score > 0 ? 'text-green-500' : 'text-red-500'}">{marketTemp?.details?.econ?.score > 0 ? '+' : ''}{marketTemp?.details?.econ?.score ?? 0}</span>
                       </div>
                       <div className="flex justify-between items-center text-sm pb-1">
                         <span className="text-muted-foreground">Sentiment (30%)</span>
                         <span className="font-medium {marketTemp?.details?.sentiment?.score > 0 ? 'text-green-500' : 'text-red-500'}">{marketTemp?.details?.sentiment?.score > 0 ? '+' : ''}{marketTemp?.details?.sentiment?.score ?? 0}</span>
                       </div>
                    </div>
                  </CardContent>
                </Card>

                {/* AI Summary */}
                <Card className="bg-card border-border lg:col-span-2 shadow-sm flex flex-col">
                  <CardHeader className="pb-3 border-b border-border/40">
                    <div className="flex justify-between items-start">
                      <CardTitle className="text-lg flex items-center gap-2 text-foreground">
                        <Activity size={18} className="text-blue-400" />
                        AI Market Narrative
                      </CardTitle>
                      {marketSummary?.sentiment && (
                        <Badge variant="secondary" className={`uppercase tracking-wider text-xs ${
                          marketSummary.sentiment.toLowerCase() === 'bullish' ? 'bg-green-500/10 text-green-500' :
                          marketSummary.sentiment.toLowerCase() === 'bearish' ? 'bg-red-500/10 text-red-500' :
                          'bg-zinc-500/10 text-zinc-400'
                        }`}>
                          {marketSummary.sentiment}
                        </Badge>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className="pt-6 flex-1">
                    <div className="bg-muted/30 p-5 rounded-lg border border-border/50 h-full">
                       <p className="text-base leading-7 text-foreground/90 whitespace-pre-wrap">
                         {marketSummary?.narrative ?? "AI summary not available."}
                       </p>
                    </div>
                  </CardContent>
                </Card>

                <Card className="bg-[#1e1f22] border-border/20 lg:col-span-3 shadow-md rounded-xl overflow-hidden mt-2">
                  <CardHeader className="pb-3 border-b border-white/5 bg-[#2b2d31]">
                    <CardTitle className="text-[15px] font-semibold flex items-center gap-2 text-white/90">
                      <Terminal size={16} className="text-zinc-400" />
                      discord-broadcast
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pt-4 bg-[#313338]">
                    <div className="flex gap-4">
                      {/* Discord Avatar */}
                      <div className="w-10 h-10 rounded-full bg-[#5865F2] flex-shrink-0 flex items-center justify-center overflow-hidden shadow-inner">
                        <Activity className="text-white w-6 h-6" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2 mb-1">
                          <span className="font-medium text-[16px] text-white/95 tracking-wide flex items-center gap-1.5">
                            Firefeet Bot 
                            <span className="bg-[#5865F2] text-[10px] font-bold px-1.5 py-0.5 rounded-[3px] text-white flex items-center justify-center leading-none mt-0.5 mb-0.5 h-4">APP</span>
                          </span>
                          <span className="text-xs text-white/40 font-medium">Today at {new Date().toLocaleTimeString('en-US', {hour: 'numeric', minute:'2-digit', hour12: true})}</span>
                        </div>
                        <div className="text-[#dbdee1] text-[15px] whitespace-pre-wrap font-sans">
                          {marketTemp?.discord_report ? (
                            <div className="prose prose-invert prose-p:my-0 prose-p:leading-[1.6] max-w-none text-[#dbdee1] [&_strong]:text-white [&_strong]:font-semibold">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {marketTemp.discord_report.replace(/\n/g, '  \n')}
                              </ReactMarkdown>
                            </div>
                          ) : (
                            <span className="text-white/30 italic">Discord format not available.</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* AI Market Prediction */}
                <Card className="bg-card border-border lg:col-span-3 shadow-sm flex flex-col mt-4">
                  <CardHeader className="pb-3 border-b border-border/40">
                    <CardTitle className="text-[16px] font-semibold flex items-center gap-2 text-foreground">
                      <TrendingUp size={18} className="text-purple-400" />
                      내일의 한국 증시 예측 리포트 (By AI)
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pt-6">
                    <div className="bg-muted/30 p-5 rounded-lg border border-border/50 text-foreground/90 whitespace-pre-wrap font-sans prose prose-invert max-w-none prose-p:leading-[1.7]">
                       {marketPrediction?.prediction ? (
                         <ReactMarkdown remarkPlugins={[remarkGfm]}>
                           {marketPrediction.prediction}
                         </ReactMarkdown>
                       ) : (
                         <span className="text-muted-foreground italic">분석 중입니다... (약 10~30초 소요)</span>
                       )}
                    </div>
                  </CardContent>
                </Card>

              </div>
            )}
          </TabsContent>
          
          <TabsContent value="reports" className="w-full mt-4 sm:mt-6">
            {/* Reports List */}
            <Card className="bg-card border-border shadow-sm">
              <CardHeader className="pb-3 px-4 pt-4 border-b border-border/40">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Database size={16} />
                  <span className="text-xs font-bold uppercase tracking-wider">Reports Library</span>
                  <span className="ml-auto text-xs text-muted-foreground/60">{reports.length}개</span>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {reports.length === 0 ? (
                  <div className="p-10 text-sm text-muted-foreground italic text-center">리포트가 없습니다</div>
                ) : (
                  <div className="divide-y divide-border/40">
                    {reports.map((r) => {
                      const date = new Date(r.modified * 1000).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                      const sizeKb = r.size ? `${(r.size / 1024).toFixed(1)} KB` : '';
                      return (
                        <button
                          key={r.filename}
                          onClick={() => viewReport(r.filename)}
                          className="w-full px-4 py-3 text-left hover:bg-muted/40 transition-colors flex items-center gap-3 group"
                        >
                          <div className="h-9 w-9 rounded-lg bg-rose-500/10 border border-rose-500/20 flex items-center justify-center flex-shrink-0">
                            <FileText size={16} className="text-rose-400" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium truncate text-foreground group-hover:text-rose-400 transition-colors">{r.filename.replace('.md', '')}</p>
                            <p className="text-xs text-muted-foreground mt-0.5">{date}{sizeKb && ` · ${sizeKb}`}</p>
                          </div>
                          <ChevronRight size={16} className="text-muted-foreground/40 group-hover:text-muted-foreground transition-colors flex-shrink-0" />
                        </button>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Report Modal Viewer */}
            {selectedReport && reportContent && (
              <div
                className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
                onClick={() => { setSelectedReport(null); setReportContent(''); }}
              >
                <div
                  className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-4xl flex flex-col"
                  style={{ maxHeight: '92vh' }}
                  onClick={e => e.stopPropagation()}
                >
                  {/* Modal Header */}
                  <div className="flex items-center justify-between px-5 py-3 border-b border-border/40 bg-muted/30 rounded-t-xl flex-shrink-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <FileText size={15} className="text-rose-400 flex-shrink-0" />
                      <span className="text-sm font-medium truncate">{selectedReport.replace('.md', '')}</span>
                      {reports.find(r => r.filename === selectedReport)?.size && (
                        <span className="text-xs text-muted-foreground flex-shrink-0">· {(reports.find(r => r.filename === selectedReport)!.size / 1024).toFixed(1)} KB</span>
                      )}
                    </div>
                    <button
                      onClick={() => { setSelectedReport(null); setReportContent(''); }}
                      className="ml-3 flex-shrink-0 h-7 w-7 rounded-md flex items-center justify-center hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
                    >
                      <X size={16} />
                    </button>
                  </div>
                  {/* Modal Content — only this scrolls */}
                  <div className="overflow-y-auto overflow-x-hidden p-4 sm:p-8">
                    <div className="prose prose-zinc dark:prose-invert max-w-none
                      prose-headings:font-semibold prose-headings:text-foreground prose-headings:tracking-tight
                      prose-h1:text-[1.8em] prose-h1:pb-[0.3em] prose-h1:border-b prose-h1:border-border prose-h1:mb-4 prose-h1:mt-6
                      prose-h2:text-[1.4em] prose-h2:pb-[0.3em] prose-h2:border-b prose-h2:border-border prose-h2:mt-6 prose-h2:mb-4
                      prose-h3:text-[1.2em] prose-h3:mt-6 prose-h3:mb-4
                      prose-p:text-[15px] prose-p:leading-[1.6] prose-p:my-3
                      prose-a:text-blue-500 hover:prose-a:underline prose-a:no-underline
                      prose-blockquote:border-l-[0.25em] prose-blockquote:border-border prose-blockquote:pl-4 prose-blockquote:text-muted-foreground prose-blockquote:my-4
                      prose-table:border-collapse prose-table:border prose-table:border-border prose-table:my-4 prose-table:min-w-full
                      prose-th:bg-muted/50 prose-th:border prose-th:border-border prose-th:px-3 prose-th:py-1.5 prose-th:font-semibold prose-th:text-left prose-th:whitespace-nowrap
                      prose-td:border prose-td:border-border prose-td:px-3 prose-td:py-1.5
                      prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded-md prose-code:text-foreground prose-code:font-mono prose-code:text-[85%] prose-code:before:content-none prose-code:after:content-none
                      prose-pre:bg-muted/50 prose-pre:border prose-pre:border-border prose-pre:p-4 prose-pre:rounded-lg prose-pre:my-4 prose-pre:overflow-x-auto
                      prose-li:my-1
                      [&_table]:block [&_table]:overflow-x-auto [&_table]:w-full
                    ">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{reportContent}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </TabsContent>

          <TabsContent value="trades" className="w-full mt-6">
             {(() => {
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
                 <>
                   <div className="flex flex-col md:flex-row gap-6 mb-6">
                     {/* Summary Card */}
                     <Card className="flex-1 bg-card border-border shadow-sm">
                       <CardContent className="p-6 flex flex-wrap items-center justify-between gap-6">
                         <div className="flex flex-col gap-1">
                           <span className="text-sm font-medium text-muted-foreground uppercase tracking-wider">총 매매 횟수</span>
                           <div className="flex items-end gap-2">
                             <span className="text-3xl font-black">{totalTrades}</span>
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
                           <span className={`text-3xl font-black ${totalProfit > 0 ? 'text-green-500' : totalProfit < 0 ? 'text-rose-500' : 'text-foreground'}`}>
                             {totalProfit > 0 ? '+' : ''}{totalProfit.toLocaleString()}
                           </span>
                         </div>
                         <div className="flex flex-col gap-2 min-w-[200px] border-l border-border pl-6">
                           <span className="text-sm font-medium text-muted-foreground uppercase tracking-wider">날짜 필터</span>
                           <input 
                             type="date" 
                             className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                             value={tradeDate}
                             onChange={(e) => setTradeDate(e.target.value)}
                           />
                         </div>
                       </CardContent>
                     </Card>
                   </div>

                   <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
               <Card className="bg-card border-border">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                       <BarChart size={18} className="text-rose-500" /> Scalping History
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="rounded-md border border-border">
                      <Table>
                        <TableHeader className="bg-muted border-b border-border">
                          <TableRow className="hover:bg-transparent">
                            <TableHead className="text-muted-foreground">Date</TableHead>
                            <TableHead className="text-muted-foreground">Code</TableHead>
                            <TableHead className="text-muted-foreground">P/L %</TableHead>
                            <TableHead className="text-muted-foreground text-right">Profit (₩)</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {filteredScalp.length === 0 ? (
                            <TableRow><TableCell colSpan={4} className="text-center py-6 text-muted-foreground">No scalping trades found.</TableCell></TableRow>
                          ) : (
                            filteredScalp.map((log: any, i: number) => (
                              <TableRow key={i} className="border-border hover:bg-muted/50 hover:bg-muted">
                                <TableCell className="text-foreground/80 font-mono text-xs">{log.timestamp || log.sell_time}</TableCell>
                                <TableCell className="text-foreground/80 font-medium">
                                  {log.name && log.code ? `${log.name} (${log.code})` : log.code}
                                </TableCell>
                                <TableCell className={parseFloat(log.pnl_rate) > 0 ? "text-green-400" : "text-rose-400"}>
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
               <Card className="bg-card border-border">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                       <BarChart size={18} className="text-orange-400" /> Swing & Batch History
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="rounded-md border border-border">
                      <Table>
                        <TableHeader className="bg-muted border-b border-border">
                          <TableRow className="hover:bg-transparent">
                            <TableHead className="text-muted-foreground">Date</TableHead>
                            <TableHead className="text-muted-foreground">Code</TableHead>
                            <TableHead className="text-muted-foreground">P/L %</TableHead>
                            <TableHead className="text-muted-foreground text-right">Profit (₩)</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {filteredSwing.length === 0 ? (
                            <TableRow><TableCell colSpan={4} className="text-center py-6 text-muted-foreground">No swing trades found yet.</TableCell></TableRow>
                          ) : (
                            filteredSwing.map((log: any, i: number) => (
                              <TableRow key={i} className="border-border hover:bg-muted/50 hover:bg-muted">
                                <TableCell className="text-foreground/80 font-mono text-xs">{log.timestamp || log.sell_time}</TableCell>
                                <TableCell className="text-foreground/80 font-medium">
                                  {log.name && log.code ? `${log.name} (${log.code})` : log.code}
                                </TableCell>
                                <TableCell className={parseFloat(log.pnl_rate) > 0 ? "text-green-400" : "text-rose-400"}>
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
               );
             })()}
          </TabsContent>
        </div>{/* /content */}
      </Tabs>
    </div>
  );
}
