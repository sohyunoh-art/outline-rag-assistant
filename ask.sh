#!/usr/bin/env bash
# 간편 실행기: venv 활성화 없이 어시스턴트에게 바로 질문한다.
#   ./ask.sh "질문 내용"
#   ./ask.sh -a onboarding "질문 내용"
#   ./ask.sh              (대화형 모드)
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -m cli.main "$@"
