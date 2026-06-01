"""Outline 연결 진단 (Anthropic 키 없이 검색·열람만 확인).

답변 생성(Claude) 빼고, retriever 절반만 실제 위키에 붙여 확인한다.
사용: python tools/check_outline.py "검색해볼 질문"
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.outline_client import OutlineClient  # noqa: E402
from core.retriever import Retriever  # noqa: E402


def main() -> None:
    load_dotenv(ROOT / ".env")
    query = " ".join(sys.argv[1:]) or "테스트"

    try:
        client = OutlineClient()
    except RuntimeError as e:
        sys.exit(f"[설정 오류] {e}")

    # 1) 인증 확인: 컬렉션 목록
    try:
        collections = client.list_collections(limit=100)
    except Exception as e:  # noqa: BLE001
        sys.exit(
            f"[연결 실패] Outline 호출이 거부됐습니다: {e}\n"
            "→ OUTLINE_API_URL(끝에 /api 없이)과 OUTLINE_API_TOKEN을 다시 확인하세요."
        )
    print(f"✓ 인증 성공. 접근 가능한 컬렉션 {len(collections)}개:")
    for c in collections[:10]:
        print(f"   - {c.get('name')}  (id={c.get('id')})")

    # 2) 검색·열람 확인
    print(f"\n검색어: {query!r}")
    docs = Retriever(client, collections=[], max_docs=3).search(query)
    if not docs:
        print("  (검색 결과 없음 — 다른 검색어로 다시 시도해보세요)")
        return
    print(f"✓ 관련 문서 {len(docs)}개 확보:")
    for d in docs:
        preview = (d.text or "").strip().replace("\n", " ")[:80]
        print(f"   • {d.title}\n     {d.url}\n     본문 미리보기: {preview}…")


if __name__ == "__main__":
    main()
