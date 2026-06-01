"""작성자별 문서 조회 (Anthropic 키 없이, 검색 대신 작성자 필터만 사용).

MCP 도구로는 불가능한 "특정 사람이 작성한 문서 목록"을 Outline REST로 직접 뽑는다.
사용: python tools/list_by_author.py "다윗"  [--collection 보안] [--limit 50]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cli.main import author_command  # noqa: E402
from core import config  # noqa: E402
from core.outline_client import OutlineClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Outline 작성자별 문서 조회")
    parser.add_argument("name", help="작성자 이름 (예: 다윗)")
    parser.add_argument("--collection", help="이 컬렉션 이름으로 범위 한정")
    parser.add_argument("--limit", type=int, default=config.DEFAULT_AUTHOR_DOC_LIMIT)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    try:
        client = OutlineClient()
    except RuntimeError as e:
        sys.exit(f"[설정 오류] {e}")

    print("\n" + author_command(args.name, client=client, limit=args.limit, collection=args.collection) + "\n")


if __name__ == "__main__":
    main()
