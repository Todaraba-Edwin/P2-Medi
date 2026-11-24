#!/usr/bin/env bash
# 카카오 refresh token 재발급(운영자 전용, 약 2개월 만료 때). 서버 준비 알림(`kakao_notify.py`)이 쓰는 값이다.
#
# 하는 일: 루트 `.env`의 KAKAO_REST_API_KEY·KAKAO_CLIENT_SECRET을 읽어 인가 주소를 열고, 사용자가 붙여 넣은 주소(또는 code)를
# 토큰으로 교환해 새 refresh_token을 `.env`의 KAKAO_REFRESH_TOKEN 줄에 쓴다. 토큰·코드·키는 화면에 출력하지 않는다.
# 사용: bash backend/scripts/kakao_reissue_token.sh            (저장소 어디서든 실행 가능)
# 사전: 카카오 개발자 콘솔에서 카카오 로그인 활성화, Redirect URI 등록(기본 http://localhost:3000/kakao-callback), 동의항목 talk_message 설정.
# 환경: KAKAO_REDIRECT_URI로 Redirect URI를 바꿀 수 있다(셸 환경 전용, `.env`에 넣지 말 것: Settings가 extra 금지라 설정 로드가 실패한다).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"                       # 시험에서만 덮어쓴다
LOCAL_TOKEN_FILE="${KAKAO_LOCAL_TOKEN_FILE:-$REPO_ROOT/data/ops/kakao_refresh_token.local}"
REDIRECT_URI="${KAKAO_REDIRECT_URI:-http://localhost:3000/kakao-callback}"

[ -f "$ENV_FILE" ] || { echo "오류: .env를 찾을 수 없다($ENV_FILE)" >&2; exit 1; }

# .env에서 한 키의 값만 읽는다(source 하지 않음, 따옴표 제거). 값은 변수에만 담고 출력하지 않는다.
env_value() {
  local line
  line="$(grep -E "^[[:space:]]*$1[[:space:]]*=" "$ENV_FILE" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%$'\r'}"
  line="${line#\"}"; line="${line%\"}"; line="${line#\'}"; line="${line%\'}"
  printf '%s' "$line"
}

CLIENT_ID="$(env_value KAKAO_REST_API_KEY)"
CLIENT_SECRET="$(env_value KAKAO_CLIENT_SECRET)"
[ -n "$CLIENT_ID" ] || { echo "오류: .env에 KAKAO_REST_API_KEY가 없다" >&2; exit 1; }

AUTH_URL="https://kauth.kakao.com/oauth/authorize?response_type=code&client_id=${CLIENT_ID}&redirect_uri=${REDIRECT_URI}&scope=talk_message"

echo "1) 브라우저에서 카카오 로그인·동의를 끝내세요. (Redirect URI: $REDIRECT_URI)"
echo "   주소는 화면에 출력하지 않는다(REST API 키 포함). 브라우저가 열리지 않으면 Ctrl+C 후 수동으로 인가 주소를 여세요."
if command -v open >/dev/null 2>&1; then
  open "$AUTH_URL" || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$AUTH_URL" || true
fi
echo
echo "2) 동의 뒤 이동한 주소창의 전체 주소(…/kakao-callback?code=…) 또는 code 값만 붙여 넣고 Enter. 입력은 화면에 보이지 않는다."
read -r -s -p "주소 또는 code: " PASTED
echo

# 주소 전체가 오면 code 파라미터만 꺼낸다.
CODE="$(PASTED="$PASTED" python3 -I - <<'PY'
import os, re, urllib.parse
s = os.environ["PASTED"].strip()
m = re.search(r"[?&]code=([^&#\s]+)", s)
print(urllib.parse.unquote(m.group(1)) if m else s)
PY
)"
[ -n "$CODE" ] || { echo "오류: code를 읽지 못했다" >&2; exit 1; }

