import os
import datetime
from datetime import timezone, timedelta


KST = timezone(timedelta(hours=9))


class ReportBuilder:
    SECTION_TITLES = {
        "company_overview": "1. 기업 개요",
        "financial_analysis": "2. 재무 분석",
        "valuation": "3. 밸류에이션",
        "industry_competition": "4. 산업 및 경쟁 분석",
        "supply_technical": "5. 수급 및 기술적 분석",
        "news_disclosure": "6. 뉴스 및 공시",
        "consensus": "7. 증권사 컨센서스",
        "investment_thesis": "8. AI 투자 의견",
    }

    SECTION_EMOJIS = {
        "company_overview": "🏢",
        "financial_analysis": "📈",
        "valuation": "💰",
        "industry_competition": "🏭",
        "supply_technical": "📊",
        "news_disclosure": "📰",
        "consensus": "🎯",
        "investment_thesis": "🤖",
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.output_dir = self.config.get("output", {}).get("file_dir", "reports")

    def _extract_summary(self, sections: dict) -> str:
        """investment_thesis 섹션에서 핵심 요약 추출 (첫 단락 또는 첫 몇 줄)"""
        thesis = sections.get("investment_thesis", "")
        if not thesis:
            return "분석 데이터 없음"

        # 첫 단락 추출 (빈 줄 기준)
        paragraphs = thesis.strip().split("\n\n")
        if paragraphs:
            first = paragraphs[0].strip()
            # 너무 길면 처음 300자만
            if len(first) > 300:
                first = first[:300] + "..."
            return first
        return thesis[:300]

    def build(self, code: str, name: str, sections: dict, model: str = "") -> str:
        """섹션별 분석 결과를 최종 마크다운 리포트로 조립"""
        now = datetime.datetime.now(KST)
        date_str = now.strftime("%Y-%m-%d")

        lines = []

        # 리포트 헤더
        lines.append(f"# 📊 {name}({code}) 딥 리서치 리포트")
        model_info = f" | AI 모델: {model}" if model else ""
        lines.append(f"> 분석일: {date_str}{model_info}")
        lines.append("")

        # 핵심 요약
        lines.append("## 📌 핵심 요약")
        lines.append(self._extract_summary(sections))
        lines.append("")

        # 각 섹션 순서대로 조립
        for key, title in self.SECTION_TITLES.items():
            lines.append("---")
            emoji = self.SECTION_EMOJIS.get(key, "")
            lines.append(f"## {emoji} {title}")
            content = sections.get(key, "").strip()
            if content:
                lines.append(content)
            else:
                lines.append("분석 데이터 없음")
            lines.append("")

        return "\n".join(lines)

    def build_summary(self, code: str, name: str, sections: dict) -> str:
        """Discord용 요약 리포트 (핵심 요약 + 투자의견만, 1900자 이하)"""
        now = datetime.datetime.now(KST)
        date_str = now.strftime("%Y-%m-%d")

        lines = []
        lines.append(f"**📊 {name}({code}) 딥 리서치 요약**")
        lines.append(f"> 분석일: {date_str}")
        lines.append("")
        lines.append("**📌 핵심 요약**")
        lines.append(self._extract_summary(sections))
        lines.append("")

        # 투자의견 추가 (있으면)
        thesis = sections.get("investment_thesis", "").strip()
        if thesis:
            lines.append("**🤖 AI 투자 의견**")
            # 남은 공간 계산 후 자르기
            current = "\n".join(lines)
            remaining = 1900 - len(current) - 50  # 여유분
            if remaining > 0:
                lines.append(thesis[:remaining] + ("..." if len(thesis) > remaining else ""))

        summary = "\n".join(lines)
        # 최종적으로 1900자 초과 시 강제 자르기
        if len(summary) > 1900:
            summary = summary[:1897] + "..."
        return summary

    def save_to_file(self, report: str, code: str, name: str) -> str:
        """reports/{date}_{code}_{name}.md 파일 저장. 저장 경로 반환."""
        os.makedirs(self.output_dir, exist_ok=True)
        date_str = datetime.datetime.now(KST).strftime("%Y%m%d")
        filename = f"{date_str}_{code}_{name}.md"
        filepath = os.path.join(self.output_dir, filename)
        print(f"[ReportBuilder] Saving report to {filepath}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)
        return filepath

    def send_to_discord(self, report: str, summary: str, discord_client, send_full: bool = False):
        """Discord 전송 (요약 또는 전체)"""
        if send_full:
            # 전체 리포트를 분할 전송
            discord_client.send(report)
        else:
            # 요약만 단일 메시지 전송
            discord_client.send_message(summary)
