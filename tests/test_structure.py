"""코어 구조·동작 검증 (외부 API 키 없이 가짜 클라이언트로).

핵심 검증:
  - config가 모델명·답변규칙을 한 곳에 모았는가
  - retriever의 컬렉션 한정·중복제거·max_docs·키워드 재검색
  - answerer의 system 프롬프트 결합·컨텍스트 구성
  - assistant의 YAML 조립과 ask() 흐름
  - 두 번째 어시스턴트가 코어 수정 없이 YAML 한 개로 동작 (구조 분리 증명)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from core import config  # noqa: E402
from core.answerer import Answerer, build_context  # noqa: E402
from core.answerer_claude_cli import ClaudeCliAnswerer  # noqa: E402
from core.assistant import Assistant, AssistantConfig, build_answerer  # noqa: E402
from core.retriever import Retriever, RetrievedDoc  # noqa: E402

ASSISTANTS_DIR = ROOT / "assistants"


# ── 가짜 더블들 ──────────────────────────────────────────────────────
class FakeOutlineClient:
    """검색/열람/컬렉션 동작을 흉내내는 가짜 Outline 클라이언트."""

    def __init__(self, search_results=None, documents=None, collections=None):
        # search_results: query별 결과를 단순화해 동일 결과를 반환
        self._search_results = search_results if search_results is not None else []
        self._documents = documents or {}
        self._collections = collections or []
        self.search_calls: list[dict] = []
        self.fetched_ids: list[str] = []

    def search_documents(self, query, *, collection_id=None, limit=config.DEFAULT_SEARCH_LIMIT):
        self.search_calls.append({"query": query, "collection_id": collection_id})
        # 빈 query 시뮬레이션: 결과가 콜러블이면 호출(키워드 재검색 테스트용)
        if callable(self._search_results):
            return self._search_results(query, collection_id)
        return list(self._search_results)

    def get_document(self, document_id):
        self.fetched_ids.append(document_id)
        return self._documents.get(document_id, {"id": document_id, "title": "", "url": "", "text": ""})

    def find_collection_ids(self, names):
        wanted = {n.strip().lower() for n in names}
        return [c["id"] for c in self._collections if c["name"].lower() in wanted]


class FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResp:
    def __init__(self, text):
        self.content = [FakeBlock(text)]


class FakeAnthropic:
    """anthropic.Anthropic() 대체. 마지막 호출 인자를 기록한다."""

    def __init__(self, reply="모의 답변"):
        self.reply = reply
        self.last_kwargs = None

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                self._outer.last_kwargs = kwargs
                return FakeResp(self._outer.reply)

        self.messages = _Messages(self)


def _doc(did, ranking, title="제목"):
    return {"id": did, "title": title, "url": f"https://wiki/{did}", "_ranking": ranking}


# ── US-001: config ───────────────────────────────────────────────────
def test_config_centralizes_model_and_rules():
    assert isinstance(config.ANSWERER_MODEL, str) and config.ANSWERER_MODEL
    # 4대 답변 규칙이 모두 들어 있는지 핵심 키워드로 확인
    for keyword in ["지어내지", "출처", "충돌", "같은 언어"]:
        assert keyword in config.BASE_SYSTEM_PROMPT
    assert config.OUTLINE_SEARCH_PATH and config.OUTLINE_INFO_PATH


# ── US-003: retriever ────────────────────────────────────────────────
def test_retriever_dedup_rank_and_max_docs():
    results = [_doc("a", 0.1), _doc("b", 0.9), _doc("a", 0.5), _doc("c", 0.7)]
    docs = {
        "a": {"id": "a", "title": "A", "url": "u/a", "text": "본문A"},
        "b": {"id": "b", "title": "B", "url": "u/b", "text": "본문B"},
        "c": {"id": "c", "title": "C", "url": "u/c", "text": "본문C"},
    }
    client = FakeOutlineClient(search_results=results, documents=docs)
    r = Retriever(client, collections=[], max_docs=2)
    out = r.search("질문")
    # 중복 a 제거 + ranking 내림차순(b, c, a) → max_docs=2 → b, c
    assert [d.id for d in out] == ["b", "c"]
    assert out[0].text == "본문B"
    # 전체검색이므로 collection_id 없이 1회 검색
    assert client.search_calls[0]["collection_id"] is None


def test_retriever_scopes_to_collections():
    client = FakeOutlineClient(
        search_results=[_doc("a", 1.0)],
        documents={"a": {"id": "a", "title": "A", "url": "u/a", "text": "x"}},
        collections=[{"id": "col1", "name": "온보딩"}, {"id": "col2", "name": "인사"}],
    )
    r = Retriever(client, collections=["온보딩", "인사"], max_docs=5)
    r.search("질문")
    called_scopes = {c["collection_id"] for c in client.search_calls}
    assert called_scopes == {"col1", "col2"}  # 지정 컬렉션 범위로만 검색


def test_retriever_token_fallback_when_empty():
    calls = {"queries": []}

    def search_fn(query, collection_id):
        calls["queries"].append(query)
        # 문장형 원문은 빈 결과, 토큰("휴가")으로 검색하면 결과 반환
        if query == "휴가":
            return [_doc("a", 1.0)]
        return []

    client = FakeOutlineClient(
        search_results=search_fn,
        documents={"a": {"id": "a", "title": "A", "url": "u/a", "text": "x"}},
    )
    r = Retriever(client, collections=[], max_docs=5)
    out = r.search("휴가 신청 방법은?")
    assert [d.id for d in out] == ["a"]
    # 1차는 문장 전체, 이후 토큰 단위 재검색이 일어남
    assert calls["queries"][0] == "휴가 신청 방법은?"
    assert "휴가" in calls["queries"]


# ── US-004: answerer ─────────────────────────────────────────────────
def test_answerer_system_prompt_combines_rules_and_role():
    a = Answerer("너는 온보딩 안내자다.", client=FakeAnthropic())
    sp = a.system_prompt
    assert "지어내지" in sp  # 코어 고정 규칙
    assert "온보딩 안내자" in sp  # role_prompt


def test_answerer_includes_docs_and_calls_model():
    fake = FakeAnthropic(reply="답변 본문")
    a = Answerer("역할", client=fake)
    docs = [RetrievedDoc(id="a", title="휴가 규정", url="https://wiki/a", text="본문내용")]
    text = a.answer("휴가 며칠?", docs)
    assert text == "답변 본문"
    # 모델·system·문서 컨텍스트가 호출에 반영됐는지
    assert fake.last_kwargs["model"] == config.ANSWERER_MODEL
    user_msg = fake.last_kwargs["messages"][0]["content"]
    assert "휴가 규정" in user_msg and "https://wiki/a" in user_msg and "본문내용" in user_msg


def test_build_context_no_docs():
    assert "검색된 문서 없음" in build_context([])


# ── US-005 / US-007: 첫 어시스턴트 조립 ──────────────────────────────
def test_general_assistant_assembles_and_asks():
    cfg = AssistantConfig.from_yaml(ASSISTANTS_DIR / "general.yaml")
    assert cfg.name == "범용 사내 Q&A"
    assert cfg.collections == []  # 전체 대상

    client = FakeOutlineClient(
        search_results=[_doc("a", 1.0)],
        documents={"a": {"id": "a", "title": "A", "url": "u/a", "text": "x"}},
    )
    assistant = Assistant(cfg, client=client, answerer=Answerer(cfg.role_prompt, client=FakeAnthropic("OK")))
    ans = assistant.ask("질문")
    assert ans.text == "OK"
    assert [d.id for d in ans.docs] == ["a"]


def test_config_requires_name_and_role(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("description: 이름과 역할이 없음\n", encoding="utf-8")
    with pytest.raises(ValueError):
        AssistantConfig.from_yaml(bad)


# ── US-008: 두 번째 어시스턴트 = YAML 한 개, 코어 수정 0 ─────────────
def test_second_assistant_loads_from_config_only():
    # onboarding.yaml 은 core/ 를 전혀 건드리지 않고 추가된 설정 파일이다.
    cfg = AssistantConfig.from_yaml(ASSISTANTS_DIR / "onboarding.yaml")
    assert cfg.name == "신규 입사자 온보딩 도우미"

    client = FakeOutlineClient(
        search_results=[_doc("z", 1.0)],
        documents={"z": {"id": "z", "title": "온보딩 가이드", "url": "u/z", "text": "환영"}},
    )
    assistant = Assistant(cfg, client=client, answerer=Answerer(cfg.role_prompt, client=FakeAnthropic("환영합니다")))
    ans = assistant.ask("첫 출근날 뭐하나요?")
    assert ans.text == "환영합니다"
    assert ans.docs[0].title == "온보딩 가이드"


def test_both_assistants_use_same_core_class():
    # 두 어시스턴트가 동일한 Assistant 코어 클래스로 만들어짐을 확인 (분리 증명)
    fake_client = FakeOutlineClient(search_results=[], documents={})
    a1 = Assistant(
        AssistantConfig.from_yaml(ASSISTANTS_DIR / "general.yaml"),
        client=fake_client, answerer=Answerer("r", client=FakeAnthropic()),
    )
    a2 = Assistant(
        AssistantConfig.from_yaml(ASSISTANTS_DIR / "onboarding.yaml"),
        client=fake_client, answerer=Answerer("r", client=FakeAnthropic()),
    )
    assert type(a1) is type(a2) is Assistant


# ── 답변 백엔드 선택 + claude CLI 백엔드 ────────────────────────────
def test_build_answerer_selects_backend(monkeypatch):
    monkeypatch.delenv(config.ENV_ANSWERER_BACKEND, raising=False)
    assert isinstance(build_answerer("역할"), Answerer)
    monkeypatch.setenv(config.ENV_ANSWERER_BACKEND, "claude_cli")
    assert isinstance(build_answerer("역할"), ClaudeCliAnswerer)


def test_claude_cli_answerer_builds_command_and_prompt():
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = "CLI 답변"
        stderr = ""

    def fake_runner(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input", "")
        return FakeProc()

    a = ClaudeCliAnswerer("온보딩 안내자다.", runner=fake_runner)
    docs = [RetrievedDoc(id="a", title="휴가 규정", url="https://outline/x", text="본문")]
    text = a.answer("휴가 며칠?", docs)

    assert text == "CLI 답변"
    # claude -p --system-prompt "<규칙+역할>" 형태
    assert captured["cmd"][0] == config.CLAUDE_CLI_COMMAND
    assert "-p" in captured["cmd"]
    sp_index = captured["cmd"].index("--system-prompt") + 1
    system_prompt = captured["cmd"][sp_index]
    assert "지어내지" in system_prompt and "온보딩 안내자" in system_prompt
    # 문서 컨텍스트는 stdin으로
    assert "휴가 규정" in captured["input"] and "https://outline/x" in captured["input"]


def test_claude_cli_answerer_raises_on_error():
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    a = ClaudeCliAnswerer("역할", runner=lambda *a, **k: FakeProc())
    with pytest.raises(RuntimeError):
        a.answer("q", [])
