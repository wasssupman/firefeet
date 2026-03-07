import os
import json
import datetime
import logging
import fcntl
from core.interfaces.llm import IAnalystLLM, IExecutorLLM
from core.analysis.llms.claude_analyst import ClaudeAnalyst
from core.analysis.llms.claude_executor import ClaudeExecutor
from core.analysis.llms.vision_analyst import VisionAnalyst
from core.config_loader import ConfigLoader

class AISwingAgent:
    """
    AI Swing Trading Agent (Orchestrator Pattern)
    Coordinates a Dual-LLM pipeline:
    1. Analyst (e.g., Claude) digests massive data into a detailed Markdown report.
    2. Executor (e.g., Claude) reads the report and hard facts to output strict JSON execution orders.
    """
    
    def __init__(self, config_path="config/deep_analysis.yaml", analyst: IAnalystLLM = None, executor: IExecutorLLM = None):
        self.logger = logging.getLogger("AISwingAgent")
        
        # Load configs
        import yaml
        self.config = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
                
        orch_config = self.config.get("orchestrator", {})
        self.analyst_timeout = orch_config.get("analyst_timeout_sec", 30.0)
        self.fallback_allowed = orch_config.get("fallback_on_analyst_fail", True)
        self.max_daily_calls = orch_config.get("max_daily_calls", 15)
        self.usage_file = "logs/ai_usage.json"
        
        # Dependency Injection (Defaults to Claude -> Claude -> Vision)
        compact = orch_config.get("compact_prompt", False)
        self.analyst = analyst if analyst else ClaudeAnalyst(compact_prompt=compact)
        self.executor = executor if executor else ClaudeExecutor(compact_prompt=compact)
        self.vision = VisionAnalyst()
        
    def analyze_trading_opportunity(self, code: str, name: str, data: dict) -> dict:
        """
        Orchestrates the Dual-LLM workflow to arrive at a trading decision.
        """
        self.logger.info(f"[{name}({code})] Deep Analysis Orchestrator started.")
        
        # Extract Hard Facts to ground the Executor LLM (prevents hallucination)
        curr = data.get("current_data", {})
        current_price = curr.get("price", 0)
        screener_score = data.get("screener_score", 0)
        
        hard_facts = {
            "current_price": current_price,
            "score": screener_score
        }
        
        # --- Pre-Check: Daily Budget / Quota Check ---
        if not self._check_and_increment_quota():
            self.logger.warning(f"[{name}({code})] Daily Pro Model API limit ({self.max_daily_calls}) reached. Forcing WAIT.")
            fallback = self._safe_fallback_json()
            fallback["reasoning"] = f"DAILY AI QUOTA EXCEEDED ({self.max_daily_calls} calls). Wait until tomorrow."
            return fallback

        memo = ""
        
        # --- Phase 1: Analyst ---
        try:
            self.logger.info(f"[{name}({code})] Phase 1: Analyst evaluating data...")
            memo = self.analyst.analyze(code, name, data)
            self.logger.info(f"[{name}({code})] Phase 1: Analyst Memo generated successfully.")
        except Exception as e:
            self.logger.error(f"[{name}({code})] Phase 1 Analyst Failure: {e}")
            if self.fallback_allowed:
                self.logger.warning(f"[{name}({code})] Falling back to Executor-only logic (Degraded Mode).")
                memo = "ANALYST FAILED. You must operate based purely on the hard facts provided and output a safe HOLD JSON decision if unsure."
            else:
                return self._safe_fallback_json()

        # --- Phase 2: Executor ---
        try:
             self.logger.info(f"[{name}({code})] Phase 2: Executor parsing Memo into Trading Order...")
             decision_json = self.executor.execute_decision(code, name, memo, hard_facts)

             # Decision summary log
             self.logger.info(
                 f"[{name}({code})] Phase 2 결과: {decision_json.get('decision', 'N/A')} "
                 f"(확신도: {decision_json.get('confidence', 0)}, "
                 f"전략: {decision_json.get('strategy_type', 'N/A')}) — "
                 f"{str(decision_json.get('reasoning', ''))[:100]}"
             )

             # Python-level sanity check
             decision_json = self._sanity_check(decision_json, hard_facts, code, name)
             
             # --- Phase 3: Vision AI Cross-Validation (only if BUY) ---
             if decision_json.get("decision") == "BUY":
                 self.logger.info(f"[{name}({code})] Phase 3: Vision AI chart cross-validation started...")
                 try:
                     from utils.chart_renderer import render_chart_to_bytes
                     chart_bytes = render_chart_to_bytes(code, period_days=60)
                     vision_result = self.vision.validate(chart_bytes, code, name)
                     if vision_result.get("action") == "REJECT":
                         self.logger.warning(
                             f"[{name}({code})] Phase 3 REJECTED by Vision AI "
                             f"(confidence={vision_result.get('confidence')}%, "
                             f"risk={vision_result.get('risk_level')}): "
                             f"{vision_result.get('reason')}"
                         )
                         decision_json["decision"] = "WAIT"
                         decision_json["reasoning"] = (
                             f"[Vision AI 기각] {vision_result.get('reason')} "
                             f"(Chart risk: {vision_result.get('risk_level')}, "
                             f"confidence: {vision_result.get('confidence')}%)"
                         )
                     else:
                         self.logger.info(
                             f"[{name}({code})] Phase 3 CONFIRMED by Vision AI "
                             f"(confidence={vision_result.get('confidence')}%). Proceeding with BUY."
                         )
                 except Exception as ve:
                     self.logger.warning(f"[{name}({code})] Phase 3 Vision check skipped due to error: {ve}")
             
             return decision_json
             
        except Exception as e:
             self.logger.error(f"[{name}({code})] Phase 2 Executor Failure: {e}")
             return self._safe_fallback_json()
             
    def _sanity_check(self, decision: dict, facts: dict, code: str, name: str) -> dict:
        """Ultimate Python-level verification of LLM output."""
        price = facts.get("current_price", 0)
        if price <= 0:
            return decision  # Cannot sanity check without price
            
        action = decision.get("decision", "HOLD")
        target = float(decision.get("target_price", 0))
        stop = float(decision.get("stop_loss", 0))
        
        if action == "BUY":
            # LLM이 target_price 또는 stop_loss를 미제공한 경우 (0값) → 매수 불가
            if target <= 0 or stop <= 0:
                self.logger.warning(f"[{name}({code})] LLM sanity check failed: missing target/stop. Target: {target}, Stop: {stop}. Overriding to WAIT.")
                decision["decision"] = "WAIT"
                decision["reasoning"] = f"OVERRIDDEN: Missing target_price or stop_loss from LLM. (Target: {target}, Stop: {stop})"
            # Sanity logic: target must be > price, stop must be < price
            elif target <= price or stop >= price:
                self.logger.warning(f"[{name}({code})] LLM sanity check failed. Price: {price}, Target: {target}, Stop: {stop}. Overriding to WAIT.")
                decision["decision"] = "WAIT"
                decision["reasoning"] = f"OVERRIDDEN: LLM suggested invalid logic. (Price: {price}, Target: {target}, Stop: {stop})"
                
        return decision

    def _safe_fallback_json(self) -> dict:
        """Ultimate fallback to keep trade loop alive."""
        return {
            "decision": "WAIT",
            "confidence": 0,
            "strategy_type": "NONE",
            "stop_loss": 0,
            "qty_ratio": 0.0,
            "reasoning": "Fallback Triggered."
        }
        
    def _check_and_increment_quota(self) -> bool:
        """Check if daily max runs is exceeded. Uses file locking for multi-process safety."""
        if self.max_daily_calls <= 0:
            return True  # Unlimited if set to 0

        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        # Ensure log dir exists
        os.makedirs(os.path.dirname(self.usage_file) or ".", exist_ok=True)

        try:
            # 파일 락으로 동시 접근 방지 (read-modify-write 원자적 실행)
            with open(self.usage_file, "a+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    content = f.read().strip()
                    if content:
                        usage_data = json.loads(content)
                        if usage_data.get("date") != today_str:
                            usage_data = {"date": today_str, "count": 0}
                    else:
                        usage_data = {"date": today_str, "count": 0}

                    if usage_data["count"] >= self.max_daily_calls:
                        self.logger.warning(f"일일 AI 호출 쿼터 초과: {usage_data['count']}/{self.max_daily_calls}")
                        return False

                    usage_data["count"] += 1

                    # 80% 경고
                    threshold_80 = int(self.max_daily_calls * 0.8)
                    if usage_data["count"] == threshold_80:
                        self.logger.warning(f"AI 호출 쿼터 80% 도달: {usage_data['count']}/{self.max_daily_calls}")

                    f.seek(0)
                    f.truncate()
                    json.dump(usage_data, f)
                    return True
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception as e:
            self.logger.warning(f"쿼터 파일 처리 실패 (안전하게 허용): {e}")
            return True
