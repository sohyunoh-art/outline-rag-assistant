# Outline 사내 문서 RAG 어시스턴트

사내 Outline 위키를 근거로 질문에 답하는 어시스턴트입니다.
**하나의 코어 엔진** 위에 용도별 어시스턴트를 **설정 파일(YAML)** 로만 갈아 끼울 수 있습니다.
새 어시스턴트 추가 = "YAML 파일 한 개 추가"로 끝납니다.

## 동작 방식 (RAG, 읽기 전용)

0. **검색어 확장(query expansion)** — 질문을 그대로 검색하면 어휘가 안 맞아 자주 빗나갑니다
   ("도선사"는 문서엔 "pilot", "상태 관리"는 "Zustand/Recoil"로 적혀 있는 식). LLM이 질문을
   문서에 실제로 박혀 있을 검색어 묶음(조사 제거·영문 동의어·기술명, 보수적 최대 6개)으로 바꿉니다.
   실패하면 조용히 건너뛰고 아래 검색을 그대로 진행합니다(보강일 뿐 의존하지 않음).
1. **검색(retriever)** — 원문 질문 + 확장 검색어들을 Outline REST API(`/documents.search`)로 검색해
   문서 id 기준으로 합칩니다. 여러 검색어가 함께 끌어온 문서(득표수)를 우선해 관련도를 매깁니다.
   설정에 `collections`가 있으면 그 범위로 한정하고, 그래도 비면 키워드를 쪼개 재검색합니다.
2. **열람** — 관련도 높은 상위 문서의 본문(`/documents.info`)을 가져옵니다.
   거대 문서가 컨텍스트를 독점하지 않도록 본문은 일정 길이(`MAX_DOC_CHARS`)에서 자릅니다.
3. **답변(answerer)** — 확보한 본문 + 설정의 `role_prompt`를 Claude에게 주고 답을 생성합니다.

> 문서를 **생성·수정·삭제하지 않습니다.** 클라이언트는 검색·열람·컬렉션 조회만 호출합니다.

## 폴더 구조

```
outline-rag-assistant/
├── core/                  # 용도와 무관한 공통 엔진 (건드릴 일 거의 없음)
│   ├── config.py          # 모델명·엔드포인트·환경변수·고정 답변규칙을 한 곳에
│   ├── outline_client.py  # Outline REST 읽기전용 클라이언트
│   ├── retriever.py       # 검색·열람 로직
│   ├── author_lookup.py   # 작성자 이름→사용자→문서목록 (RAG 아님, 작성자 필터)
│   ├── answerer.py        # 문서+role_prompt로 Claude 답변 생성
│   └── assistant.py       # 설정을 읽어 retriever+answerer를 조립
├── assistants/            # 용도별 설정 (코어를 건드리지 않음)
│   ├── general.yaml       # 범용 Q&A
│   └── onboarding.yaml    # 온보딩 도우미 (설정만으로 추가한 두 번째 예시)
├── cli/main.py            # 터미널 진입점 (RAG Q&A + --author 작성자 조회)
├── tools/                 # check_outline.py(연결 진단) · list_by_author.py(작성자 조회)
├── tests/                 # 가짜 클라이언트 기반 구조·동작 테스트
├── .env.example
├── requirements.txt
└── README.md
```

## 설치

```bash
cd outline-rag-assistant
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 설정

```bash
cp .env.example .env
# .env 를 열어 값 3개를 채웁니다.
```

| 변수 | 설명 |
|---|---|
| `ANSWERER_BACKEND` | 답변 백엔드. `anthropic`(기본, API 키 사용) 또는 `claude_cli`(아래 참고) |
| `ANTHROPIC_API_KEY` | Claude API 키 (https://console.anthropic.com). `claude_cli` 백엔드면 비워도 됨 |
| `OUTLINE_API_URL` | Outline 주소. 끝에 `/api`를 붙이지 마세요 (예: `https://wiki.회사.com`) |
| `OUTLINE_API_TOKEN` | Outline API 토큰 (아래 발급법) |

### API 키 없이 쓰기 (`ANSWERER_BACKEND=claude_cli`)

Anthropic API 키가 아직 없다면, 로컬에 설치된 **Claude Code CLI(`claude`)의 기존 로그인**으로
답변을 생성할 수 있습니다. `.env`에 `ANSWERER_BACKEND=claude_cli` 한 줄만 넣으면 됩니다
(`ANTHROPIC_API_KEY`는 비워둬도 됨). 내부적으로 `claude -p`를 호출하며, 검색·열람은 동일하게
Outline API를 씁니다. 나중에 API 키가 생기면 `ANSWERER_BACKEND=anthropic`으로 바꾸기만 하면 됩니다.

