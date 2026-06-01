"""작성자별 문서 조회: 이름 → 사용자 해석 → 그 사용자가 작성한 문서 목록.

MCP 도구만으로는 불가능했던 "특정 작성자가 쓴 문서 목록"을 채우는 자리.
읽기 전용 — users.list / documents.list 만 사용한다(생성·수정·삭제 없음).

해석 규칙(이름 → 사용자):
  1) 이름이 '정확히' 일치하는 사용자가 있으면 그쪽을 우선한다(부분일치 노이즈 배제).
  2) 정확 일치가 없으면 이름/이메일 부분일치로 후보를 찾는다.
  3) 0명 → not_found, 2명 이상 → ambiguous(동명이인 등), 1명 → ok.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from . import config


class _AuthorClientLike(Protocol):
    """author_lookup이 의존하는 최소 인터페이스 (실제/가짜 클라이언트 공용)."""

    def list_users(self, query: str | None = ..., *, limit: int = ...) -> list[dict[str, Any]]: ...
    def list_documents_by_author(
        self, user_id: str, *, collection_id: str | None = ..., sort: str = ..., direction: str = ..., limit: int = ...
    ) -> list[dict[str, Any]]: ...
    def find_collection_ids(self, names: list[str]) -> list[str]: ...


@dataclass
class AuthorDoc:
    id: str
    title: str
    url: str
    updated_at: str


@dataclass
class AuthorLookupResult:
    status: str  # "ok" | "not_found" | "ambiguous"
    name: str
    user: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    documents: list[AuthorDoc] = field(default_factory=list)


def _match_users(users: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """이름 → 사용자 후보. 정확 일치를 부분 일치보다 우선한다."""
    key = name.strip().lower()
    exact = [u for u in users if (u.get("name") or "").strip().lower() == key]
    if exact:
        return exact
    return [
        u
        for u in users
        if key in (u.get("name") or "").strip().lower()
        or key in (u.get("email") or "").strip().lower()
    ]


def lookup_by_author(
    client: _AuthorClientLike,
    name: str,
    *,
    collection: str | None = None,
    limit: int = config.DEFAULT_AUTHOR_DOC_LIMIT,
) -> AuthorLookupResult:
    """작성자 이름으로 문서 목록을 조회한다.

    collection(이름)이 주어지면 그 컬렉션으로 범위를 한정한다.
    문서의 상대경로 url(/doc/...)은 클라이언트 base_url로 절대경로화한다.
    """
    name = (name or "").strip()
    if not name:
        return AuthorLookupResult(status="not_found", name=name)

    users = client.list_users(query=name)
    matched = _match_users(users, name)
    if not matched:
        return AuthorLookupResult(status="not_found", name=name)
    if len(matched) > 1:
        return AuthorLookupResult(status="ambiguous", name=name, candidates=matched)

    user = matched[0]
    collection_id: str | None = None
    if collection:
        ids = client.find_collection_ids([collection])
        collection_id = ids[0] if ids else None

    raw = client.list_documents_by_author(user["id"], collection_id=collection_id, limit=limit)
    base_url = getattr(client, "base_url", "")
    documents: list[AuthorDoc] = []
    for d in raw:
        url = d.get("url", "") or ""
        # Outline은 url을 보통 상대경로(/doc/...)로 준다 → base_url을 붙여 절대경로로.
        # 이미 절대 url(http/https)이면 그대로 둔다.
        if url and base_url and not url.lower().startswith(("http://", "https://")):
            url = base_url + url
        documents.append(
            AuthorDoc(
                id=d.get("id", ""),
                title=d.get("title") or "(제목 없음)",
                url=url,
                updated_at=d.get("updatedAt", "") or "",
            )
        )
    return AuthorLookupResult(status="ok", name=name, user=user, documents=documents)
