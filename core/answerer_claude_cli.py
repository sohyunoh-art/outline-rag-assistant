"""답변 백엔드(대안): 로컬 claude CLI(Claude Code)를 통해 답변 생성.

Anthropic API 키 없이, 이미 로그인된 Claude Code 자격으로 동작한다.
인터페이스(Answerer와 동일): system_prompt 프로퍼티 + answer(question, docs).

동작: claude -p --system-prompt "<규칙+역할>"  (사용자 컨텍스트는 stdin으로 전달)
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Callable

from . import config
from .answerer import build_context
from .retriever import RetrievedDoc


class ClaudeCliAnswerer:
    def __init__(
        self,
        role_prompt: str,
        *,
        command: str = config.CLAUDE_CLI_COMMAND,
        timeout: int = config.CLAUDE_CLI_TIMEOUT,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self.role_prompt = role_prompt.strip()
        self.command = command
        self.timeout = timeout
        self._runner = runner or subprocess.run  # 테스트에서 주입 가능

    @property
    def system_prompt(self) -> str:
        return f"{config.BASE_SYSTEM_PROMPT}\n\n[이 어시스턴트의 역할]\n{self.role_prompt}"

    def answer(self, question: str, docs: list[RetrievedDoc]) -> str:
        if self._runner is subprocess.run and shutil.which(self.command) is None:
            raise RuntimeError(
                f"'{self.command}' 명령을 찾을 수 없습니다. Claude Code CLI가 설치/로그인돼 있어야 합니다."
            )
        user_content = (
            f"다음은 사내 문서에서 찾은 근거입니다.\n\n{build_context(docs)}\n\n"
            f"위 문서만 근거로, 규칙에 따라 다음 질문에 답하세요.\n\n질문: {question}"
        )
        # claude CLI는 자체 로그인(OAuth)으로 동작해야 한다. .env에서 올라온
        # (비어있거나 플레이스홀더인) ANTHROPIC_API_KEY가 상속되면 "Invalid API key"로
        # 실패하므로, 서브프로세스 환경에서 키 관련 변수를 제거한다.
        child_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        }
        proc = self._runner(
            [self.command, "-p", "--system-prompt", self.system_prompt],
            input=user_content,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            env=child_env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI 오류(returncode={proc.returncode}): {proc.stderr.strip()}")
        return proc.stdout.strip()