> 연결만 먼저 확인하려면(답변 생성 빼고 검색·열람만): `python tools/check_outline.py "검색어"`

### Outline API 토큰 발급법

1. Outline 웹에 로그인합니다.
2. 좌측 하단 프로필(또는 워크스페이스) → **Settings(설정)** 로 들어갑니다.
3. 좌측 메뉴에서 **API Tokens** 를 엽니다.
4. **New API token** / **Create token** 을 눌러 이름(예: `rag-assistant`)을 주고 생성합니다.
5. 생성 시 한 번만 보이는 토큰 문자열을 복사해 `.env`의 `OUTLINE_API_TOKEN`에 붙여넣습니다.

> 토큰은 **본인 권한**으로 동작합니다. 즉 내가 접근 가능한 문서만 검색·열람됩니다 (권한 밖 문서는 보이지 않음).
> `OUTLINE_API_URL`은 평소 위키에 접속하는 브라우저 주소에서 경로를 뗀 부분입니다.

## 실행

```bash
# 단발 질문
python -m cli.main --assistant general "휴가 신청은 어떻게 하나요?"

# 대화형(REPL)
python -m cli.main --assistant general

# 어시스턴트 바꿔서
python -m cli.main --assistant onboarding "첫 출근날 무엇부터 하면 되나요?"
```

## 작성자별 문서 조회 (`--author`)

"특정 사람이 작성한 문서 목록"은 전문검색(RAG)이 아니라 **작성자 필터**가 필요합니다.
(MCP 도구만으로는 작성자 메타데이터가 없어 불가능했던 부분입니다.)
`--author`는 LLM/Anthropic 키 없이 Outline REST(`users.list`로 이름→사용자 해석 후
`documents.list`로 필터)만으로 **결정적 목록**을 출력합니다.

```bash
# "다윗"님이 작성한 문서 목록
python -m cli.main --author "다윗"

# 특정 컬렉션으로 범위를 한정하고, 최대 20건만
python -m cli.main --author "다윗" --collection "업무 자료" --limit 20

# (동형 진단 도구) — 검색 대신 작성자 필터만 빠르게 확인
python tools/list_by_author.py "다윗"
```

- 이름에 해당하는 사용자가 **없으면** "사용자를 찾지 못했습니다", **여러 명**이면(동명이인 등)
  후보(이름·이메일)를 보여주고 더 구체적으로 지정하도록 안내합니다.
- 토큰은 **본인 권한**으로 동작하므로, 내가 볼 수 있는 문서만 목록에 나타납니다.

## 새 어시스턴트 추가하는 법

코어 코드는 건드리지 않습니다. **`assistants/` 에 YAML 한 개만** 추가하면 됩니다.

1. 기존 파일을 복사합니다: `cp assistants/general.yaml assistants/security.yaml`
2. 값만 바꿉니다:
   ```yaml
   name: 보안 정책 도우미
   description: 정보보안·접근권한 관련 질문 전용
   collections: ["보안"]        # 이 컬렉션 범위로만 검색 (비우면 전체)
   max_docs: 5
   role_prompt: |
     너는 사내 보안 정책 안내자다.
     보안 문서를 근거로 정확하고 보수적으로 답한다.
   ```
3. 실행: `python -m cli.main --assistant security "VPN 신청 절차는?"`

설정 필드:

| 필드 | 의미 |
|---|---|
| `name` | 어시스턴트 이름 (필수) |
| `description` | 한 줄 설명 |
| `collections` | 검색 범위를 좁힐 컬렉션 **이름** 목록. 비우면 전체 문서 대상 |
| `max_docs` | 답변 근거로 본문을 열람할 최대 문서 수 |
| `role_prompt` | 이 어시스턴트의 역할 프롬프트 (필수). 코어의 고정 답변규칙 **위에** 얹힘 |

## 테스트

API 키 없이 가짜 클라이언트로 구조·동작을 검증합니다.

```bash
pip install -r requirements.txt
python -m pytest -q
```

## 답변 규칙 (모든 어시스턴트 공통, `core/config.py`에 고정)

- 문서에 실제로 있는 내용만으로 답하고, 근거가 없으면 "관련 문서를 찾지 못했습니다"라고 답합니다.
- 답변 끝에 근거 문서의 제목과 Outline 링크를 출처로 표시합니다.
- 문서 간 내용이 충돌하면 그 사실을 알리고 양쪽을 보여줍니다.
- 질문과 같은 언어로 답합니다.

## 모델 교체

`core/config.py`의 `ANSWERER_MODEL` 한 줄만 바꾸면 됩니다.
