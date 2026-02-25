"""
core/analysis/llms/claude_cli.py

Claude CLI 공통 유틸리티.
모든 Claude CLI 호출을 일관된 인터페이스로 통합.
- 재귀 호출 방지 (CLAUDECODE 환경변수 제거)
- 타임아웃 + exponential backoff 재시도
- 인코딩 통일 (utf-8)
- "Not logged in" 감지
"""

import os
import subprocess
import time
import logging

logger = logging.getLogger("ClaudeCLI")


class ClaudeCLIError(Exception):
    """Claude CLI 호출 실패"""
    pass


class ClaudeCLIAuthError(ClaudeCLIError):
    """Claude CLI 인증 필요 (로그인 안 됨)"""
    pass


class ClaudeCLINotFoundError(ClaudeCLIError):
    """Claude CLI 미설치"""
    pass


def call_claude(
    prompt: str,
    timeout: int = 60,
    max_retries: int = 2,
    output_format: str = "text",
) -> str:
    """
    공통 Claude CLI 호출.

    Args:
        prompt: Claude에 보낼 프롬프트
        timeout: 타임아웃(초). 기본 60초.
        max_retries: 최대 재시도 횟수. 기본 2회.
        output_format: 출력 형식 ("text" 또는 "json")

    Returns:
        Claude 응답 텍스트

    Raises:
        ClaudeCLINotFoundError: CLI 미설치
        ClaudeCLIAuthError: 로그인 필요
        ClaudeCLIError: 기타 CLI 에러
    """
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    last_error = None

    for attempt in range(max_retries + 1):
        try:
            result = subprocess.run(
                ["claude", "-p", "--output-format", output_format],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                encoding="utf-8",
                errors="replace",
            )

            output = result.stdout.strip()
            stderr = result.stderr.strip()

            # 인증 실패 감지
            combined = output + " " + stderr
            if "Not logged in" in combined or "/login" in combined:
                raise ClaudeCLIAuthError(
                    "Claude CLI 인증 필요: 터미널에서 'claude login'을 먼저 실행하세요."
                )

            if result.returncode == 0 and output:
                return output

            # returncode != 0 이지만 stdout에 내용이 있으면 반환
            if output:
                return output

            # stderr에만 출력이 있는 경우
            if stderr:
                last_error = f"CLI stderr: {stderr}"
            else:
                last_error = f"CLI returned code {result.returncode} with no output"

        except FileNotFoundError:
            raise ClaudeCLINotFoundError(
                "claude CLI를 찾을 수 없습니다. Claude Code가 설치되어 있는지 확인하세요."
            )
        except subprocess.TimeoutExpired:
            last_error = f"Claude CLI 타임아웃 ({timeout}초)"
        except (ClaudeCLIAuthError, ClaudeCLINotFoundError):
            raise
        except Exception as e:
            last_error = str(e)

        # 재시도 대기 (exponential backoff)
        if attempt < max_retries:
            wait = 2 ** (attempt + 1)
            logger.warning(
                f"Claude CLI 호출 실패 (시도 {attempt + 1}/{max_retries + 1}): {last_error}. "
                f"{wait}초 후 재시도..."
            )
            time.sleep(wait)

    raise ClaudeCLIError(f"Claude CLI 호출 최종 실패: {last_error}")


def is_cli_available() -> bool:
    """Claude CLI 사용 가능 여부 확인"""
    try:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False
