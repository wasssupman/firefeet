"""Windows cp949 환경에서 UTF-8 출력 설정.

한국어 Windows 기본 인코딩(cp949)에서 이모지/유니코드 출력 시
UnicodeEncodeError 방지. macOS/Linux는 이미 UTF-8이라 영향 없음.
"""

import sys


def setup_utf8_stdout():
    """stdout/stderr를 UTF-8로 재설정."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
