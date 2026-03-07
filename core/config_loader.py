import yaml
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class ConfigLoader:
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = os.path.join(_PROJECT_ROOT, "config", "secrets.yaml")
        self.config_path = config_path
        self._config = None

    def load_config(self):
        if self._config is not None:
            return self._config
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file not found at: {self.config_path}. Please copy secrets_template.yaml to secrets.yaml and fill in your keys.")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)
        return self._config

    def get_kis_config(self, mode="PAPER"):
        """
        Returns the KIS API configuration for the specified mode.
        mode: "REAL" (Real Trading) or "PAPER" (Paper Trading)
        """
        config = self.load_config()
        key = "PROD" if mode == "REAL" else "PAPER"
        result = config.get(key)
        if not result:
            raise ValueError(
                f"secrets.yaml에 '{key}' 섹션이 없습니다. "
                f"secrets_template.yaml을 참고하여 설정하세요."
            )
        return result

    def get_account_info(self, mode="REAL"):
        config = self.load_config()
        if mode == "PAPER" and config.get("PAPER_CANO"):
            cano = config.get("PAPER_CANO")
        else:
            cano = config.get("CANO")
        return {
            "CANO": cano,
            "ACNT_PRDT_CD": config.get("ACNT_PRDT_CD")
        }
