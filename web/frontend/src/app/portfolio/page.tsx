/* eslint-disable */
"use client";

import { useState, useEffect } from "react";
import { Briefcase, Loader2, DollarSign, Wallet } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const API_BASE = "http://localhost:8000/api";

export default function Portfolio() {
  const [portfolio, setPortfolio] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const fetchPortfolio = async () => {
    try {
      const res = await fetch(`${API_BASE}/portfolio`);
      const data = await res.json();
      setPortfolio(data);
    } catch (e) {
      console.error("Could not fetch portfolio", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
    const interval = setInterval(fetchPortfolio, 10000);
    return () => clearInterval(interval);
  }, []);

  const renderPortfolioCard = (data: any, title: string, isPaper: boolean) => {
    if (!data) return null;
    
    // Safety destructure based on what DataService actually returns
    const cash = data.deposit || data.cash || data.d2_deposit || 0;
    const total = data.total_asset || data.total_assets || cash;
    const holdList = data.holdings || []; // Depends on how KISManager wraps the response

    return (
      <Card className="bg-card/40 backdrop-blur-xl border-border/50 shadow-xl w-full">
        <CardHeader className="pb-3 border-b border-border/40">
          <CardTitle className="flex items-center gap-2 text-xl font-bold">
            <Wallet className={isPaper ? "text-blue-400" : "text-emerald-500"} />
            {title}
            {isPaper && <span className="ml-2 text-xs font-semibold bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded-full border border-blue-500/30">PAPER</span>}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid grid-cols-2 gap-4 mb-8">
            <div className="flex flex-col gap-1 p-4 bg-muted/20 border border-border/30 rounded-xl">
              <span className="text-sm font-medium text-muted-foreground flex items-center gap-1"><DollarSign size={14}/> Total Assets</span>
              <span className="text-3xl font-black text-foreground">{parseInt(total).toLocaleString()} ₩</span>
            </div>
            <div className="flex flex-col gap-1 p-4 bg-muted/20 border border-border/30 rounded-xl">
              <span className="text-sm font-medium text-muted-foreground flex items-center gap-1"><DollarSign size={14}/> Available Cash (D+2)</span>
              <span className="text-3xl font-black text-foreground">{parseInt(cash).toLocaleString()} ₩</span>
            </div>
          </div>

          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">Current Holdings</h3>
          <div className="rounded-lg border border-border/40 overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/30">
                <TableRow className="border-border/40 hover:bg-transparent">
                  <TableHead className="font-semibold text-muted-foreground text-left">Code</TableHead>
                  <TableHead className="font-semibold text-muted-foreground text-right">Qty</TableHead>
                  <TableHead className="font-semibold text-muted-foreground text-right">Buy Price</TableHead>
                  <TableHead className="font-semibold text-muted-foreground text-right">Current</TableHead>
                  <TableHead className="font-semibold text-muted-foreground text-right">P/L %</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {holdList.length === 0 ? (
                  <TableRow><TableCell colSpan={5} className="text-center py-8 text-muted-foreground">No active positions.</TableCell></TableRow>
                ) : (
                  holdList.map((pos: any, idx: number) => {
                    // Extract values adapting to typical Open API responses
                    const code = pos.pdno || pos.code || "Unknown";
                    const qty = pos.hldg_qty || pos.qty || 0;
                    const buyPrice = pos.pchs_avg_pric || pos.buy_price || 0;
                    const currentPrice = pos.prpr || pos.current_price || 0;
                    const pnlPct = pos.evlu_pfls_rt || pos.profit_rate || pos.pnl_rate || 0;
                    const isWin = parseFloat(pnlPct) > 0;
                    
                    return (
                      <TableRow key={idx} className="border-border/30 hover:bg-white/5">
                        <TableCell className="font-medium text-foreground">{code}</TableCell>
                        <TableCell className="text-right text-foreground/80 font-mono">{parseInt(qty).toLocaleString()}</TableCell>
                        <TableCell className="text-right text-foreground/80 font-mono">{parseInt(buyPrice).toLocaleString()}</TableCell>
                        <TableCell className="text-right text-foreground/80 font-mono">{parseInt(currentPrice).toLocaleString()}</TableCell>
                        <TableCell className={`text-right font-medium ${isWin ? 'text-green-500' : 'text-rose-500'}`}>
                          {parseFloat(pnlPct).toFixed(2)}%
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-8 py-8 animate-in fade-in duration-500">
      <header className="flex items-center justify-between pb-6 mb-6 border-b border-border/40">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Briefcase className="text-emerald-500" />
            Portfolio Manager
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Real-time asset tracking and open positions monitor.</p>
        </div>
      </header>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
          <p className="text-sm">Fetching KIS API account balance...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
          {renderPortfolioCard(portfolio?.real, "Real Account", false)}
          {renderPortfolioCard(portfolio?.paper, "Paper Account", true)}
        </div>
      )}
    </div>
  );
}
