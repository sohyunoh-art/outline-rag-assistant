"""검색 앞단: 질문 → 전문검색에 넣을 검색어 묶음(query expansion).

왜 필요한가:
  사용자는 "도선사가 뭐야?", "상태 관리 어떻게 해?"처럼 묻지만, 문서에는
  "pilot", "Zustand/Recoil/전역 상태"처럼 다른 어휘로 적혀 있다. 키워드 전문검색은
  이 한↔영·구어↔용어 갭을 못 넘는다. LLM이 질문을 "문서에 박혀 있을 법한 검색어"로
  바꿔주면 recall이 크게 오른다.

설계:
  - 인터페이스: expand(question) -> list[str]  (검색어 목록, 보수적/고정밀)
  - 백엔드 2종: anthropic API / 로컬 claude CLI  (answerer와 동일한 선택 규칙)
  - 실패해도 절대 예외를 밖으로 던지지 않는다 → 빈 리스트 반환 → 호출측(retriever)이
    기존 토큰 fallback으로 안전하게 내려간다. 검색 품질은 보강이지 의존이 아니다.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Callable

from . import config

# 검색어로서 의미 없는, 너무 일반적인 토큰(있으면 노이즈만 끌어옴).
_GENERIC_STOPWORDS = {
    "우리", "우리회사", "회사", "저희", "저희회사", "팀", "팀이", "어떻게",
    "무엇", "뭐", "뭐야", "있어", "하고", "하나요", "인가요", "어디", "관련",
    "그것", "이것", "대해", "대한", "방법", "방식",
}

_EXPANSION_SYSTEM_PROMPT = """\
너는 사내 위키(Outline) 전문검색에 넣을 '검색어'를 뽑는 도우미다.
사용자 질문을 보고, 그 답이 적혀 있을 문서를 찾기 위한 검색어 목록을 만들어라.

규칙:
- 조사·어미를 떼고 핵심 명사/명사구만 남긴다 ("상태 관리를" → "상태 관리").
- 한국어 용어는 문서에 영어로 적혔을 수 있으니 영어 동의어도 함께 낸다
  (예: "도선사" → "pilot", "상태 관리" → "state management", "Zustand", "Recoil").
- 도메인 동의어·구체 기술명을 적극 포함한다 (개념어보다 문서에 실제로 박힐 단어).
- "우리회사/어떻게/무엇" 같은 너무 일반적인 단어는 제외한다.
- 3~6개. 한 줄에 검색어 하나씩만. 번호·불릿·설명·따옴표 없이 검색어만 출력한다.
"""


def _parse_terms(raw: str) -> list[str]:
    """LLM 출력(줄 단위)을 검색어 리스트로 정리: 잡기호 제거·stopword 제거·중복제거·상한."""
    terms: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        # 앞머리 번호/불릿/따옴표/대시 제거
        t = re.sub(r"^[\s\-\*•\d\.\)\]]+", "", line).strip().strip("\"'`").strip()
        if not t or len(t) < 2:
            continue
        if t in _GENERIC_STOPWORDS:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(t)
        if len(terms) >= config.MAX_EXPANSION_TERMS:
            break
    return terms


class _BaseExpander:
    """expand()의 공통 골격. 하위 클래스는 _generate(question)->str 만 구현한다."""

    def _generate(self, question: str) -> str:  # pragma: no cover - 추상
        raise NotImplementedError

    def expand(self, question: str) -> list[str]:
        try:
            raw = self._generate(question)
        except Exception:
            # 확장은 보강일 뿐 — 실패는 조용히 삼키고 호출측이 fallback 하게 한다.
            return []
        return _parse_terms(raw or "")


class QueryExpander(_BaseExpander):
    """Anthropic API 기반 확장기 (answerer.Answerer와 동일한 자격/모델 사용)."""

    def __init__(self, *, client: Any | None = None, model: str = config.ANSWERER_MODEL) -> None:
        self.model = model
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic  # 지연 임포트

            self._client = anthropic.Anthropic()
        return self._client

    def _generate(self, question: str) -> str:
        resp = self._get_client().messages.create(
            model=self.model,
            max_tokens=config.QUERY_EXPANSION_MAX_TOKENS,
            system=_EXPANSION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"질문: {question}"}],
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )


class ClaudeCliQueryExpander(_BaseExpander):
    """로컬 claude CLI 기반 확장기 (API 키 없이 동작)."""

    def __init__(
        self,
        *,
        command: str = config.CLAUDE_CLI_COMMAND,
        timeout: int = config.QUERY_EXPANSION_CLI_TIMEOUT,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self.command = command
        self.timeout = timeout
        self._runner = runner or subprocess.run

    def _generate(self, question: str) -> str:
        if self._runner is subprocess.run and shutil.which(self.command) is None:
            raise RuntimeError(f"'{self.command}' 명령을 찾을 수 없습니다.")
        # answerer_claude_cli와 동일: 상속된 (빈/플레이스홀더) 키가 CLI 로그인을 깨지 않게 제거
        child_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        }
        proc = self._runner(
            [self.command, "-p", "--system-prompt", _EXPANSION_SYSTEM_PROMPT],
            input=f"질문: {question}",
            capture_output=True,
            text=True,
            timeout=self.timeout,
            env=child_env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI 확장 오류(returncode={proc.returncode}): {proc.stderr.strip()}")
        return proc.stdout.strip()


def build_query_expander() -> _BaseExpander:
    """ANSWERER_BACKEND에 맞춰 확장기 백엔드를 고른다 (build_answerer와 동형)."""
    backend = os.getenv(config.ENV_ANSWERER_BACKEND, config.DEFAULT_ANSWERER_BACKEND).strip().lower()
    if backend == "claude_cli":
        return ClaudeCliQueryExpander()
    return QueryExpander()
