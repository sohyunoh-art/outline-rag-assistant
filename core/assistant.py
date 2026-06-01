"""조립: YAML 설정을 읽어 Retriever+Answerer를 하나의 어시스턴트로 묶는다.

코어는 여기까지다. 새 용도를 추가하려면 assistants/*.yaml 파일 한 개만 만들면 되고,
core/ 아래 코드는 단 한 줄도 건드리지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import config
from .answerer import Answerer
from .answerer_claude_cli import ClaudeCliAnswerer
from .outline_client import OutlineClient
from .query_expander import build_query_expander
from .retriever import Retriever, RetrievedDoc


def build_answerer(role_prompt: str) -> Any:
    """ANSWERER_BACKEND 환경변수에 따라 답변 백엔드를 고른다.

    "claude_cli" → 로컬 claude CLI(키 불필요), 그 외 → Anthropic API.
    """
    backend = os.getenv(config.ENV_ANSWERER_BACKEND, config.DEFAULT_ANSWERER_BACKEND).strip().lower()
    if backend == "claude_cli":
        return ClaudeCliAnswerer(role_prompt)
    return Answerer(role_prompt)


@dataclass
class AssistantConfig:
    name: str
    description: str = ""
    collections: list[str] = field(default_factory=list)
    max_docs: int = config.DEFAULT_MAX_DOCS
    role_prompt: str = ""

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AssistantConfig":
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if "name" not in data or not str(data.get("name", "")).strip():
            raise ValueError(f"{path}: 'name' 필드는 필수입니다.")
        if not str(data.get("role_prompt", "")).strip():
            raise ValueError(f"{path}: 'role_prompt' 필드는 필수입니다.")
        return cls(
            name=str(data["name"]).strip(),
            description=str(data.get("description", "")).strip(),
            collections=list(data.get("collections") or []),
            max_docs=int(data.get("max_docs", config.DEFAULT_MAX_DOCS)),
            role_prompt=str(data["role_prompt"]),
        )


@dataclass
class Answer:
    text: str
    docs: list[RetrievedDoc]


class Assistant:
    def __init__(
        self,
        cfg: AssistantConfig,
        *,
        client: OutlineClient | None = None,
        answerer: Answerer | None = None,
        expander: Any | None = None,
    ) -> None:
        self.cfg = cfg
        self.client = client or OutlineClient()
        self.retriever = Retriever(
            self.client, collections=cfg.collections, max_docs=cfg.max_docs, expander=expander
        )
        self.answerer = answerer or build_answerer(cfg.role_prompt)

    @classmethod
    def from_config_file(cls, path: str | Path, **kwargs: Any) -> "Assistant":
        # production(CLI) 경로에서는 query expansion을 기본으로 켠다.
        # 직접 Assistant(...)를 만드는 호출(테스트 등)은 영향받지 않는다.
        # (명시적으로 expander를 넘기면 그대로 존중 — 불필요한 생성도 피한다)
        if "expander" not in kwargs:
            kwargs["expander"] = build_query_expander()
        return cls(AssistantConfig.from_yaml(path), **kwargs)

    def ask(self, question: str) -> Answer:
        docs = self.retriever.search(question)
        text = self.answerer.answer(question, docs)
        return Answer(text=text, docs=docs)
