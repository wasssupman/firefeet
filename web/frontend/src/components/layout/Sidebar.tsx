/* eslint-disable */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Terminal, LineChart, FileText, Activity, Database, Briefcase } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: Activity },
  { href: "/scalping", label: "Scalping", icon: Terminal },
  { href: "/swing", label: "Swing", icon: LineChart },
  { href: "/reports", label: "AI Reports", icon: FileText },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase },
  { href: "/trades", label: "Trades Log", icon: Database },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 border-r border-border/40 bg-background/50 backdrop-blur-xl flex flex-col h-screen fixed sticky top-0 left-0 hidden md:flex z-50">
      <div className="h-16 flex items-center px-6 border-b border-border/40 shrink-0">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-tr from-rose-500 to-orange-400 flex items-center justify-center shadow-lg shadow-rose-500/20">
            <Activity className="text-white w-4 h-4" />
          </div>
          <span className="font-bold text-lg tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-foreground to-foreground/70">
            Firefeet
          </span>
        </div>
      </div>
      
      <div className="flex-1 py-6 px-4 flex flex-col gap-2 overflow-y-auto">
        <div className="px-2 mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Command Center
        </div>
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-all group relative",
                isActive 
                  ? "text-foreground bg-rose-500/10 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)] border border-rose-500/20" 
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
              )}
            >
              {isActive && (
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-4 bg-rose-500 rounded-r-full" />
              )}
              <item.icon className={cn("w-4 h-4", isActive ? "text-rose-500" : "text-muted-foreground group-hover:text-foreground")} />
              {item.label}
            </Link>
          );
        })}
      </div>
      
      <div className="p-4 border-t border-border/40 shrink-0">
        <div className="bg-muted/50 rounded-lg p-3 border border-border/50">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Uplink Status</span>
            <span className="flex h-2 w-2 rounded-full bg-green-500 animate-pulse" />
          </div>
        </div>
      </div>
    </aside>
  );
}
