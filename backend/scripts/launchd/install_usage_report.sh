#!/usr/bin/env bash
# OpenAI 사용 비용 일일 보고 launchd 작업 설치/제거(운영자 전용). 기본은 계획만 출력하고 아무것도 쓰지 않는다.
# 사용: bash backend/scripts/launchd/install_usage_report.sh [--yes]              설치(--yes 없으면 계획만)
#       bash backend/scripts/launchd/install_usage_report.sh --uninstall [--yes]  제거
# 시험용 주입: LAUNCH_AGENTS_DIR(plist 폴더), LAUNCHCTL(launchctl 대체 명령). 기본은 ~/Library/LaunchAgents, launchctl.
set -euo pipefail

LABEL="com.mediagent.openai-usage-report"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
PYTHON="${USAGE_REPORT_PYTHON:-$REPO_ROOT/backend/.venv/bin/python}"
TEMPLATE="$HERE/$LABEL.plist.template"
AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
LAUNCHCTL="${LAUNCHCTL:-launchctl}"
PLIST="$AGENTS_DIR/$LABEL.plist"
DOMAIN="gui/$(id -u)"

YES=0; UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --yes) YES=1 ;;
    --uninstall) UNINSTALL=1 ;;
    *) echo "알 수 없는 인자: $arg" >&2; exit 2 ;;
  esac
done

if [ "$UNINSTALL" -eq 1 ]; then
  echo "계획: $LAUNCHCTL bootout $DOMAIN/$LABEL 후 $PLIST 삭제"
  [ "$YES" -eq 1 ] || { echo "(계획만 출력함. 실제로 제거하려면 --uninstall --yes)"; exit 0; }
  "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" 2>/dev/null || echo "참고: 로드된 작업이 없었다"
  rm -f "$PLIST"
  echo "제거 완료"
  exit 0
fi

echo "계획: $TEMPLATE 의 경로를 치환해 $PLIST 에 쓰고 $LAUNCHCTL bootstrap $DOMAIN $PLIST"
echo "  매일 12:00(Asia/Seoul), 파이썬=$PYTHON"
echo "  로그: $REPO_ROOT/logs/openai_usage_report.log (한 줄 요약), launchd 출력은 openai_usage_report.launchd.log"
[ -x "$PYTHON" ] || echo "경고: $PYTHON 이 없다(backend/.venv를 먼저 만들 것)"
[ "$YES" -eq 1 ] || { echo "(계획만 출력함. 실제로 설치하려면 --yes)"; exit 0; }

[ -x "$PYTHON" ] || { echo "오류: $PYTHON 이 없어 설치하지 않는다" >&2; exit 1; }
mkdir -p "$AGENTS_DIR" "$REPO_ROOT/logs"
sed -e "s|@PYTHON@|$PYTHON|g" -e "s|@REPO_ROOT@|$REPO_ROOT|g" "$TEMPLATE" > "$PLIST"
"$LAUNCHCTL" bootout "$DOMAIN/$LABEL" 2>/dev/null || true  # 재설치 때 기존 작업 교체
"$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST"
echo "설치 완료. 확인: launchctl print $DOMAIN/$LABEL"
