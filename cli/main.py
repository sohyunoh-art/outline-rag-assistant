"""터미널 진입점: 어시스턴트를 골라 질문한다.

사용 예:
  python -m cli.main --assistant general "휴가 신청은 어떻게 하나요?"
  python -m cli.main --assistant general          # 대화형(REPL)
  python -m cli.main                              # 기본 general
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트를 import 경로에 추가 (python cli/main.py 직접 실행도 지원)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402
from core.assistant import Answer, Assistant  # noqa: E402
from core.author_lookup import AuthorLookupResult, lookup_by_author  # noqa: E402
from core.outline_client import OutlineClient  # noqa: E402

ASSISTANTS_DIR = ROOT / "assistants"


def format_author_result(result: AuthorLookupResult) -> str:
    """작성자 조회 결과를 사람이 읽을 텍스트로 렌더링한다(순수 함수, LLM 불필요)."""
    if result.status == "not_found":
        return f"'{result.name}'에 해당하는 사용자를 찾지 못했습니다. 이름 표기(공백·영문/한글)를 바꿔 다시 시도해보세요."
    if result.status == "ambiguous":
        lines = [f"'{result.name}'에 해당하는 사용자가 여러 명입니다. 더 구체적으로 지정해주세요:"]
        for u in result.candidates:
            email = u.get("email", "")
            lines.append(f"  - {u.get('name', '(이름 없음)')}{f' <{email}>' if email else ''}")
        return "\n".join(lines)
    # status == "ok"
    user = result.user or {}
    who = user.get("name") or result.name
    if not result.documents:
        return f"{who}님이 작성한 문서가 없습니다 (또는 내 권한으로 볼 수 있는 문서가 없습니다)."
    lines = [f"{who}님이 작성한 문서 {len(result.documents)}건:"]
    for d in result.documents:
        when = f"  (수정: {d.updated_at[:10]})" if d.updated_at else ""
        lines.append(f"  • {d.title}{when}\n    {d.url}")
    return "\n".join(lines)


def author_command(name: str, *, client, limit: int, collection: str | None) -> str:
    """--author 분기의 핵심: 작성자 조회만 수행하고 텍스트를 돌려준다. RAG/LLM(answerer)은 거치지 않는다."""
    result = lookup_by_author(client, name, collection=collection, limit=limit)
    return format_author_result(result)


def _config_path(name: str) -> Path:
    path = ASSISTANTS_DIR / f"{name}.yaml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in ASSISTANTS_DIR.glob("*.yaml"))) or "(없음)"
        sys.exit(f"어시스턴트 '{name}'를 찾을 수 없습니다. 사용 가능: {available}")
    return path


def _print_answer(answer: Answer) -> None:
    print("\n" + answer.text.strip() + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Outline 사내 문서 RAG 어시스턴트")
    parser.add_argument(
        "-a", "--assistant", default="general",
        help="어시스턴트 이름 (assistants/<이름>.yaml). 기본값: general",
    )
    parser.add_argument(
        "--author",
        help="특정 작성자가 쓴 문서 목록을 조회한다 (RAG/LLM 없이 결정적 목록 출력)",
    )
    parser.add_argument(
        "--collection",
        help="--author와 함께 쓸 때 조회 범위를 이 컬렉션 이름으로 한정",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="--author 조회 시 가져올 최대 문서 수 (기본: config.DEFAULT_AUTHOR_DOC_LIMIT)",
    )
    parser.add_argument("question", nargs="*", help="질문. 생략하면 대화형 모드로 진입")
    args = parser.parse_args()

    load_dotenv()

    # --author: RAG/LLM(Assistant.ask)을 거치지 않는 결정적 목록 조회 경로
    if args.author:
        try:
            client = OutlineClient()
        except RuntimeError as e:
            sys.exit(f"[설정 오류] {e}")
        limit = args.limit if args.limit is not None else config.DEFAULT_AUTHOR_DOC_LIMIT
        print("\n" + author_command(args.author, client=client, limit=limit, collection=args.collection) + "\n")
        return

    assistant = Assistant.from_config_file(_config_path(args.assistant))
    print(f"[{assistant.cfg.name}] {assistant.cfg.description}")

    if args.question:
        _print_answer(assistant.ask(" ".join(args.question)))
        return

    print("질문을 입력하세요. (종료: Ctrl+C 또는 Ctrl+D)")
    try:
        while True:
            q = input("\n질문> ").strip()
            if not q:
                continue
            _print_answer(assistant.ask(q))
    except (EOFError, KeyboardInterrupt):
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
