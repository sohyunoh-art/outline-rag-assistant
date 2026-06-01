"""검색 단계: 질문 → 관련 문서 본문 확보.

전략:
  0) (선택) query expander로 질문을 검색어 묶음으로 확장 — 질문어≠문서어 갭을 메운다.
  1) 원문 질문 + 확장 검색어들을 각각 검색 (collections가 지정되면 그 범위로 한정)
  2) 문서 id 기준 병합 — '여러 검색어가 함께 끌어온 문서(득표수)'를 우선,
     동률이면 ranking 내림차순. (여러 검색어가 가리키는 문서일수록 관련도가 높다)
  3) 후보가 비면 키워드만 추려 재검색 (확장기 실패 시의 안전망)
  4) 상위 N개만 본문 열람(get_document), 거대 문서는 truncate
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


class _ExpanderLike(Protocol):
    def expand(self, question: str) -> list[str]: ...


@dataclass
class RetrievedDoc:
    id: str
    title: str
    url: str
    text: str


@dataclass
class _Candidate:
    """병합 중인 후보 문서: 몇 개의 검색어가 끌어왔는지(votes)와 최대 ranking을 추적."""

    doc: dict[str, Any]
    votes: int = 0
    ranking: float = 0.0


class Retriever:
    def __init__(
        self,
        client: _ClientLike,
        *,
        collections: list[str] | None = None,
        max_docs: int = config.DEFAULT_MAX_DOCS,
        expander: _ExpanderLike | None = None,
        max_doc_chars: int = config.MAX_DOC_CHARS,
    ) -> None:
        self.client = client
        self.collections = collections or []
        self.max_docs = max_docs
        self.expander = expander
        self.max_doc_chars = max_doc_chars
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

    def _collect(self, queries: list[str]) -> list[dict[str, Any]]:
        """여러 검색어로 검색해 문서 id 기준 병합.

        정렬: 득표수(이 문서를 끌어온 서로 다른 검색어 수) 내림차순,
        동률이면 그 문서가 받은 최대 ranking 내림차순.
        검색어가 1개뿐이면 득표수가 모두 1이라 사실상 ranking 정렬과 같다(기존 동작 보존).
        """
        cands: dict[str, _Candidate] = {}
        for q in queries:
            seen_in_q: set[str] = set()
            for doc in self._search_all_scopes(q):
                did = doc.get("id")
                if not did:
                    continue
                rank = doc.get("_ranking", 0) or 0
                c = cands.get(did)
                if c is None:
                    c = _Candidate(doc=doc, votes=0, ranking=rank)
                    cands[did] = c
                # 같은 검색어 안에서의 중복은 한 표로만 센다
                if did not in seen_in_q:
                    c.votes += 1
                    seen_in_q.add(did)
                c.ranking = max(c.ranking, rank)
        ordered = sorted(cands.values(), key=lambda c: (c.votes, c.ranking), reverse=True)
        return [c.doc for c in ordered]

    def search(self, question: str) -> list[RetrievedDoc]:
        # 0) 질문을 검색어 묶음으로 확장 (실패하면 빈 리스트 → 원문만 검색)
        expansion = self.expander.expand(question) if self.expander else []
        queries = [question] + [t for t in expansion if t and t != question]

        unique = self._collect(queries)

        if not unique:
            # 문장형 질문은 전문검색에서 자주 빗나간다 → 토큰을 하나씩 검색해 recall을 높인다.
            tokens = [t for t in self._keywords(question)[: self._MAX_FALLBACK_TOKENS] if t != question]
            unique = self._collect(tokens)

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
                    text=self._truncate(full.get("text", "")),
                )
            )
        return result

    def _truncate(self, text: str) -> str:
        """거대 문서가 컨텍스트를 독점하지 않도록 본문을 상한선에서 자른다."""
        if self.max_doc_chars and len(text) > self.max_doc_chars:
            return text[: self.max_doc_chars] + "\n\n…(본문 일부 생략)"
        return text
