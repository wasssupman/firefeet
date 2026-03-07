/* eslint-disable */
"use client";

import { useState, useEffect } from "react";
import { Activity, ThermometerSun, RefreshCw, TrendingUp, Terminal, Send } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ThemeToggle } from "@/components/theme-toggle";

const API_BASE = "http://localhost:8000/api";

export default function Dashboard() {
  const [marketTemp, setMarketTemp] = useState<any>(null);
  const [marketSummary, setMarketSummary] = useState<any>(null);
  const [marketPrediction, setMarketPrediction] = useState<any>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const [outsideHours, setOutsideHours] = useState(false);
  const [discordSending, setDiscordSending] = useState<string | null>(null);

  const sendToDiscord = async (type: string, customMessage?: string) => {
    setDiscordSending(type);
    try {
      const res = await fetch(`${API_BASE}/discord/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: customMessage || "", type }),
      });
      if (!res.ok) {
        const err = await res.json();
        alert(`전송 실패: ${err.detail}`);
      }
    } catch (e) {
      alert("Discord 전송 중 오류 발생");
    } finally {
      setDiscordSending(null);
    }
  };

  const fetchMarketPrediction = async (force = false) => {
    const qs = force ? "?force=true" : "";
    try {
      const predRes = await fetch(`${API_BASE}/market/prediction${qs}`);
      if (predRes.ok) {
        const predData = await predRes.json();
        setMarketPrediction(predData);
      }
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

      if (tempRes.ok) {
        const tempData = await tempRes.json();
        if (tempData.outside_hours && !tempData.score) {
          setOutsideHours(true);
        } else {
          setOutsideHours(false);
          setMarketTemp(tempData);
        }
      }
      if (sumRes.ok) {
        const sumData = await sumRes.json();
        if (!sumData.outside_hours) setMarketSummary(sumData);
      }
    } catch (e) {
      console.error("Could not fetch market insights", e);
    } finally {
      setMarketLoading(false);
    }
    fetchMarketPrediction(force);
  };

  useEffect(() => {
    fetchMarketInsights();
  }, []);

  return (
    <div className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-8 py-8">
      <header className="flex items-center justify-between pb-6 mb-6 border-b border-border/40">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Market Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-1">AI-driven macro and narrative analysis to gauge market risk.</p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={() => fetchMarketInsights(true)} disabled={marketLoading} className="gap-2">
            <RefreshCw size={14} className={marketLoading ? "animate-spin" : ""} />
            Force Refresh
          </Button>
          <ThemeToggle />
        </div>
      </header>

      {outsideHours && !marketTemp && (
        <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 flex items-center gap-3">
          <ThermometerSun size={20} className="text-amber-500 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-400">장 외 시간</p>
            <p className="text-xs text-muted-foreground mt-0.5">시장 분석은 평일 08:00~15:00 (KST)에만 실행됩니다. 캐시된 데이터가 있으면 마지막 분석 결과가 표시됩니다.</p>
          </div>
        </div>
      )}

      {marketLoading && !marketTemp ? (
        <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-4">
          <Activity className="w-8 h-8 animate-pulse text-rose-500" />
          <p className="text-sm text-center px-4 animate-pulse">Analyzing market conditions and fetching AI sentiment...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <Card className="bg-card/50 backdrop-blur-xl border-border/60 xl:col-span-1 shadow-2xl shadow-black/20">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg flex items-center gap-2 text-foreground">
                <ThermometerSun size={18} className="text-orange-500" />
                Temperature
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col items-center justify-center py-8">
                <span className="text-7xl font-black tracking-tighter mb-2 bg-clip-text text-transparent bg-gradient-to-b from-foreground to-foreground/50">
                  {marketTemp?.score ?? 0}°
                </span>
                <Badge variant="outline" className={`text-md px-4 py-1.5 font-bold tracking-wider ${
                  marketTemp?.level === 'HOT' ? 'border-red-500/50 text-red-500 bg-red-500/10 shadow-[0_0_15px_rgba(239,68,68,0.2)]' :
                  marketTemp?.level === 'WARM' ? 'border-orange-500/50 text-orange-500 bg-orange-500/10 shadow-[0_0_15px_rgba(249,115,22,0.2)]' :
                  marketTemp?.level === 'COOL' ? 'border-blue-400/50 text-blue-400 bg-blue-400/10 shadow-[0_0_15px_rgba(96,165,250,0.2)]' :
                  marketTemp?.level === 'COLD' ? 'border-blue-600/50 text-blue-600 bg-blue-600/10 shadow-[0_0_15px_rgba(37,99,235,0.2)]' :
                  'border-zinc-500/50 text-zinc-400 bg-zinc-500/10'
                }`}>
                  {marketTemp?.level ?? 'UNKNOWN'}
                </Badge>
              </div>
              <div className="space-y-3 mt-4">
                <div className="flex justify-between items-center text-sm border-b border-border/40 pb-2">
                  <span className="text-muted-foreground">Macro (40%)</span>
                  <span className={`font-medium ${marketTemp?.details?.macro?.score > 0 ? 'text-green-500' : 'text-red-500'}`}>{marketTemp?.details?.macro?.score > 0 ? '+' : ''}{marketTemp?.details?.macro?.score ?? 0}</span>
                </div>
                <div className="flex justify-between items-center text-sm border-b border-border/40 pb-2">
                  <span className="text-muted-foreground">Econ (30%)</span>
                  <span className={`font-medium ${marketTemp?.details?.econ?.score > 0 ? 'text-green-500' : 'text-red-500'}`}>{marketTemp?.details?.econ?.score > 0 ? '+' : ''}{marketTemp?.details?.econ?.score ?? 0}</span>
                </div>
                <div className="flex justify-between items-center text-sm pb-1">
                  <span className="text-muted-foreground">Sentiment (30%)</span>
                  <span className={`font-medium ${marketTemp?.details?.sentiment?.score > 0 ? 'text-green-500' : 'text-red-500'}`}>{marketTemp?.details?.sentiment?.score > 0 ? '+' : ''}{marketTemp?.details?.sentiment?.score ?? 0}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card/50 backdrop-blur-xl border-border/60 xl:col-span-2 shadow-2xl flex flex-col">
            <CardHeader className="pb-3 border-b border-border/40">
              <div className="flex justify-between items-start">
                <CardTitle className="text-lg flex items-center gap-2 text-foreground">
                  <Activity size={18} className="text-blue-400" />
                  AI Market Narrative
                </CardTitle>
                {marketSummary?.sentiment && (
                  <Badge variant="secondary" className={`uppercase tracking-wider text-xs ${
                    marketSummary.sentiment.toLowerCase() === 'bullish' ? 'bg-green-500/10 text-green-500 border border-green-500/20' :
                    marketSummary.sentiment.toLowerCase() === 'bearish' ? 'bg-red-500/10 text-red-500 border border-red-500/20' :
                    'bg-zinc-500/10 text-zinc-400 border border-zinc-500/20'
                  }`}>
                    {marketSummary.sentiment}
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="pt-6 flex-1">
              <div className="bg-muted/20 p-5 rounded-lg border border-border/30 h-full shadow-inner">
                 <p className="text-[15px] leading-[1.8] text-foreground/90 whitespace-pre-wrap">
                   {marketSummary?.narrative ?? "AI summary not available."}
                 </p>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-[#1e1f22]/90 backdrop-blur-xl border-border/20 xl:col-span-3 shadow-2xl rounded-xl mt-2">
            <CardHeader className="pb-3 border-b border-white/5 bg-[#2b2d31]">
              <div className="flex items-center justify-between">
                <CardTitle className="text-[15px] font-semibold flex items-center gap-2 text-white/90">
                  <Terminal size={16} className="text-zinc-400" />
                  discord-broadcast
                </CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2.5 text-xs text-white/50 hover:text-white hover:bg-white/10 gap-1.5"
                  disabled={!marketTemp?.discord_report || discordSending === "temperature"}
                  onClick={() => sendToDiscord("temperature")}
                >
                  <Send size={12} className={discordSending === "temperature" ? "animate-pulse" : ""} />
                  {discordSending === "temperature" ? "전송중..." : "Discord 전송"}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="pt-4 bg-[#313338]">
              <div className="flex gap-4">
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
                  {marketTemp ? (
                    <div className="space-y-3 text-[14px]">
                      {/* 매크로 */}
                      {(() => {
                        const macro = marketTemp.details?.macro;
                        const macroScore = marketTemp.components?.macro ?? 0;
                        if (!macro) return null;
                        const items = Object.entries(macro).filter(([, v]: [string, any]) => v && typeof v === 'object' && v.trend_info);
                        return (
                          <div className="bg-white/[0.03] rounded-lg p-3 border border-white/5">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-[13px] font-semibold text-white/80">📊 매크로 추세</span>
                              <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${macroScore > 0 ? 'bg-green-500/15 text-green-400' : macroScore < 0 ? 'bg-red-500/15 text-red-400' : 'bg-zinc-500/15 text-zinc-400'}`}>{macroScore > 0 ? '+' : ''}{macroScore.toFixed(0)}</span>
                            </div>
                            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                              {items.map(([key, val]: [string, any]) => {
                                const info = val.trend_info;
                                const changes = info?.daily_changes || [];
                                const latest = changes[changes.length - 1] ?? 0;
                                const trend = info?.trend;
                                return (
                                  <div key={key} className="flex items-center justify-between text-[13px]">
                                    <span className="text-white/50">{val.label || key}</span>
                                    <div className="flex items-center gap-1.5">
                                      <span className={`font-mono ${latest > 0 ? 'text-green-400' : latest < 0 ? 'text-red-400' : 'text-zinc-400'}`}>{latest > 0 ? '+' : ''}{latest.toFixed(2)}%</span>
                                      <span className="text-[11px]">{trend === 'UP' ? '📈' : trend === 'DOWN' ? '📉' : '➡️'}</span>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })()}

                      {/* 뉴스 감성 */}
                      {(() => {
                        const sentiment = marketTemp.details?.sentiment;
                        const sentScore = marketTemp.components?.sentiment ?? 0;
                        if (!sentiment) return null;
                        const sources = sentiment.sources || {};
                        const trend = sentiment.trend || 'STABLE';
                        const trendColor = trend === 'IMPROVING' ? 'text-green-400' : trend === 'WORSENING' ? 'text-red-400' : 'text-zinc-400';
                        return (
                          <div className="bg-white/[0.03] rounded-lg p-3 border border-white/5">
                            <div className="flex items-center justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <span className="text-[13px] font-semibold text-white/80">📰 뉴스 감성</span>
                                <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${sentScore > 0 ? 'bg-green-500/15 text-green-400' : sentScore < 0 ? 'bg-red-500/15 text-red-400' : 'bg-zinc-500/15 text-zinc-400'}`}>{sentScore > 0 ? '+' : ''}{sentScore.toFixed(0)}</span>
                              </div>
                              <span className={`text-xs font-medium ${trendColor}`}>{trend === 'IMPROVING' ? '↗ 개선' : trend === 'WORSENING' ? '↘ 악화' : '→ 유지'}</span>
                            </div>
                            <div className="space-y-1">
                              {Object.entries(sources).map(([src, data]: [string, any]) => {
                                const pos = data?.positive ?? 0;
                                const neg = data?.negative ?? 0;
                                const total = pos + neg || 1;
                                const posRatio = (pos / total) * 100;
                                return (
                                  <div key={src} className="flex items-center gap-2 text-[13px]">
                                    <span className="text-white/50 w-16 flex-shrink-0">{src === 'korea' ? '한국' : '해외'}</span>
                                    <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
                                      <div className="h-full bg-gradient-to-r from-green-500/60 to-green-400/40 rounded-full" style={{width: `${posRatio}%`}} />
                                    </div>
                                    <span className="text-white/40 text-[12px] font-mono w-20 text-right">
                                      <span className="text-green-400/70">{pos}</span>
                                      <span className="text-white/20"> / </span>
                                      <span className="text-red-400/70">{neg}</span>
                                    </span>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })()}

                      {/* 경제 지표 */}
                      {(() => {
                        const econScore = marketTemp.components?.econ ?? 0;
                        return (
                          <div className="bg-white/[0.03] rounded-lg p-3 border border-white/5">
                            <div className="flex items-center gap-2">
                              <span className="text-[13px] font-semibold text-white/80">📅 경제 지표</span>
                              <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${econScore > 0 ? 'bg-green-500/15 text-green-400' : econScore < 0 ? 'bg-red-500/15 text-red-400' : 'bg-zinc-500/15 text-zinc-400'}`}>{econScore > 0 ? '+' : ''}{econScore.toFixed(0)}</span>
                              {econScore === 0 && <span className="text-[12px] text-white/30">금일 주요 이벤트 없음</span>}
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  ) : (
                    <span className="text-white/30 italic text-sm">데이터 로딩 중...</span>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card/50 backdrop-blur-xl border-border/60 xl:col-span-3 shadow-2xl flex flex-col mt-2">
            <CardHeader className="pb-3 border-b border-border/40">
              <div className="flex items-center justify-between">
                <CardTitle className="text-[16px] font-semibold flex items-center gap-2 text-foreground">
                  <TrendingUp size={18} className="text-purple-400" />
                  내일의 한국 증시 예측 리포트 (By AI)
                </CardTitle>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 px-2.5 text-xs gap-1.5"
                  disabled={!marketPrediction?.prediction || discordSending === "prediction"}
                  onClick={() => sendToDiscord("prediction")}
                >
                  <Send size={12} className={discordSending === "prediction" ? "animate-pulse" : ""} />
                  {discordSending === "prediction" ? "전송중..." : "Discord 전송"}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="pt-4 pb-4">
              <div className="bg-muted/20 px-5 py-4 rounded-lg border border-border/30 text-[14px] text-foreground/90 font-sans prose prose-sm prose-zinc dark:prose-invert max-w-none prose-p:my-1 prose-p:leading-[1.5] prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-1.5 prose-headings:text-[15px] prose-ul:my-1 prose-li:my-0 prose-li:leading-[1.5] prose-hr:my-2 prose-blockquote:my-1.5 [&_h1]:text-base [&_h2]:text-[15px] [&_h3]:text-[14px] [&_h2]:border-b [&_h2]:border-border/20 [&_h2]:pb-1">
                 {marketPrediction?.prediction ? (
                   <ReactMarkdown remarkPlugins={[remarkGfm]}>
                     {marketPrediction.prediction}
                   </ReactMarkdown>
                 ) : (
                   <div className="flex items-center gap-3 text-muted-foreground italic text-sm">
                     <RefreshCw className="w-4 h-4 animate-spin" />
                     분석 중입니다... (약 10~30초 소요)
                   </div>
                 )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
