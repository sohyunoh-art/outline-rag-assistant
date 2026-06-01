"""작성자별 문서 조회 검증 (외부 API/네트워크 없이 가짜 클라이언트로).

검증:
  - 이름 → 사용자 해석: 없음(not_found) / 동명이인(ambiguous) / 단일(ok)
  - 단일 매칭 시 문서 목록 + 상대경로 url 절대화
  - 단일 매칭이지만 문서 0건
  - CLI --author 분기(author_command)가 answerer(LLM)를 거치지 않음 + 렌더링 텍스트
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cli.main import author_command, format_author_result  # noqa: E402
from core.author_lookup import AuthorLookupResult, lookup_by_author  # noqa: E402


# ── 가짜 클라이언트 ──────────────────────────────────────────────────
class FakeAuthorClient:
    def __init__(self, users=None, docs_by_user=None, collections=None, base_url="https://wiki.example.com"):
        self._users = users or []
        self._docs_by_user = docs_by_user or {}
        self._collections = collections or []
        self.base_url = base_url
        self.author_calls: list[dict] = []

    def list_users(self, query=None, *, limit=100):
        if not query:
            return list(self._users)
        q = query.strip().lower()
        return [
            u for u in self._users
            if q in (u.get("name") or "").lower() or q in (u.get("email") or "").lower()
        ]

    def list_documents_by_author(self, user_id, *, collection_id=None, sort="updatedAt", direction="DESC", limit=50):
        self.author_calls.append({"user_id": user_id, "collection_id": collection_id, "limit": limit})
        docs = self._docs_by_user.get(user_id, [])
        if collection_id is not None:
            docs = [d for d in docs if d.get("collectionId") == collection_id]
        return list(docs)

    def find_collection_ids(self, names):
        wanted = {n.strip().lower() for n in names}
        return [c["id"] for c in self._collections if c["name"].lower() in wanted]


def _user(uid, name, email=""):
    return {"id": uid, "name": name, "email": email}


def _rawdoc(did, title, url, updated="2025-07-04T00:00:00.000Z", collection_id=None):
    d = {"id": did, "title": title, "url": url, "updatedAt": updated}
    if collection_id:
        d["collectionId"] = collection_id
    return d


# ── US-002: lookup_by_author ─────────────────────────────────────────
def test_lookup_not_found():
    client = FakeAuthorClient(users=[_user("u1", "다른사람")])
    res = lookup_by_author(client, "다윗")
    assert res.status == "not_found"
    assert res.documents == []


def test_lookup_empty_name_is_not_found():
    client = FakeAuthorClient(users=[_user("u1", "다윗")])
    res = lookup_by_author(client, "   ")
    assert res.status == "not_found"


def test_lookup_ambiguous_lists_candidates():
    client = FakeAuthorClient(users=[_user("u1", "다윗", "david1@x.com"), _user("u2", "다윗", "david2@x.com")])
    res = lookup_by_author(client, "다윗")
    assert res.status == "ambiguous"
    assert len(res.candidates) == 2
    assert {c["email"] for c in res.candidates} == {"david1@x.com", "david2@x.com"}


def test_lookup_ok_with_docs_and_absolute_url():
    client = FakeAuthorClient(
        users=[_user("u1", "다윗")],
        docs_by_user={"u1": [_rawdoc("d1", "기획안", "/doc/plan-d1"), _rawdoc("d2", "회의록", "https://wiki.example.com/doc/m-d2")]},
    )
    res = lookup_by_author(client, "다윗")
    assert res.status == "ok"
    assert res.user["id"] == "u1"
    assert [d.title for d in res.documents] == ["기획안", "회의록"]
    # 상대경로는 base_url로 절대화, 이미 절대경로면 그대로
    assert res.documents[0].url == "https://wiki.example.com/doc/plan-d1"
    assert res.documents[1].url == "https://wiki.example.com/doc/m-d2"


def test_lookup_ok_but_no_documents():
    client = FakeAuthorClient(users=[_user("u1", "다윗")], docs_by_user={"u1": []})
    res = lookup_by_author(client, "다윗")
    assert res.status == "ok"
    assert res.documents == []


def test_lookup_exact_match_preferred_over_substring():
    # "다윗"이 정확히 일치하는 u1과, 이름에 "다윗"이 포함된 u2가 함께 있으면 정확일치만 택해 ok가 된다.
    client = FakeAuthorClient(
        users=[_user("u1", "다윗"), _user("u2", "다윗현")],
        docs_by_user={"u1": [_rawdoc("d1", "문서", "/doc/x")]},
    )
    res = lookup_by_author(client, "다윗")
    assert res.status == "ok"
    assert res.user["id"] == "u1"


def test_lookup_scopes_to_collection():
    client = FakeAuthorClient(
        users=[_user("u1", "다윗")],
        docs_by_user={"u1": [_rawdoc("d1", "보안문서", "/doc/s", collection_id="col-sec"), _rawdoc("d2", "기타", "/doc/o")]},
        collections=[{"id": "col-sec", "name": "보안"}],
    )
    res = lookup_by_author(client, "다윗", collection="보안")
    assert [d.title for d in res.documents] == ["보안문서"]
    assert client.author_calls[-1]["collection_id"] == "col-sec"


# ── US-003: CLI --author 분기 ────────────────────────────────────────
def test_format_author_result_messages():
    assert "찾지 못했습니다" in format_author_result(AuthorLookupResult(status="not_found", name="없음"))
    amb = AuthorLookupResult(status="ambiguous", name="다윗", candidates=[_user("u1", "다윗", "a@x.com")])
    assert "여러 명" in format_author_result(amb) and "a@x.com" in format_author_result(amb)


def test_author_command_lists_docs_without_llm():
    # answerer(LLM)를 전혀 주입하지 않고, 클라이언트만으로 목록 텍스트를 만든다 = RAG/LLM 우회 증명.
    client = FakeAuthorClient(
        users=[_user("u1", "다윗")],
        docs_by_user={"u1": [_rawdoc("d1", "기획안", "/doc/plan-d1")]},
    )
    out = author_command("다윗", client=client, limit=50, collection=None)
    assert "다윗" in out and "기획안" in out
    assert "https://wiki.example.com/doc/plan-d1" in out
