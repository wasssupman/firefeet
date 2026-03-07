"""
트레이딩 봇 공통 생명주기 관리.

PID 파일 기반 단일 인스턴스 보장, SIGTERM 핸들러, 장 운영 시간 체크를
각 봇 엔트리포인트에서 공통 클래스로 추출.
"""

import os
import sys
import signal
import atexit


class BotLifecycle:
    """트레이딩 봇 공통 생명주기 관리."""

    def __init__(self, pid_name: str, close_time: str = "1530"):
        """
        pid_name: PID 파일 이름 (예: "firefeet_scalper") → /tmp/{pid_name}.pid
        close_time: 장 마감 시간 HHMM (기본 "1530", 스윙 봇은 "1520")
        """
        import tempfile
        self.pid_file = os.path.join(tempfile.gettempdir(), f"{pid_name}.pid")
        self.close_time = close_time
        self._lock_acquired = False

    def acquire_lock(self) -> None:
        """PID 파일 기반 단일 인스턴스 보장.

        기존 PID 파일이 있으면 해당 프로세스 생존 여부를 확인한다.
        살아 있으면 sys.exit(1), 죽어 있으면(stale) 무시하고 계속 진행.
        새 PID를 기록하고 atexit에 release_lock을 등록한다.
        """
        if os.path.exists(self.pid_file):
            try:
                with open(self.pid_file) as f:
                    old_pid = int(f.read().strip())
                os.kill(old_pid, 0)  # signal 0 = 존재 확인만
                print(f"[BotLifecycle] 이미 실행 중입니다 (PID {old_pid}). 중복 실행 방지로 종료합니다.")
                print(f"[BotLifecycle] 기존 프로세스를 먼저 종료하세요: kill {old_pid}")
                sys.exit(1)
            except (ProcessLookupError, PermissionError, OSError):
                # 프로세스 없음 → stale PID 파일, 무시하고 계속
                pass
            except ValueError:
                # PID 파일 손상 → 무시
                pass

        with open(self.pid_file, "w") as f:
            f.write(str(os.getpid()))

        self._lock_acquired = True
        atexit.register(self.release_lock)

    def release_lock(self) -> None:
        """PID 파일 제거."""
        try:
            os.remove(self.pid_file)
        except FileNotFoundError:
            pass

    def setup_signal_handler(self) -> None:
        """SIGTERM → SystemExit(0) 변환.

        finally 블록 실행을 보장하기 위해 SIGTERM 수신 시 SystemExit을 발생시킨다.
        """
        def _handler(signum, frame):
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, _handler)

    def is_market_hours(self, now_str: str) -> bool:
        """장 운영 시간 체크.

        now_str: "HHMM" 형식 (예: "0930", "1520")
        주말 여부는 호출자가 책임진다. 이 메서드는 시간 범위만 판단한다.
        """
        return "0900" <= now_str <= self.close_time
