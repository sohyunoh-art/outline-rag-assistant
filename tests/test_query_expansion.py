"""query expansion(검색 앞단) 검증 — 외부 API/CLI 없이 가짜 더블로.

검증:
  - _parse_terms: 번호·불릿·따옴표 제거, stopword 제거, 중복제거, 상한
  - ClaudeCliQueryExpander: fake runner로 출력 파싱
  - expand(): LLM 실패 시 예외 대신 빈 리스트 (graceful)
  - build_query_expander: ANSWERER_BACKEND에 따른 백엔드 선택
  - Retriever 통합: 확장어 검색·득표수 병합·본문 truncate·확장 실패 fallback
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402
from core.query_expander import (  # noqa: E402
    ClaudeCliQueryExpander,
    QueryExpander,
    _parse_terms,
    build_query_expander,
)
from core.retriever import Retriever  # noqa: E402


# ── _parse_terms ─────────────────────────────────────────────────────
def test_parse_terms_cleans_bullets_quotes_and_stopwords():
    raw = '1. 도선사\n- pilot\n* "harbor pilot"\n회사\n어떻게\n도선사\n'
    terms = _parse_terms(raw)
    # 번호/불릿/따옴표 제거, stopword(회사·어떻게) 제거, 중복(도선사) 제거
    assert terms == ["도선사", "pilot", "harbor pilot"]


def test_parse_terms_caps_at_max():
    raw = "\n".join(f"term{i}" for i in range(20))
    assert len(_parse_terms(raw)) == config.MAX_EXPANSION_TERMS


def test_parse_terms_drops_single_char_and_empty():
    assert _parse_terms("\n  \nx\n상태 관리\n") == ["상태 관리"]


# ── ClaudeCliQueryExpander ───────────────────────────────────────────
def test_cli_expander_parses_runner_output():
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = "pilot\n도선\nharbor pilot"
        stderr = ""

    def fake_runner(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input", "")
        return FakeProc()

    exp = ClaudeCliQueryExpander(runner=fake_runner)
    terms = exp.expand("도선사가 뭐야?")
    assert terms == ["pilot", "도선", "harbor pilot"]
    assert captured["cmd"][0] == config.CLAUDE_CLI_COMMAND
    assert "도선사" in captured["input"]


def test_cli_expander_returns_empty_on_error():
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    exp = ClaudeCliQueryExpander(runner=lambda *a, **k: FakeProc())
    # 실패해도 예외를 던지지 않고 빈 리스트 → retriever가 fallback 하도록
    assert exp.expand("질문") == []


def test_cli_expander_returns_empty_on_runner_exception():
    def boom(*a, **k):
        raise TimeoutError("timed out")

    exp = ClaudeCliQueryExpander(runner=boom)
    assert exp.expand("질문") == []


# ── build_query_expander ─────────────────────────────────────────────
def test_build_query_expander_selects_backend(monkeypatch):
    monkeypatch.delenv(config.ENV_ANSWERER_BACKEND, raising=False)
    assert isinstance(build_query_expander(), QueryExpander)
    monkeypatch.setenv(config.ENV_ANSWERER_BACKEND, "claude_cli")
    assert isinstance(build_query_expander(), ClaudeCliQueryExpander)


# ── Retriever 통합 ───────────────────────────────────────────────────
class FakeExpander:
    def __init__(self, terms):
        self._terms = terms
        self.calls = []

    def expand(self, question):
        self.calls.append(question)
        return list(self._terms)


def _doc(did, ranking):
    return {"id": did, "title": did.upper(), "url": f"https://wiki/{did}", "_ranking": ranking}


def test_retriever_uses_expansion_and_vote_merge():
    # 검색어별 결과: 정답 문서 'navlue'는 'Recoil'과 '전역 상태' 두 검색어가 함께 끌어온다(득표 2).
    # 노이즈 'pdr'은 원문 질문 하나만 끌어오고(득표 1) ranking은 더 높다.
    table = {
        "프론트엔드 상태 관리 어떻게?": [_doc("pdr", 0.9)],
        "Recoil": [_doc("navlue", 0.4)],
        "전역 상태": [_doc("navlue", 0.5), _doc("onboarding", 0.3)],
    }

    # FakeOutlineClient는 콜러블을 (query, collection_id) 위치인자로 호출한다(test_structure 참고)
    def search_fn(query, collection_id):
        return list(table.get(query, []))

    docs_body = {
        "navlue": {"id": "navlue", "title": "Navlue 온보딩", "url": "u/n", "text": "Recoil 사용"},
        "pdr": {"id": "pdr", "title": "PDR", "url": "u/p", "text": "x"},
        "onboarding": {"id": "onboarding", "title": "온보딩", "url": "u/o", "text": "y"},
    }

    from test_structure import FakeOutlineClient  # 재사용

    client = FakeOutlineClient(search_results=search_fn, documents=docs_body)
    exp = FakeExpander(["Recoil", "전역 상태"])
    r = Retriever(client, collections=[], max_docs=3, expander=exp)
    out = r.search("프론트엔드 상태 관리 어떻게?")

    # 득표 2인 navlue가 ranking이 더 높은 pdr보다 앞서야 한다
    assert out[0].id == "navlue"
    assert exp.calls == ["프론트엔드 상태 관리 어떻게?"]
    # 원문 + 확장어 2개가 모두 검색됐는지
    assert {c["query"] for c in client.search_calls} == {"프론트엔드 상태 관리 어떻게?", "Recoil", "전역 상태"}


def test_retriever_truncates_huge_body():
    from test_structure import FakeOutlineClient

    big = "가" * 20000
    client = FakeOutlineClient(
        search_results=[_doc("a", 1.0)],
        documents={"a": {"id": "a", "title": "A", "url": "u/a", "text": big}},
    )
    r = Retriever(client, collections=[], max_docs=1, max_doc_chars=8000)
    out = r.search("질문")
    assert len(out[0].text) < len(big)
    assert "생략" in out[0].text


def test_retriever_falls_back_when_expander_empty():
    # 확장기가 빈 리스트를 주면(=실패) 기존 토큰 fallback 경로로 동작해야 한다.
    def search_fn(query, collection_id):
        return [_doc("a", 1.0)] if query == "휴가" else []

    from test_structure import FakeOutlineClient

    client = FakeOutlineClient(
        search_results=search_fn,
        documents={"a": {"id": "a", "title": "A", "url": "u/a", "text": "x"}},
    )
    r = Retriever(client, collections=[], max_docs=5, expander=FakeExpander([]))
    out = r.search("휴가 신청 방법은?")
    assert [d.id for d in out] == ["a"]
