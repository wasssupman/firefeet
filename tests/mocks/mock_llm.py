"""Mock LLM classes for testing AI pipeline without real API calls."""

from core.interfaces.llm import IAnalystLLM, IExecutorLLM


class MockClaudeAnalyst(IAnalystLLM):
    """Mock Analyst that returns canned markdown memo."""

    def __init__(self, memo=None):
        self._memo = memo or "## Mock Analysis\n- Trend: Upward\n- Volume: High"
        self._calls = []

    def analyze(self, code, name, data):
        self._calls.append({"code": code, "name": name, "data": data})
        return self._memo

    def set_memo(self, memo):
        self._memo = memo

    def set_error(self):
        """Make next call raise an exception."""
        self._memo = None

    @property
    def call_count(self):
        return len(self._calls)


class MockClaudeExecutor(IExecutorLLM):
    """Mock Executor that returns canned decision JSON."""

    def __init__(self, decision=None):
        self._decision = decision or {
            "decision": "BUY",
            "confidence": 75,
            "strategy_type": "BREAKOUT",
            "target_price": 55000,
            "stop_loss": 47000,
            "qty_ratio": 0.5,
            "reasoning": "Mock: Strong upward momentum.",
        }
        self._calls = []

    def execute_decision(self, code, name, memo, facts):
        self._calls.append({
            "code": code, "name": name, "memo": memo, "facts": facts,
        })
        if self._decision is None:
            raise RuntimeError("Mock executor forced error")
        return dict(self._decision)  # return copy

    def set_decision(self, decision):
        self._decision = decision

    def set_error(self):
        """Make next call raise an exception."""
        self._decision = None

    @property
    def call_count(self):
        return len(self._calls)


class MockVisionAnalyst:
    """Mock VisionAnalyst that returns canned validation result."""

    def __init__(self, result=None):
        self._result = result or {
            "action": "CONFIRM",
            "confidence": 70,
            "risk_level": "LOW",
            "reason": "Mock: chart looks good.",
        }
        self.use_mock = True
        self._calls = []

    def validate(self, chart_png_bytes, code, name):
        self._calls.append({"code": code, "name": name})
        return dict(self._result)

    def set_result(self, result):
        self._result = result

    def set_reject(self, reason="Mock rejection"):
        self._result = {
            "action": "REJECT",
            "confidence": 80,
            "risk_level": "HIGH",
            "reason": reason,
        }

    def set_error(self):
        """Make next call return error-style REJECT."""
        self._result = {
            "action": "REJECT",
            "confidence": 0,
            "risk_level": "HIGH",
            "reason": "Vision check failed (mock error)",
        }

    @property
    def call_count(self):
        return len(self._calls)
