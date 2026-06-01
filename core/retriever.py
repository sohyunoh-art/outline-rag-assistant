"""검색 단계: 질문 → 관련 문서 본문 확보.

전략:
  1) 질문 그대로 검색 (collections가 지정되면 그 범위로 한정)
  2) 1차가 비면 키워드만 추려 재검색
  3) 문서 id 기준 중복 제거 → ranking 내림차순 정렬
  4) 상위 N개만 본문 열람(get_document)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from . import config


class _ClientLike(Protocol):
    """retriever가 의존하는 최소 인터페이스 (실제/가짜 클라이언트 공용)."""

    def search_documents(self, query: str, *, collection_id: str | None = ..., limit: int = ...) -> list[dict[str, Any]]: ...
    def get_document(self, document_id: str) -> dict[str, Any]: ...
    def find_collection_ids(self, names: list[str]) -> list[str]: ...


@dataclass
class RetrievedDoc:
    id: str
    title: str
    url: str
    text: str


class Retriever:
    def __init__(
        self,
        client: _ClientLike,
        *,
        collections: list[str] | None = None,
        max_docs: int = config.DEFAULT_MAX_DOCS,
    ) -> None:
        self.client = client
        self.collections = collections or []
        self.max_docs = max_docs
        self._collection_ids: list[str] | None = None  # 1회만 조회해 캐시

    def _resolve_collection_ids(self) -> list[str]:
        if self._collection_ids is None:
            self._collection_ids = self.client.find_collection_ids(self.collections)
        return self._collection_ids

    def _search_all_scopes(self, query: str) -> list[dict[str, Any]]:
        scope_ids = self._resolve_collection_ids()
        if not scope_ids:
            return self.client.search_documents(query)
        merged: list[dict[str, Any]] = []
        for cid in scope_ids:
            merged.extend(self.client.search_documents(query, collection_id=cid))
        return merged

    # 빈 결과 fallback에서 검색해볼 최대 토큰 수 (검색 횟수 상한)
    _MAX_FALLBACK_TOKENS = 6

    @staticmethod
    def _keywords(question: str) -> list[str]:
        """아주 단순한 키워드 추출: 2글자 이상 토큰만 남긴다(형태소 분석 아님)."""
        return re.findall(r"[0-9A-Za-z가-힣]{2,}", question)

    def search(self, question: str) -> list[RetrievedDoc]:
        candidates = self._search_all_scopes(question)
        if not candidates:
            # 문장형 질문은 전문검색에서 자주 빗나간다 → 토큰을 하나씩 검색해 합쳐 recall을 높인다.
            for token in self._keywords(question)[: self._MAX_FALLBACK_TOKENS]:
                if token == question:
                    continue
                candidates.extend(self._search_all_scopes(token))

        # 중복 제거(문서 id 기준) + ranking 내림차순
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for doc in sorted(candidates, key=lambda d: d.get("_ranking", 0), reverse=True):
            did = doc.get("id")
            if not did or did in seen:
                continue
            seen.add(did)
            unique.append(doc)

        # 상위 N개 본문 열람
        base_url = getattr(self.client, "base_url", "")
        result: list[RetrievedDoc] = []
        for doc in unique[: self.max_docs]:
            full = self.client.get_document(doc["id"])
            url = full.get("url") or doc.get("url", "")
            # Outline은 url을 상대경로(/doc/...)로 주므로 도메인을 붙여 클릭 가능한 링크로 만든다.
            if url.startswith("/") and base_url:
                url = base_url + url
            result.append(
                RetrievedDoc(
                    id=doc["id"],
                    title=full.get("title") or doc.get("title", "(제목 없음)"),
                    url=url,
                    text=full.get("text", ""),
                )
            )
        return result