# 토큰 교환. 키·시크릿·코드는 프로세스 인자가 아니라 표준입력으로 넘긴다(ps에 보이지 않게).
RESPONSE="$(
  {
    printf 'grant_type=authorization_code&client_id=%s&redirect_uri=%s&code=%s' \
      "$(python3 -I -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$CLIENT_ID")" \
      "$(python3 -I -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$REDIRECT_URI")" \
      "$(python3 -I -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$CODE")"
    if [ -n "$CLIENT_SECRET" ]; then
      printf '&client_secret=%s' \
        "$(python3 -I -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$CLIENT_SECRET")"
    fi
  } | curl -sS --max-time 15 -X POST https://kauth.kakao.com/oauth/token \
        -H 'Content-Type: application/x-www-form-urlencoded;charset=utf-8' --data-binary @-
)"

# 응답은 파이썬 안에서만 해석한다. 성공이면 refresh_token을 .env와 로컬 토큰 파일에 쓰고, 값은 출력하지 않는다.
RESPONSE="$RESPONSE" ENV_FILE="$ENV_FILE" LOCAL_TOKEN_FILE="$LOCAL_TOKEN_FILE" python3 -I - <<'PY'
import json, os, sys, tempfile

raw = os.environ["RESPONSE"]
try:
    data = json.loads(raw)
except ValueError:
    print("오류: 응답을 해석하지 못했다(네트워크 또는 서버 오류)", file=sys.stderr)
    sys.exit(1)

token = data.get("refresh_token")
if not token:
    # 오류 코드와 설명만 알린다(토큰이 있을 수 없는 응답).
    err = data.get("error_code") or data.get("error") or "unknown"
    desc = data.get("error_description") or data.get("msg") or ""
    print(f"오류: 토큰 교환 실패 error={err} {desc}".strip(), file=sys.stderr)
    print("  - invalid_grant/KOE320: 코드가 만료·사용됨 또는 redirect_uri 불일치. 처음부터 다시 실행하세요.", file=sys.stderr)
    print("  - invalid_client: KAKAO_CLIENT_SECRET이 필요하거나 틀림.", file=sys.stderr)
    sys.exit(1)

env_file = os.environ["ENV_FILE"]
with open(env_file, encoding="utf-8") as f:
    lines = f.read().splitlines()

new_line = f"KAKAO_REFRESH_TOKEN={token}"
replaced = False
for i, line in enumerate(lines):
    if line.lstrip().startswith("KAKAO_REFRESH_TOKEN") and "=" in line:
        lines[i] = new_line
        replaced = True
if not replaced:
    lines.append(new_line)

# 원자적 교체(권한 유지). 중간에 실패해도 .env가 반쯤 써지지 않게 한다.
mode = os.stat(env_file).st_mode & 0o777
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(env_file) or ".", prefix=".env.tmp.")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, mode)
    os.replace(tmp, env_file)
except Exception:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise

# 서버는 로컬 토큰 파일이 있으면 .env보다 우선한다. 옛 값이 남지 않게 새 값으로 덮거나 지운다.
local = os.environ["LOCAL_TOKEN_FILE"]
if os.path.exists(local):
    os.makedirs(os.path.dirname(local), exist_ok=True)
    fd2 = os.open(local, os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0o600)
    with os.fdopen(fd2, "w", encoding="utf-8") as f:
        f.write(token)
    os.chmod(local, 0o600)
    print("로컬 토큰 파일도 새 값으로 갱신했다.")

print("완료: .env의 KAKAO_REFRESH_TOKEN을 갱신했다(" + ("교체" if replaced else "추가") + "). 값은 출력하지 않았다.")
PY

echo
echo "다음: 실제 전송 1건으로 확인하세요."
echo "  $REPO_ROOT/backend/.venv/bin/python $REPO_ROOT/backend/scripts/kakao_notify_probe.py --yes"
echo "백엔드를 재시작해야 새 토큰을 읽습니다."
