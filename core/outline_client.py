"""Outline REST API 얇은 클라이언트 (읽기 전용).

검색·열람·컬렉션 조회만 한다. 생성·수정·삭제 엔드포인트는 아예 호출하지 않는다.
테스트에서는 이 클래스를 가짜 객체(FakeOutlineClient)로 교체(주입)할 수 있다.

Outline REST API 참고: 모든 호출은 POST + JSON 바디 + Bearer 토큰.
  - POST /api/documents.search   {query, collectionId?, limit}
  - POST /api/documents.info     {id}
  - POST /api/collections.list   {limit}
  - POST /api/users.list         {query?, limit}            (작성자 이름 → userId 해석)
  - POST /api/documents.list     {userId?, collectionId?, sort, direction, limit}  (작성자 필터 목록)
"""
from __future__ import annotations

import os
from typing import Any

import requests

from . import config


class OutlineClient:
    """읽기 전용 Outline 클라이언트."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        base_url = base_url or os.getenv(config.ENV_OUTLINE_URL, "")
        token = token or os.getenv(config.ENV_OUTLINE_TOKEN, "")
        if not base_url or not token:
            raise RuntimeError(
                f"{config.ENV_OUTLINE_URL}와 {config.ENV_OUTLINE_TOKEN}를 .env에 설정해야 합니다. "
                "(.env.example 참고)"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self._session.post(self.base_url + path, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def search_documents(
        self,
        query: str,
        *,
        collection_id: str | None = None,
        limit: int = config.DEFAULT_SEARCH_LIMIT,
    ) -> list[dict[str, Any]]:
        """전문 검색. 결과의 document만 추려 정렬용 _ranking을 부착해 반환한다."""
        payload: dict[str, Any] = {"query": query, "limit": limit}
        if collection_id:
            payload["collectionId"] = collection_id
        data = self._post(config.OUTLINE_SEARCH_PATH, payload).get("data", [])
        results: list[dict[str, Any]] = []
        for item in data:
            doc = dict(item.get("document") or {})
            doc["_ranking"] = item.get("ranking", 0)
            results.append(doc)
        return results

    def get_document(self, document_id: str) -> dict[str, Any]:
        """문서 본문(text/title/url 등)을 가져온다."""
        return self._post(config.OUTLINE_INFO_PATH, {"id": document_id}).get("data", {})

    def list_collections(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._post(config.OUTLINE_COLLECTIONS_PATH, {"limit": limit}).get("data", [])

    def list_users(self, query: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        """워크스페이스 사용자 목록(읽기 전용). query가 있으면 이름/이메일로 서버측 필터링."""
        payload: dict[str, Any] = {"limit": limit}
        if query:
            payload["query"] = query
        return self._post(config.OUTLINE_USERS_PATH, payload).get("data", [])

    def list_documents_by_author(
        self,
        user_id: str,
        *,
        collection_id: str | None = None,
        sort: str = "updatedAt",
        direction: str = "DESC",
        limit: int = config.DEFAULT_AUTHOR_DOC_LIMIT,
    ) -> list[dict[str, Any]]:
        """특정 사용자(userId)가 작성한 문서 목록(읽기 전용). 본문은 포함하지 않는다."""
        payload: dict[str, Any] = {
            "userId": user_id,
            "sort": sort,
            "direction": direction,
            "limit": limit,
        }
        if collection_id:
            payload["collectionId"] = collection_id
        return self._post(config.OUTLINE_DOCUMENTS_LIST_PATH, payload).get("data", [])

    def find_collection_ids(self, names: list[str]) -> list[str]:
        """컬렉션 '이름' 목록을 실제 컬렉션 ID 목록으로 변환한다."""
        if not names:
            return []
        wanted = {n.strip().lower() for n in names}
        return [
            col["id"]
            for col in self.list_collections()
            if col.get("name", "").strip().lower() in wanted and col.get("id")
        ]
