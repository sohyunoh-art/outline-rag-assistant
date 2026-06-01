# Outline 사내 문서 RAG 어시스턴트

사내 **Outline 위키를 근거로 질문에 답하는** 어시스턴트입니다.
"문서 찾기"가 아니라, 문서 **내용을 읽고 종합해** 답합니다.
예) `도선사가 뭐야?`, `프론트엔드 팀은 상태 관리를 어떻게 해?`

- ✅ **읽기 전용** — 문서를 생성·수정·삭제하지 않습니다 (검색·열람·목록 조회만).
- ✅ **권한 안전** — 내 토큰 권한 안에서만 검색됩니다. 내가 못 보는 문서는 답에도 안 나옵니다.
- ✅ **확장 쉬움** — 새 용도 추가 = `assistants/`에 YAML 한 개 추가. 코어 코드는 안 건드립니다.

> 이 도구는 **각자 자기 컴퓨터에서 돌리는 CLI**입니다(호스팅 서비스 아님).
> 팀원이 쓰려면 코드를 받아 본인 자격증명으로 실행합니다. → [팀에 공유하기](#팀에-공유하기)

---

## 목차

1. [빠른 시작 (TL;DR)](#빠른-시작-tldr)
2. [사전 준비물](#사전-준비물)
3. [설치](#설치)
4. [설정 (.env)](#설정-env)
5. [실행](#실행)
6. [작성자별 문서 조회 (`--author`)](#작성자별-문서-조회---author)
7. [동작 방식 (RAG)](#동작-방식-rag)
8. [문제 해결 (Troubleshooting)](#문제-해결-troubleshooting)
9. [새 어시스턴트 추가하는 법](#새-어시스턴트-추가하는-법)
10. [테스트](#테스트)
11. [답변 규칙 · 모델 교체](#답변-규칙-모든-어시스턴트-공통)
12. [폴더 구조](#폴더-구조)
13. [팀에 공유하기](#팀에-공유하기)

---

## 빠른 시작 (TL;DR)

이미 Python·git이 있고 Outline 토큰을 발급받았다면, 복붙 5줄이면 끝납니다.

```bash
git clone https://github.com/sohyunoh-art/outline-rag-assistant.git
cd outline-rag-assistant
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # ← .env 열어서 값 채우기 (아래 '설정' 참고)
```

```bash
# 연결부터 확인 (Claude 없이 검색·열람만 점검)
python tools/check_outline.py "테스트"

# 질문하기
python -m cli.main --assistant general "도선사가 뭐야?"
```

처음이라 토큰 발급·백엔드 선택이 헷갈리면 아래 [사전 준비물](#사전-준비물)부터 차근차근 보세요.

---

## 사전 준비물

| 준비물 | 설명 | 확인 방법 |
|---|---|---|
| **Python 3.10 이상** | CLI 실행 환경 | `python3 --version` (Windows는 `python --version`) |
| **git** | 코드 내려받기 | `git --version` |
| **Outline 접근 권한** | 사내 위키(`outline.seadronix.com`) 계정 | 브라우저로 위키 로그인이 되면 OK |
| **Outline API 토큰** | 본인 계정으로 발급 (→ [발급법](#1-outline-api-토큰-발급-필수)) | 아래 절차 |
| **답변 백엔드 1개** | 둘 중 하나 (→ [백엔드 선택](#2-답변-백엔드-선택-중요)) | 아래 결정 가이드 |

> **답변 백엔드?** 검색은 Outline이 하지만, 답을 *문장으로 생성*하는 건 Claude입니다.
> 그 Claude를 ① **로컬 Claude Code 로그인**으로 부를지(`claude_cli`, 키 불필요),
> ② **Anthropic API 키**로 부를지(`anthropic`) 하나를 고릅니다.

---

## 설치

```bash
# 1) 내려받기
git clone https://github.com/sohyunoh-art/outline-rag-assistant.git
cd outline-rag-assistant

# 2) 가상환경 만들고 활성화
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux / WSL
# .venv\Scripts\activate           # Windows PowerShell
# .venv\Scripts\activate.bat       # Windows cmd

# 3) 의존성 설치
pip install -r requirements.txt
```

설치되는 패키지: `anthropic`, `requests`, `PyYAML`, `python-dotenv`, `pytest`.

> **Windows 안내**: 명령은 `python3` 대신 `python`을 쓰세요. 가상환경 활성화가 되면
> 프롬프트 앞에 `(.venv)`가 붙습니다. 활성화는 새 터미널을 열 때마다 다시 해줘야 합니다.

---

## 설정 (.env)

```bash
cp .env.example .env
# .env 를 편집기로 열어 값을 채웁니다.
```

`.env` 항목:

| 변수 | 설명 |
|---|---|
| `ANSWERER_BACKEND` | 답변 백엔드. `anthropic`(기본, API 키 사용) 또는 `claude_cli`(키 불필요) |
| `ANTHROPIC_API_KEY` | Claude API 키. `ANSWERER_BACKEND=claude_cli`면 **비워둬도 됨** |
| `OUTLINE_API_URL` | Outline 주소. **끝에 `/api`를 붙이지 마세요** (예: `https://outline.seadronix.com`) |
| `OUTLINE_API_TOKEN` | Outline API 토큰 (아래 발급법) |

> ⚠️ `.env`에는 **실제 토큰**이 들어갑니다. `.gitignore`로 깃 추적에서 제외돼 있으니
> **절대 커밋하지 마세요.** 남에게 줄 때는 토큰이 아니라 "발급 방법"을 알려주세요.

### 1) Outline API 토큰 발급 (필수)

1. Outline 웹에 로그인합니다.
2. 좌측 하단 프로필(또는 워크스페이스) → **Settings(설정)**.
3. 좌측 메뉴 **API Tokens**.
4. **New API token / Create token** → 이름(예: `rag-assistant`) 지정 후 생성.
5. **생성 시 한 번만 보이는** 토큰 문자열을 복사해 `.env`의 `OUTLINE_API_TOKEN`에 붙여넣습니다.

> 토큰은 **본인 권한**으로 동작합니다 — 내가 볼 수 있는 문서만 검색·열람됩니다.
> `OUTLINE_API_URL`은 평소 위키에 접속하는 브라우저 주소에서 경로(`/doc/...`)를 뗀 부분입니다.

### 2) 답변 백엔드 선택 (중요)

**Anthropic API 키가 있나요?**

- **아니오 (대부분 이 경우)** → `.env`에 한 줄만 바꾸세요: `ANSWERER_BACKEND=claude_cli`
  - 조건: 이 컴퓨터에 **Claude Code CLI(`claude`)가 설치·로그인**돼 있어야 합니다.
    터미널에서 `claude` 명령이 동작하면 OK. `ANTHROPIC_API_KEY`는 비워둬도 됩니다.
  - 내부적으로 `claude -p`를 호출합니다.
- **예** → `ANSWERER_BACKEND=anthropic`(기본값) 그대로 두고 `ANTHROPIC_API_KEY`를 채웁니다.
  - 키 발급: https://console.anthropic.com → API Keys.

> 나중에 키가 생기면 `ANSWERER_BACKEND`만 `anthropic`으로 바꾸면 됩니다. 코드는 안 건드려도 됩니다.

### 3) 연결 확인 (답변 생성 전에 검색·열람만 점검)

```bash
python tools/check_outline.py "테스트"
```

- `✓ 인증 성공. 접근 가능한 컬렉션 N개:` 가 나오면 토큰·URL이 올바른 것입니다.
- 실패하면 [문제 해결](#문제-해결-troubleshooting)의 Outline 항목을 보세요.
- 이 도구는 **Anthropic 키 없이도** 동작합니다(검색·열람만 하므로).

---

## 실행

```bash
# 단발 질문
python -m cli.main --assistant general "휴가 신청은 어떻게 하나요?"

# 대화형(REPL) — 질문을 빼면 진입, 종료는 Ctrl+C / Ctrl+D
python -m cli.main --assistant general

# 어시스턴트 바꿔서
python -m cli.main --assistant onboarding "첫 출근날 무엇부터 하면 되나요?"
```

답변 끝에는 항상 **근거 문서 제목과 Outline 링크**가 출처로 붙습니다.

---

## 작성자별 문서 조회 (`--author`)

"특정 사람이 작성한 문서 목록"은 전문검색(RAG)이 아니라 **작성자 필터**가 필요합니다.
`--author`는 LLM/Anthropic 키 없이 Outline REST(`users.list`로 이름→사용자 해석 후
`documents.list`로 필터)만으로 **결정적 목록**을 출력합니다.

```bash
# "다윗"님이 작성한 문서 목록
python -m cli.main --author "다윗"

# 컬렉션으로 범위 한정 + 최대 20건
python -m cli.main --author "다윗" --collection "업무 자료" --limit 20

# (동형 진단 도구) 검색 대신 작성자 필터만 빠르게 확인
python tools/list_by_author.py "다윗"
```

- 이름에 맞는 사용자가 **없으면** "사용자를 찾지 못했습니다", **여러 명**이면 후보(이름·이메일)를
  보여주고 더 구체적으로 지정하도록 안내합니다.
- 토큰 권한 안에서 보이는 문서만 목록에 나타납니다.

---

## 동작 방식 (RAG)

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

> RAG는 "미리 학습"하지 않습니다. 질문할 때마다 관련 문서를 즉석에서 읽고 답하므로,
> 문서가 바뀌어도 재학습이 필요 없고 항상 최신 내용을 따릅니다.

---

## 문제 해결 (Troubleshooting)

| 증상 / 메시지 | 원인 | 해결 |
|---|---|---|
| `claude: command not found` (또는 claude CLI 오류) | `ANSWERER_BACKEND=claude_cli`인데 Claude Code가 설치/로그인 안 됨 | Claude Code를 설치·로그인하거나, Anthropic 키가 있으면 `ANSWERER_BACKEND=anthropic`으로 전환 |
| `Invalid API key` / 인증 오류 | `anthropic` 백엔드인데 `ANTHROPIC_API_KEY`가 비었거나 잘못됨 | 키를 채우거나, 키가 없으면 `ANSWERER_BACKEND=claude_cli`로 전환 |
| `[연결 실패]` / Outline 401·403 | `OUTLINE_API_TOKEN`이 틀렸거나 만료, 권한 부족 | 토큰 재발급 후 `.env` 갱신 |
| Outline 404 / 이상한 경로 오류 | `OUTLINE_API_URL` 끝에 `/api`를 붙였거나 주소 오타 | `/api` **빼고** 도메인까지만 (예: `https://outline.seadronix.com`) |
| "관련 문서를 찾지 못했습니다" 만 계속 | ① 위키에 정말 그 내용이 없음 ② 내 권한 밖 문서 ③ 검색어가 너무 빗나감 | `python tools/check_outline.py "키워드"`로 검색 자체가 되는지 확인. 권한·내용 존재 여부 점검 |
| `ModuleNotFoundError` / `No module named ...` | 가상환경 미활성화 또는 설치 안 함 | `source .venv/bin/activate` 후 `pip install -r requirements.txt` |
| `RuntimeError: OUTLINE_API_URL와 ...를 .env에 설정` | `.env`가 없거나 값이 빔 | `cp .env.example .env` 후 값 입력. 명령은 프로젝트 루트에서 실행 |
| Windows에서 `python3` 안 됨 | Windows는 런처가 `python` | `python -m cli.main ...`, `python -m venv .venv` 사용 |

> 막히면 **`python tools/check_outline.py "검색어"`** 부터 돌려보세요.
> "검색·열람"과 "답변 생성"을 분리해 보여주므로, 문제가 Outline 쪽인지 Claude 쪽인지 바로 갈립니다.

---

## 새 어시스턴트 추가하는 법

코어 코드는 건드리지 않습니다. **`assistants/`에 YAML 한 개만** 추가하면 됩니다.

1. 기존 파일 복사: `cp assistants/general.yaml assistants/security.yaml`
2. 값만 변경:
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

---

## 테스트

API 키 없이 가짜 클라이언트로 구조·동작을 검증합니다.

```bash
pip install -r requirements.txt
python -m pytest -q
```

---

## 답변 규칙 (모든 어시스턴트 공통)

`core/config.py`에 고정돼 있어, 모든 어시스턴트가 아래를 지킵니다.

- 문서에 실제로 있는 내용만으로 답하고, 근거가 없으면 "관련 문서를 찾지 못했습니다"라고 답합니다.
- 답변 끝에 근거 문서의 제목과 Outline 링크를 출처로 표시합니다.
- 문서 간 내용이 충돌하면 그 사실을 알리고 양쪽을 보여줍니다.
- 질문과 같은 언어로 답합니다.

### 모델 교체

`core/config.py`의 `ANSWERER_MODEL` 한 줄만 바꾸면 됩니다.

---

## 폴더 구조

```
outline-rag-assistant/
├── core/                  # 용도와 무관한 공통 엔진 (건드릴 일 거의 없음)
│   ├── config.py          # 모델명·엔드포인트·환경변수·고정 답변규칙·튜닝 상수
│   ├── outline_client.py  # Outline REST 읽기전용 클라이언트
│   ├── retriever.py       # 검색·열람 로직 (확장어 병합·본문 truncate 포함)
│   ├── query_expander.py  # 질문 → 검색어 묶음 (LLM query expansion)
│   ├── author_lookup.py   # 작성자 이름→사용자→문서목록 (RAG 아님, 작성자 필터)
│   ├── answerer.py        # 문서+role_prompt로 Claude 답변 생성 (anthropic 백엔드)
│   ├── answerer_claude_cli.py  # 답변 백엔드 대안 (로컬 claude CLI, 키 불필요)
│   └── assistant.py       # 설정을 읽어 expander+retriever+answerer를 조립
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

---

## 팀에 공유하기

이건 호스팅 서비스가 아니라 **각자 자기 컴퓨터에서 돌리는 CLI**입니다. 그래서 공유 = "이 저장소를
각자 받아 본인 `.env`를 채워 실행"입니다. 받는 방법은 셋 중 편한 것:

- `git clone https://github.com/sohyunoh-art/outline-rag-assistant.git`
- GitHub → **Code → Download ZIP** (git 없이)
- `pip install "git+https://github.com/sohyunoh-art/outline-rag-assistant.git"` (패키지 형태)

그다음은 위 [설치](#설치) · [설정](#설정-env)과 동일합니다.

### 공유할 때 꼭 알아둘 것 (보안·권한)

- **`.env`는 깃에 올라가지 않습니다**(`.gitignore`로 차단). 실제 토큰이 든 파일이니 **절대 커밋 금지.**
  공유는 토큰이 아니라 "발급 방법"을 알려주는 식으로 합니다.
- **각자 자기 토큰**을 발급하세요. 토큰 = 그 사람 권한이라, 자기가 볼 수 있는 문서만 답에 나옵니다.
- **저장소 공개 범위**: Private이면 팀원을 collaborator로 초대해야 clone 됩니다. Public이면 누구나
  clone 할 수 있지만, **사내 Outline 접근 + 본인 토큰**이 없으면 실제 답은 안 나옵니다(코드만 보임).
- (선택) 외부에 정식 오픈소스로 공개하려면 `LICENSE` 파일 추가를 권합니다.
