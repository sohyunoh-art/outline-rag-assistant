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

from core.assistant import Answer, Assistant  # noqa: E402

ASSISTANTS_DIR = ROOT / "assistants"


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
    parser.add_argument("question", nargs="*", help="질문. 생략하면 대화형 모드로 진입")
    args = parser.parse_args()

    load_dotenv()
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
