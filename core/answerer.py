"""답변 단계: 확보한 문서 + role_prompt → Claude 답변 생성.

system 프롬프트 = 코어 고정 규칙(BASE_SYSTEM_PROMPT) + 어시스턴트 역할(role_prompt).
anthropic 클라이언트는 주입 가능해서, API 키 없이도(가짜 클라이언트로) 테스트된다.
"""
from __future__ import annotations

from typing import Any

from . import config
from .retriever import RetrievedDoc


def build_context(docs: list[RetrievedDoc]) -> str:
    """검색된 문서들을 Claude에게 줄 컨텍스트 블록으로 직렬화한다."""
    if not docs:
        return "(검색된 문서 없음)"
    blocks = [
        f"[문서 {i}] 제목: {d.title}\n링크: {d.url}\n본문:\n{d.text}".strip()
        for i, d in enumerate(docs, 1)
    ]
    return "\n\n---\n\n".join(blocks)


class Answerer:
    def __init__(
        self,
        role_prompt: str,
        *,
        client: Any | None = None,
        model: str = config.ANSWERER_MODEL,
    ) -> None:
        self.role_prompt = role_prompt.strip()
        self.model = model
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic  # 지연 임포트: 키/패키지 없이 모듈 임포트만 해도 안 깨지게

            self._client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용
        return self._client

    @property
    def system_prompt(self) -> str:
        return f"{config.BASE_SYSTEM_PROMPT}\n\n[이 어시스턴트의 역할]\n{self.role_prompt}"

    def answer(self, question: str, docs: list[RetrievedDoc]) -> str:
        user_content = (
            f"다음은 사내 문서에서 찾은 근거입니다.\n\n{build_context(docs)}\n\n"
            f"위 문서만 근거로, 규칙에 따라 다음 질문에 답하세요.\n\n질문: {question}"
        )
        resp = self._get_client().messages.create(
            model=self.model,
            max_tokens=config.ANSWERER_MAX_TOKENS,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
