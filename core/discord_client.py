import requests
import json
from core.config_loader import ConfigLoader

class DiscordClient:
    MAX_LEN = 1900  # Discord 2000자 제한 (여유분 확보)

    def __init__(self, webhook_key="DISCORD_WEBHOOK_URL"):
        loader = ConfigLoader()
        config = loader.load_config()
        self.webhook_url = config.get(webhook_key) or config.get("DISCORD_WEBHOOK_URL")

    def send_message(self, message):
        """단일 메시지 전송 (2000자 이하)"""
        if not self.webhook_url:
            print("[DiscordClient] No Webhook URL found in config.")
            return

        payload = {"content": message}
        
        try:
            res = requests.post(self.webhook_url, json=payload)
            res.raise_for_status()
        except Exception as e:
            print(f"[DiscordClient] Failed to send message: {e}")

    def send(self, message):
        """긴 메시지를 자동 분할 전송"""
        if len(message) <= self.MAX_LEN:
            self.send_message(message)
            return

        # 줄 단위로 분할
        lines = message.split("\n")
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > self.MAX_LEN:
                self.send_message(chunk)
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk.strip():
            self.send_message(chunk)

    def send_alert(self, title, link, keyword):
        """뉴스 알림 전송"""
        message = f"🚨 **[{keyword}]** 감지!\n\n**{title}**\n{link}"
        self.send_message(message)

