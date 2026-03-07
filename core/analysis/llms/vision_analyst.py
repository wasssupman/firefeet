"""
core/analysis/llms/vision_analyst.py
Visual chart pattern cross-validator using Gemini 2.5 Flash (multimodal).
Performs final visual sanity check AFTER text-based analysis has approved.
"""

import os
import re
import json
import logging
from typing import Optional
from core.config_loader import ConfigLoader

logger = logging.getLogger("VisionAnalyst")

# Concise prompt — fewer tokens = stays under output budget
VISION_PROMPT = (
    "You are a Korean stock technical analyst. Analyze this chart image and decide if it is safe to BUY. "
    "Output ONLY valid JSON (no markdown fences, no explanation):\n"
    '{"action":"CONFIRM or REJECT","confidence":0-100,"risk_level":"LOW or MEDIUM or HIGH","reason":"one sentence in Korean"}'
)


def _parse_json_response(raw: str) -> dict:
    """Robustly parse Gemini's response — handles markdown fences and truncation."""
    raw = raw.strip()
    # Strip markdown code fences
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    if match:
        raw = match.group(1).strip()
    # Extract first valid JSON block
    if "{" in raw and "}" in raw:
        raw = raw[raw.index("{"):raw.rindex("}")+1]
    return json.loads(raw)


class VisionAnalyst:
    """
    Final visual cross-validation gate using Gemini 2.5 Flash Vision API.
    Called AFTER text-based Analyst+Executor pipeline gives a BUY signal.
    """

    def __init__(self, model: str = "gemini-2.5-flash-lite"):
        self.model_name = model
        self.client = None
        self.use_mock = False
        self._init_client()

    def _init_client(self):
        api_key = None
        try:
            secrets = ConfigLoader().load_config()
            api_key = secrets.get("GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        except Exception:
            api_key = os.environ.get("GEMINI_API_KEY", "")

        if not api_key:
            logger.warning("No GEMINI_API_KEY found. VisionAnalyst will use mock mode.")
            self.use_mock = True
            return
        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
            logger.info(f"VisionAnalyst initialized with model: {self.model_name}")
        except ImportError:
            logger.warning("google-genai not installed. Falling back to mock mode.")
            self.use_mock = True

    def validate(self, chart_png_bytes: bytes, code: str, name: str) -> dict:
        """
        Sends chart image to Gemini Vision and returns CONFIRM/REJECT decision.
        Returns dict: action, confidence (int), risk_level, reason
        """
        if self.use_mock or not chart_png_bytes:
            logger.info(f"[{name}({code})] VisionAnalyst mock mode — auto CONFIRM.")
            return {"action": "CONFIRM", "confidence": 50, "risk_level": "MEDIUM",
                    "reason": "Mock mode: chart validation skipped."}

        try:
            from google.genai import types

            image_part = types.Part.from_bytes(data=chart_png_bytes, mime_type="image/png")

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[VISION_PROMPT, image_part],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=512,
                )
            )

            raw = response.text or ""
            result = _parse_json_response(raw)
            logger.info(f"[{name}({code})] Vision — {result.get('action')} "
                        f"(conf={result.get('confidence')}%, risk={result.get('risk_level')})")
            return result

        except Exception as e:
            logger.error(f"[{name}({code})] VisionAnalyst error: {e}")
            return {
                "action": "REJECT",
                "confidence": 0,
                "risk_level": "HIGH",
                "reason": f"Vision check failed (안전 기각): {str(e)}"
            }
