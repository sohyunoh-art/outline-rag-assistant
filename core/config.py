"""중앙 설정: 모델명·엔드포인트·환경변수 이름·고정 답변 규칙을 한 곳에 모은다.

여기만 고치면 모델 교체·엔드포인트 변경이 끝나도록 의도했다.
(지침서 "모델명은 코드에 흩지 말고 한 곳에 상수로" 요구를 만족시키는 자리)
"""
from __future__ import annotations

# ── Claude (Anthropic) ──────────────────────────────────────────────
# 답변 생성에 쓰는 모델. 교체하려면 이 한 줄만 바꾸면 된다.
ANSWERER_MODEL = "claude-sonnet-4-6"
ANSWERER_MAX_TOKENS = 2048

# 검색 앞단의 query expansion(질문→검색어)용. 짧은 출력이라 토큰·타임아웃을 작게 둔다.
QUERY_EXPANSION_MAX_TOKENS = 256
QUERY_EXPANSION_CLI_TIMEOUT = 60  # 초
# 확장 검색어 상한(보수적). 너무 넓히면 오히려 노이즈가 는다.
MAX_EXPANSION_TERMS = 6

# ── 답변 백엔드 선택 ────────────────────────────────────────────────
# "anthropic"   : Anthropic API 키 사용 (ANTHROPIC_API_KEY 필요)
# "claude_cli"  : 로컬에 설치된 claude CLI(Claude Code) 사용 — API 키 없이 기존 로그인으로 동작
DEFAULT_ANSWERER_BACKEND = "anthropic"
CLAUDE_CLI_COMMAND = "claude"
CLAUDE_CLI_TIMEOUT = 180  # 초

# ── Outline REST API ────────────────────────────────────────────────
# self-hosted든 클라우드든 base_url 뒤에 붙는 경로는 동일하다.
OUTLINE_SEARCH_PATH = "/api/documents.search"
OUTLINE_INFO_PATH = "/api/documents.info"
OUTLINE_COLLECTIONS_PATH = "/api/collections.list"
# 작성자별 조회용 (둘 다 읽기 전용 list 계열)
OUTLINE_USERS_PATH = "/api/users.list"
OUTLINE_DOCUMENTS_LIST_PATH = "/api/documents.list"

# ── 환경변수 이름 ───────────────────────────────────────────────────
ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
ENV_OUTLINE_URL = "OUTLINE_API_URL"      # 예: https://wiki.seadronix.com (끝에 /api 붙이지 말 것)
ENV_OUTLINE_TOKEN = "OUTLINE_API_TOKEN"
ENV_ANSWERER_BACKEND = "ANSWERER_BACKEND"  # "anthropic"(기본) 또는 "claude_cli"

# ── 검색 기본값 ─────────────────────────────────────────────────────
DEFAULT_MAX_DOCS = 5          # 답변 근거로 본문을 열람할 문서 수
DEFAULT_SEARCH_LIMIT = 10     # 검색 단계에서 후보로 가져올 문서 수
DEFAULT_AUTHOR_DOC_LIMIT = 50 # 작성자별 조회에서 가져올 문서 수
# 한 문서 본문을 답변 컨텍스트에 넣을 때의 최대 글자 수. 5만자짜리 요구사항 문서 하나가
# 컨텍스트를 독점해 정작 관련 문서를 희석시키는 것을 막는 가드.
MAX_DOC_CHARS = 8000

# ── 고정 답변 규칙 (모든 어시스턴트 공통) ───────────────────────────
# role_prompt(용도별 역할)는 이 규칙 "위에" 얹힌다. 규칙 자체는 코어가 보장한다.
BASE_SYSTEM_PROMPT = """\
너는 사내 Outline 문서를 근거로 답하는 어시스턴트다. 다음 규칙을 반드시 지켜라.

1. 제공된 문서에 실제로 있는 내용만으로 답한다. 근거를 찾지 못하면 지어내지 말고
   "관련 문서를 찾지 못했습니다."라고 솔직히 답한다.
2. 답변 끝에 '출처' 섹션을 만들고, 근거가 된 문서의 제목과 Outline 링크를 모두 나열한다.
3. 문서 간 내용이 충돌하면 그 사실을 명시하고 양쪽 내용을 모두 보여준다.
4. 질문과 같은 언어로 답한다.
"""
