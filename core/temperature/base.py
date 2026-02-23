def clamp(value, min_val, max_val):
    return max(min_val, min(max_val, value))


class TempModule:
    """온도 모듈 공통 인터페이스"""

    name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", True)
        self.weight = config.get("weight", 0)

    def calculate(self) -> dict:
        """
        Returns:
            {
                "score": float,        # -100 ~ +100
                "details": dict,       # 모듈별 상세 정보
                "error": str | None,   # 실패 시 에러 메시지
            }
        """
        raise NotImplementedError
