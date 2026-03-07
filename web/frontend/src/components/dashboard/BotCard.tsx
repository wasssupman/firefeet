/* eslint-disable */
"use client";

import { useState, useEffect } from "react";
import { Play, Square, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { LogViewer } from "@/components/dashboard/LogViewer";

const API_BASE = "http://localhost:8000/api";

type BotID = "scalping" | "swing" | "ai_swing" | "batch_reports";
type BotStatus = "RUNNING" | "STOPPED";

export const BOT_LABELS: Record<BotID, { name: string, desc: string }> = {
  scalping: { name: "⚡ 당일 초단타 매매 (Scalping)", desc: "거래량 집중 종목 스캘핑 및 즉시 익/손절" },
  swing: { name: "📈 변동성 돌파 스윙 (Swing)", desc: "수급 기반 우량주 종가 매수 및 단기 보유" },
  ai_swing: { name: "🤖 AI 자동 분석 매매 (AI Swing)", desc: "당일 테마 분석 및 AI 재무/수급 분석 후 익일 매수" },
  batch_reports: { name: "📚 딥 리서치 자동화 (Reporter)", desc: "장 마감 후 주도주 스크리닝 및 심층 마크다운 리포트 생성" },
};

const PAPER_TRADABLE: BotID[] = ["scalping", "swing", "ai_swing"];

export function BotCard({ botId, status, onStatusChange }: { botId: BotID; status: BotStatus; onStatusChange: () => void }) {
  const [isLoading, setIsLoading] = useState(false);
  const [deepAnalysisEnabled, setDeepAnalysisEnabled] = useState(false);
  const [paperMode, setPaperMode] = useState(false);
  const [compactPrompt, setCompactPrompt] = useState(false);
  const info = BOT_LABELS[botId];
  const supportsPaper = PAPER_TRADABLE.includes(botId);

  useEffect(() => {
    if (botId === "ai_swing") {
      fetch(`${API_BASE}/config/ai-settings`).then(r => r.json()).then(d => setCompactPrompt(d.compact_prompt)).catch(() => {});
    }
  }, [botId]);

  const handleCompactToggle = async (checked: boolean) => {
    setCompactPrompt(checked);
    await fetch(`${API_BASE}/config/ai-settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ compact_prompt: checked }),
    }).catch(() => {});
  };

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
    <Card className="bg-card/40 backdrop-blur-xl border-border/50 shadow-2xl w-full flex flex-col relative overflow-hidden group transition-all hover:bg-card/60">
      {status === "RUNNING" && (
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-emerald-400 to-green-500 shadow-[0_0_10px_rgba(52,211,153,0.5)]"></div>
      )}
      <CardHeader className="pb-3">
        <div className="flex justify-between items-start">
          <div>
            <CardTitle className="text-xl text-foreground font-semibold tracking-tight">{info.name}</CardTitle>
            <CardDescription className="text-muted-foreground mt-1.5 leading-relaxed">{info.desc}</CardDescription>
          </div>
          <Badge variant={status === "RUNNING" ? "default" : "secondary"} className={status === "RUNNING" ? "bg-green-500/10 text-green-400 hover:bg-green-500/20 shadow-[inset_0_0_0_1px_rgba(74,222,128,0.2)]" : "shadow-[inset_0_0_0_1px_rgba(255,255,255,0.1)]"}>
            {status}
          </Badge>
        </div>

        {/* 모의투자 토글 */}
        {supportsPaper && (
          <div className="flex items-center gap-3 mt-5 pt-4 border-t border-border/40">
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
              <span className="text-xs font-semibold text-blue-400 ml-auto border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 rounded-full shadow-[0_0_10px_rgba(59,130,246,0.15)]">
                PAPER
              </span>
            ) : (
              <span className="text-xs font-semibold text-rose-400 ml-auto border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 rounded-full">
                REAL 💸
              </span>
            )}
          </div>
        )}

        {/* 경량 프롬프트 토글 */}
        {botId === "ai_swing" && (
          <div className="flex items-center gap-3 mt-4 pt-4 border-t border-border/40">
            <Switch
              checked={compactPrompt}
              onCheckedChange={handleCompactToggle}
              disabled={status === "RUNNING"}
              id={`compact-prompt-switch-${botId}`}
              className="data-[state=checked]:bg-amber-500"
            />
            <label htmlFor={`compact-prompt-switch-${botId}`} className="text-sm font-medium text-foreground/80 cursor-pointer select-none">
              경량 프롬프트 (비용절감)
            </label>
            {compactPrompt && (
              <span className="text-xs font-semibold text-amber-400 ml-auto border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 rounded-full">
                COMPACT
              </span>
            )}
          </div>
        )}

        {/* 딥 리서치 토글 */}
        {botId === "batch_reports" && (
          <div className="flex items-center gap-3 mt-4 pt-4 border-t border-border/40">
            <Switch 
              checked={deepAnalysisEnabled} 
              onCheckedChange={setDeepAnalysisEnabled}
              disabled={status === "RUNNING"}
              id="deep-analysis-switch"
              className="data-[state=checked]:bg-purple-500"
            />
            <label htmlFor="deep-analysis-switch" className="text-sm font-medium text-foreground/80 cursor-pointer">
              3단계 딥 리서치 (OpenAI O1)
            </label>
            {!deepAnalysisEnabled && <span className="text-xs font-medium text-purple-400 ml-auto border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 rounded-full">Stage 2 Only</span>}
          </div>
        )}
      </CardHeader>
      <CardContent className="flex-1">
        <LogViewer botId={botId} status={status} />
      </CardContent>
      <CardFooter className="pt-2 pb-5 px-6">
        <Button 
          variant={status === "RUNNING" ? "destructive" : "default"} 
          className={`w-full font-semibold transition-all h-11 ${status === 'RUNNING' ? 'shadow-[0_0_15px_rgba(239,68,68,0.3)] hover:shadow-[0_0_20px_rgba(239,68,68,0.5)]' : 'shadow-lg'}`}
          onClick={handleToggle}
          disabled={isLoading}
        >
          {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : status === "RUNNING" ? <Square className="mr-2 h-4 w-4 fill-current" /> : <Play className="mr-2 h-4 w-4 fill-current" />}
          {status === "RUNNING" ? "Terminate Process" : (supportsPaper && paperMode ? "Engage Bot (Paper)" : "Engage Bot (REAL)")}
        </Button>
      </CardFooter>
    </Card>
  );
}
