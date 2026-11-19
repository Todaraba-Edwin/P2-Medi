# 로컬 상시 서버 + 터널 배포 안내서

**DEPLOY GUIDE: 배포 안내서**

- 기준일: 2026-11-19 (공식 문서 열람일 동일)
- 결정 근거: BE-13-05 A(AWS 프리티어 사용 불가·추가 예산 없음 → 백엔드는 로컬 Mac 상시 실행 + 터널 HTTPS 공개, 프런트는 Vercel 무료, DB는 Supabase), BE-13-06 A(공개 엔드포인트 보호)
- 성격: **문서만 쓴 것이다. 설치·로그인·터널 생성은 실행하지 않았고**, 아래 명령은 모두 공식 문서나 로컬 man 페이지에서 읽은 것이다. 읽지 못했거나 문서끼리 어긋난 것은 "확인 필요"로 적었다.
- 비밀값: 변수 **이름만** 쓰고 값은 쓰지 않는다(CLAUDE.md 3장).

## Index

- [1. 구성도](#1-구성도)
- [2. 터널 비교](#2-터널-비교)
- [3. 단계별 설정 (권장안)](#3-단계별-설정-권장안)
- [4. 상시 실행](#4-상시-실행)
- [5. 보호 (BE-13-06 A 연결)](#5-보호-be-13-06-a-연결)
- [6. 운영 점검표](#6-운영-점검표)
- [7. 확인하지 못한 것과 위험](#7-확인하지-못한-것과-위험)
- [8. 출처](#8-출처)

## 1. 구성도

### (1) 요청 흐름

```
브라우저(사용자)
   │  https://<프런트 주소>/...            ← Vercel 무료 (Next.js)
   ▼
Vercel 프런트  ── rewrites: /api/:path*  →  ${MEDIAGENT_BACKEND_ORIGIN}/:path*
   │  (서버 전용 환경변수, frontend/next.config.ts:4·17)
   ▼
터널 공개 HTTPS 주소 (Cloudflare 또는 Tailscale)
   │  (터널 클라이언트가 로컬 Mac에서 바깥으로 연결을 먼저 맺음)
   ▼
로컬 Mac 127.0.0.1:8000  ← uvicorn (FastAPI, 메모리 약 1.1GB, 시작 뒤 준비 약 30초)
   │
   ├──▶ Supabase (Postgres + pgvector, 판정 테이블·근거 코퍼스·약품명 사전·로그인)
   └──▶ OpenAI (에이전트·답변·임베딩)
```

### (2) 읽을 수 있는 사실 (저장소 근거)

- 프런트는 `/api/:path*`를 `MEDIAGENT_BACKEND_ORIGIN`으로 넘긴다. 값이 없으면 rewrites가 비어 있다(`frontend/next.config.ts:4,16`).
- 브라우저는 백엔드와 같은 출처(프런트 도메인)로만 말하므로 **백엔드에 CORS 설정이 필요 없다**(백엔드 `app/` 안에서 `allow_origins`를 찾지 못했다. 이 경우만 해당하며, 터널 주소를 브라우저에서 직접 부르게 바꾸면 CORS가 필요해진다).
- `/health`는 서버가 뜨면 바로 200 `{"status":"ok"}`를 준다(`backend/app/main.py:54`). 자원 준비는 그 뒤 백그라운드에서 돈다(`main.py:10`).
- `/chat`은 `StreamingResponse` 기반 NDJSON 응답이다(`backend/app/api/chat.py:50`). 터널과 Vercel 프록시를 거쳐도 스트림이 끊기지 않는지는 **확인 필요**(7장).
- 백엔드는 현재 폴더의 `.env`와 저장소 루트 `.env`를 읽는다(`backend/app/config.py:18-24,81`). 그래서 launchd 등에서 어느 폴더로 띄워도 루트 `.env`를 찾는다.

## 2. 터널 비교

### (1) 비교 표

| 항목 | Cloudflare quick tunnel | Cloudflare named tunnel | Tailscale Funnel |
|---|---|---|---|
| 계정 | 필요 없음 | Cloudflare 계정 필요 | Tailscale 계정(tailnet) 필요 |
| 도메인 | 필요 없음 | **필요**: Cloudflare에 추가한 도메인(공개 호스트명용). 네임서버를 Cloudflare로 바꾸는 단계가 준비 항목에 있다 | 필요 없음. tailnet 도메인 `*.ts.net`의 이름만 쓸 수 있다 |
| 주소 | 무작위 `trycloudflare.com`, **만들 때마다 바뀜**, 프로세스를 끄면 중단 | 내 도메인의 호스트명으로 **고정** | `https://<기기>.<tailnet>.ts.net` 형태. 재시작 뒤에도 같은 주소인지는 **페이지에 없음(확인 필요)** |
| 무료 조건 | 계정·도메인 없이 쓴다고 명시. 단 "가동 보장 없음" | 문서에 요금·무료 조건 **없음(확인 필요)**. 도메인 구입 비용은 별도 | 문서에 "모든 플랜에서 사용 가능", 현재 **beta**. Personal 요금제는 $0, 최대 6명, 기기 무제한, **비상업 용도 한정**(pricing 페이지). 플랜별 Funnel 체크 표시는 텍스트로 확정 못 함 |
| 설치 | `brew install cloudflared` 후 `cloudflared tunnel --url http://localhost:8000` | `brew install cloudflared` + login·create·config·DNS route·run (3장) | Tailscale 설치·로그인, `tailscale funnel` 명령 |
| 포트·제한 | 터널당 동시 요청 200개(초과 429), **SSE 미지원**, 테스트·개발용이라고 문서가 안내 | 위 한도·SSE 언급 없음(확인 필요) | 공개 포트는 **443·8443·10000**만. 대역폭 제한이 있고 바꿀 수 없다(수치 없음). TLS 전용 |
| macOS 주의 | 없음 | 없음 | 변형별 지원이 문서마다 다르다. docs 페이지는 App Store·Standalone에서도 **포트 공유는 가능**, macos-variants 표는 Funnel `no`. **확인 필요**(7장) |
| 상시 실행 | 프로세스를 직접 유지해야 함 | `cloudflared service install`(launch agent/daemon) | `--bg`로 켜면 재부팅·재시작 뒤 자동 재개 |

### (2) 권장: Cloudflare named tunnel (도메인이 있을 때) / 없으면 Tailscale Funnel

- **비용 0·고정 주소·설정 단순**을 기준으로 한다.
- quick tunnel은 주소가 바뀌어 Vercel 환경변수를 매번 고쳐야 하고(변경은 새 배포에만 반영된다, 3장), 가동 보장이 없다고 문서가 말한다. 데모에는 맞지 않아 **개발 중 임시 확인용**으로만 쓴다.
- **도메인을 이미 갖고 있거나 사용자가 새로 사지 않아도 된다면** named tunnel을 권한다. 고정 호스트명, `cloudflared service install`로 상시 실행이 문서에 있고, 4장의 보호(Access)와 이어 붙이기 쉽다. 다만 **도메인 비용이 0이 아니다**.
- **도메인이 없고 추가 비용을 쓰지 않으려면 Tailscale Funnel**을 권한다. 도메인 없이 `*.ts.net` 이름이 나오고, 명령 한 줄에 `--bg`로 상시 유지가 된다. 대신 beta이고 대역폭 제한·macOS 변형 불일치가 있어 **3장에서 쓰기 전에 한 번 실제로 확인**해야 한다.
- **이 문서의 3장은 도메인 보유 여부를 모르므로 두 경로를 모두 적는다.** 가정: 비용 0 원칙(BE-13-05 A)에 따라 **도메인이 없으면 Tailscale Funnel이 기본**이다. 사용자 확정 필요.

## 3. 단계별 설정 (권장안)

모든 단계는 아직 실행하지 않았다. 표시한 명령 출처는 8장에 있다.

### (1) 공통: 백엔드를 먼저 띄워 본다

```
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8000
```

- 기본 바인딩은 `127.0.0.1`이다(0.0.0.0로 열지 않는다. 터널이 로컬로 들어오므로 필요 없다).
- 로그에 `warmup … done`이 나오면 준비가 끝난 것이다(약 30초, BE-17-01 A).
- 확인: `curl http://127.0.0.1:8000/health` → `{"status":"ok"}`.

### (2) 경로 A: Cloudflare named tunnel (도메인 보유 시)

| 순서 | 명령·행동 | 근거 |
|---|---|---|
| 1 설치 | `brew install cloudflared` | create-local-tunnel 문서 |
| 2 사전 | 도메인을 Cloudflare에 추가하고 네임서버를 Cloudflare로 변경 | 같은 문서 준비 단계 |
| 3 로그인 | `cloudflared tunnel login` (브라우저에서 호스트명 선택, `cert.pem` 생성) | 같은 문서 |
| 4 터널 생성 | `cloudflared tunnel create <이름>` (UUID·자격 증명 JSON 생성), 확인은 `cloudflared tunnel list` | 같은 문서 |
| 5 설정 | `~/.cloudflared/config.yml`에 `tunnel: <UUID>`, `credentials-file: <JSON 경로>`와 `ingress`(호스트명 → `http://localhost:8000`, 마지막에 `service: http_status:404` catch-all 필수) | configuration-file 문서 |
| 6 DNS | `cloudflared tunnel route dns <이름 또는 UUID> <호스트명>` | create-local-tunnel 문서 |
| 7 실행 | `cloudflared tunnel run <이름 또는 UUID>` | 같은 문서 |
| 8 확인 | `cloudflared tunnel info <이름 또는 UUID>`, 설정 점검 `cloudflared tunnel ingress validate` | 같은 문서 |

config.yml 예(문서의 ingress 형식을 따랐다. UUID·호스트명은 자리표시):

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /Users/<사용자>/.cloudflared/<TUNNEL_UUID>.json
ingress:
  - hostname: <API 호스트명>
    service: http://localhost:8000
  - service: http_status:404
```

상시 실행은 4장 (3)에서 다룬다.

### (3) 경로 B: Tailscale Funnel (도메인 없음)

| 순서 | 명령·행동 | 근거 |
|---|---|---|
| 1 설치·로그인 | Tailscale 설치 후 로그인(tailnet 생성). macOS 변형은 7장 확인 | macos-variants 문서 |
| 2 사전 | 관리 콘솔에서 MagicDNS, HTTPS 인증서 활성화. `tailscale funnel` CLI가 인증서 생성과 정책 파일의 funnel 속성(`nodeAttrs`)을 자동 처리한다고 문서에 있다 | funnel 문서 |
| 3 켜기 | `tailscale funnel --bg 8000` (`--bg`: 백그라운드 유지, 기본 `--https=443`) | CLI 문서 |
| 4 상태 | `tailscale funnel status` (`--json` 가능) | CLI 문서 |
| 5 끄기 | `tailscale funnel reset`(전체 초기화) 또는 켠 명령에 `off`를 붙임 | CLI 문서 |

- 문서 예시는 `tailscale funnel 3000`, `tailscale funnel localhost:3000`이다. 포트 8000 예시는 문서에 **없고**, 같은 형식을 쓴 것이다. 리버스 프록시 대상은 `http://127.0.0.1`만 지원한다고 적혀 있다.
- 문서 본문의 `-bg`와 플래그 목록의 `--bg` 표기가 달랐다. 플래그 목록 기준(`--bg`)을 따랐다. 실제 도움말 `tailscale funnel --help`로 확인한다(확인 필요).
- 공개 DNS 반영에 최대 10분 걸릴 수 있다고 문서에 있다.

### (4) 주소 확인과 Vercel 환경변수

1. 경로 A는 지정한 `https://<API 호스트명>`, 경로 B는 `tailscale funnel status`에 나오는 `https://<기기>.<tailnet>.ts.net`이 터널 주소다.
2. 터널을 통해 확인: `curl https://<터널 주소>/health` → `{"status":"ok"}`.
3. Vercel 프로젝트에 환경변수 **`MEDIAGENT_BACKEND_ORIGIN`**을 추가한다(값은 이 문서에 적지 않는다). 끝의 `/`는 코드가 제거한다(`next.config.ts:4`).
   - 환경별로 Production·Preview·Development를 고른다. 데모는 Production 하나면 된다.
   - **변경은 이전 배포에 적용되지 않고 새 배포에만 적용된다.** 값을 바꾸면 **Redeploy**한다(Vercel 문서). rewrites는 서버 쪽 설정이라 같은 규칙이 적용된다고 보이나, 빌드 시점에 굳는지는 **확인 필요**.
   - `NEXT_PUBLIC_*`에는 터널 주소·키를 넣지 않는다(CLAUDE.md 3장, 서버 전용 규칙).
   - 대시보드 메뉴 클릭 순서는 읽은 페이지에 없었다(Managing environment variables 문서에 있다고 안내만 됨, 확인 필요).
4. 동작 확인: `https://<프런트 주소>/api/health`가 `{"status":"ok"}`를 주는지 본다(`/api/:path*` → `/:path*`이므로 `/api/health` → 백엔드 `/health`).

## 4. 상시 실행

### (1) 잠자기 방지

**`caffeinate`** (로컬 `man caffeinate`, Darwin 2012-11-09판에서 읽음):

| 옵션 | 뜻 |
|---|---|
| `-i` | 시스템이 유휴 상태로 잠들지 않게 함 |
| `-d` | 디스플레이가 잠들지 않게 함 |
| `-m` | 디스크가 유휴 잠자기 하지 않게 함 |
| `-s` | 시스템이 잠들지 않게 함. **AC 전원일 때만 유효** |
| `-u` | 사용자 활동 선언. 시간 지정이 없으면 5초 |
| `-t <초>` | assertion 유지 시간 |
| `-w <pid>` | 지정 프로세스가 끝날 때까지 유지 |

- 서버 프로세스와 같이 묶기: `caffeinate -i <명령>`은 그 명령이 도는 동안 유휴 잠자기를 막는다(man 예시 `caffeinate -i make`).
- `-s`는 **전원 어댑터 연결 시에만** 효과가 있으므로 노트북을 배터리로 돌리면 의미가 없다.

**시스템 설정 경로** (Apple 지원 문서, 영문 UI 기준):

- 노트북: 시스템 설정 > Battery > Options > "Prevent automatic sleeping on power adapter when the display is off."
- 데스크톱: 시스템 설정 > Energy > "Prevent automatic sleeping when the display is off."
- 이 페이지는 "일부 옵션은 Mac에 따라 없을 수 있다"고 한다. **한국어 UI 라벨은 확인하지 못했다(확인 필요).**
- **덮개를 닫았을 때의 동작은 이 문서에 없다(확인 필요).** 덮개를 닫고 돌릴 계획이면 별도로 검증한다(7장).

### (2) 서버 자동 재시작: launchd `LaunchAgent`

launchd 기초는 `man launchd.plist`와 `man launchctl`(로컬)에서 읽었다.

- 사용자 에이전트 plist 위치: `~/Library/LaunchAgents/`(Apple 문서).
- `KeepAlive`: `true`면 job을 계속 살려 둔다(기본 false, man).
- `RunAtLoad`: load 시 한 번 시작. man은 "피하라"고 하지만 `KeepAlive`가 true이면 이 키 없이도 시작된다(man은 일부 하위 조건이 `RunAtLoad`를 함의한다고만 명시했고, `KeepAlive: true` 단독의 시작 시점은 **확인 필요**). 안전하게 같이 쓴다.
- `StandardOutPath`·`StandardErrorPath`: 로그 파일 지정. 없는 파일은 만들어진다(man).
- `WorkingDirectory`, `EnvironmentVariables`: man에 있는 키. **비밀값은 `EnvironmentVariables`에 넣지 않는다.**
- `ThrottleInterval`: 기본으로 job은 10초에 한 번보다 자주 시작되지 않는다(man).
- launchd job은 스스로 daemon화(fork 후 부모 종료)하면 안 된다(man). uvicorn을 `--reload` 없이 **전경 프로세스**로 실행하면 이 조건에 맞는다.
- 명령(man launchctl): `launchctl bootstrap gui/<uid> <plist 경로>`로 등록하고, `launchctl bootout gui/<uid> <plist 경로>`로 제거하고, `launchctl kickstart -k gui/<uid>/<Label>`로 즉시 (재)시작한다. `<uid>`는 `id -u` 값이다.

plist 예시 (경로·Label은 자리표시. **비밀값 없음**, 루트 `.env`는 앱이 직접 읽는다 → `backend/app/config.py:18-24`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.mediagent.backend</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-i</string>
    <string>/Users/<사용자>/develop/P2-Medi/backend/.venv/bin/python</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>app.main:app</string>
    <string>--app-dir</string>
    <string>/Users/<사용자>/develop/P2-Medi/backend</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8000</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/<사용자>/develop/P2-Medi</string>

  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/Users/<사용자>/Library/Logs/mediagent/backend.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/<사용자>/Library/Logs/mediagent/backend.err.log</string>
</dict>
</plist>
```

- `caffeinate -i <명령>`으로 서버를 감싸면 서버가 도는 동안 유휴 잠자기가 막힌다(`caffeinate`의 `<utility>` 사용법, man).
- 로그 폴더 `~/Library/Logs/mediagent/`는 **미리 만들어 둔다**(자동 생성 여부 확인 필요. man은 파일이 없으면 만든다고만 했고 상위 폴더는 언급하지 않았다).
- 서버 로그에 값·접속 문자열이 남지 않는다는 보증은 BE-15의 마스킹 가드(`backend/app/security`)가 한다. launchd 로그 파일은 그 가드를 우회하지 않지만 **로그 폴더 권한은 본인만 읽게** 둔다.

### (3) 터널 상시 실행

- Cloudflare named tunnel: `cloudflared service install`은 **로그인 때 실행되는 launch agent**로 설치되고 설정은 `~/.cloudflared/`를 쓴다. `sudo cloudflared service install`은 **부팅 때 실행되는 launch daemon**이며 설정은 `/etc/cloudflared`를 쓰는데, 설정을 거기로 옮기는 방법은 읽은 문서에 없었다(확인 필요). 수동 시작은 `sudo launchctl start com.cloudflare.cloudflared`, 로그는 `/Library/Logs/com.cloudflare.cloudflared.{out,err}.log`다. 제거 방법은 읽은 페이지에 없었다.
- Tailscale Funnel: `tailscale funnel --bg …`로 켜면 재부팅이나 `tailscale down/up` 뒤에도 자동으로 재개된다(CLI 문서). `--bg` 없이 켜면 수동으로 다시 켜야 한다.

### (4) 재부팅 뒤 자동 시작

- 사용자 LaunchAgent는 **그 사용자가 GUI에 로그인해야** 올라온다(`gui/<uid>` 도메인은 GUI 로그인 때 만들어진다, man launchctl). 재부팅 뒤 **자동 로그인**을 켜 두지 않으면 서버가 안 뜬다. 자동 로그인과 디스크 암호화(FileVault) 사이의 관계는 읽지 못했다(확인 필요).
- 부팅만으로 올리려면 LaunchDaemon(`/Library/LaunchDaemons`, root)이 필요하다. 이 안내서는 비밀값(루트 `.env`)을 사용자 폴더에 두므로 **LaunchAgent + 자동 로그인**을 기본으로 한다. 이 선택은 가정이다.

## 5. 보호 (BE-13-06 A 연결)

BE-13-06 A는 요청 횟수 제한·하루 LLM 비용 상한·데모 접근 코드로 정했고, **값은 개발 완료 뒤 1회 요청 평균 단가를 잰 다음에 정한다.** 이 문서는 값을 정하지 않는다.

### (1) 터널·네트워크 쪽에서 할 수 있는 것

| 수단 | 할 수 있는 것 | 확인한 범위 |
|---|---|---|
| Cloudflare Access(named tunnel로 공개한 호스트에 적용) | 이메일 OTP 등 로그인 방법, Allow·Block 정책 | 정책 구성(Allow/Block/Bypass/Service Auth)과 One-time PIN 설정은 문서에서 읽음. **무료 플랜의 사용자 수 한도는 4개 페이지에서 찾지 못했다(확인 필요)**. Bypass는 보안 통제와 로그가 없다고 문서가 경고 |
| Cloudflare quick tunnel `--allowed-mail` | 허용 이메일만 접근. 도메인 전체 허용(`'*@example.com'`)도 가능 | **대화형 브라우저 세션이 필요**하다고 문서에 있어 프런트(Vercel 서버)가 대신 부르는 경로에는 맞지 않을 수 있다(확인 필요) |
| Tailscale Funnel | 공개 인터넷 노출이 목적이라 접근 제한 수단이 아님(문서에서 접근 제어 기능은 못 읽었다). tailnet 내부 공유는 Serve가 따로 있다 | 확인 필요 |

- 중요: **프런트가 서버에서 백엔드를 부르는 구조**라 터널 주소는 사람이 직접 열 필요가 없다. 반대로 말하면 터널 주소가 공개되어 있으면 누구나 직접 `/chat`을 부를 수 있다. 터널 쪽 로그인 보호를 걸면 Vercel 서버의 호출도 막히므로 Service Auth 같은 별도 자격이 필요할 수 있다(세부 확인 필요).

### (2) 앱 쪽에서 구현할 것 (BE-13-06 A)

- 요청 횟수 제한(IP 또는 계정당), 하루 LLM 비용 상한(기존 비용 원장 `backend/app/llm/ledger.py`와 연결할 수 있는지 구현 때 확인), 데모 접근 코드(프런트가 헤더로 전달하고 백엔드가 검사).
- **값(분당 횟수, 하루 USD 상한)은 1회 요청 평균 단가를 잰 뒤에 정한다.** 지금 값을 적으면 근거가 없다.
- 이 장의 어떤 값도 평가 측정과 섞지 않는다.

## 6. 운영 점검표

### (1) 켜기·끄기

| 구분 | 순서 |
|---|---|
| 켜기 | ① 전원 어댑터 연결·잠자기 방지 확인 → ② 백엔드 시작(LaunchAgent면 자동) → ③ 로그에 `warmup … done` 확인 → ④ 터널 시작·상태 확인 → ⑤ `curl <터널 주소>/health` → ⑥ `<프런트 주소>/api/health` → ⑦ 로그인·채팅 1회 |
| 끄기 | ① 터널 끄기(Funnel: `tailscale funnel reset`, Cloudflare: 서비스 중지) → ② 백엔드 중지(`launchctl bootout gui/<uid> <plist>`) |
| 데모 직후 | 터널을 끈다. 공개 주소를 계속 열어 두지 않는다 |

### (2) 네트워크가 끊겼을 때

- 터널 클라이언트는 로컬에서 바깥으로 연결하므로 끊기면 프런트 호출이 실패한다. 복구는 클라이언트의 재연결에 맡기고 `/health`로 확인한다. 자동 재연결 시간은 **문서에서 읽지 못했다(확인 필요)**.
- 프런트는 백엔드 오류 때 에러 화면을 보여야 한다. 이 동작은 FE 티켓 범위이며 이 문서에서 확인하지 않았다.
- 응급 안내(119)처럼 코드가 강제하는 고정 문구가 백엔드 없이도 보이는지는 별도 확인 대상이다(확인 필요).

### (3) 비용 감시

- OpenAI 대시보드의 사용량을 데모 전·후와 매일 본다. 서비스가 쓰는 모델은 CLAUDE.md 3장 기준 OpenAI 계열이다.
- 기존 비용 원장(`backend/app/llm/ledger.py`)과 BE-13-06 A의 하루 상한은 개발 완료 뒤 단가를 재서 연결한다.
- Supabase Pro($25/월, BE-05-03 D)는 이미 정해진 고정비다. 터널(Cloudflare·Tailscale)과 Vercel 무료 플랜은 이 문서가 읽은 범위에서 추가 비용이 없다. 도메인을 새로 사면 비용이 든다.

### (4) 데모 전 확인

- 전원 연결, 디스플레이 잠금·잠자기 방지, OS 업데이트 자동 재시작 시각이 데모와 겹치지 않는지.
- 데모 1시간 전에 켜서 `warmup … done`과 채팅 1회를 확인한다(첫 요청이 느린 것을 피하려는 목적).
- Vercel 환경변수 `MEDIAGENT_BACKEND_ORIGIN`이 **현재 터널 주소**인지(quick tunnel이면 매번 바뀐다) 확인하고, 바뀌었으면 Redeploy한다.
- OpenAI·Supabase 상태, 비밀값이 로그·화면에 없는지 훑는다.

### (5) 녹화 영상 대비

- 데모 중 네트워크·서버 장애에 대비해 **정상 흐름을 미리 녹화**해 둔다(발표 자료 위치와 규칙은 CLAUDE.md 6장 `P2-doc/report/presentation/`, 로컬 전용).
- 녹화에는 개인정보·키·접속 문자열이 보이지 않게 한다(화면의 `.env`, 터미널 환경변수 출력 주의).

## 7. 확인하지 못한 것과 위험

### (1) 확인 필요 (이번에 읽지 못했거나 문서끼리 어긋난 것)

1. **NDJSON 스트리밍이 터널과 Vercel 프록시를 지나도 유지되는지.** quick tunnel은 SSE 미지원이라고 하고, 채팅은 NDJSON 스트림이다. 같은 제한이 걸리는지, Vercel rewrites의 응답 시간 제한이 있는지는 읽은 문서에 없다. **가장 먼저 실제로 시험할 항목**이다.
2. Cloudflare Tunnel(named)의 무료 조건과 Access 무료 플랜의 사용자 수 한도.
3. Tailscale Funnel: 주소 고정 여부, 대역폭 제한 수치, Personal 플랜 포함 여부(pricing 표 확인 불가), **macOS 변형별 지원 불일치**(docs는 포트 공유 가능, macos-variants 표는 Funnel `no`).
4. Tailscale Personal 플랜은 **비상업 용도 한정**이다. 이 프로젝트가 포트폴리오 데모라 해당될 가능성이 크지만 판단은 사용자 몫이다.
5. launchd: `KeepAlive: true` 단독 시작 시점, 로그 폴더 자동 생성 여부, 자동 로그인과 FileVault의 관계, 덮개 닫힘 동작.
6. 한국어 UI 라벨(시스템 설정 항목 이름), Vercel 대시보드 메뉴 경로.
7. Cloudflare `/etc/cloudflared` 설정 이동·서비스 제거 방법.

### (2) 위험

| 위험 | 영향 | 완화 |
|---|---|---|
| 집 네트워크 끊김·공유기 재부팅 | 데모 중 서비스 중단 | 데모 전 점검, 녹화 영상, 휴대전화 핫스팟 예비 |
| 노트북 덮개 닫힘·잠자기 | 서버 중단 | 전원 연결, 4장 설정, **덮개 닫힘은 실제 시험으로 확인** |
| OS 업데이트의 자동 재시작 | 서버·터널 중단 | 데모 기간 자동 업데이트 일정 조정, 4장 (4) 자동 로그인 |
| 터널 주소 변경(quick tunnel) | 프런트가 옛 주소를 계속 호출 | named tunnel 또는 Funnel 사용, 변경 시 Redeploy |
| 공개 엔드포인트 남용 | OpenAI 비용 폭증 | 5장 앱 쪽 보호. **값은 단가 측정 뒤** 정하며 그 전에는 데모 때만 터널을 연다 |
| 서버 메모리 약 1.1GB | 다른 작업과 겹치면 느려짐 | 데모 중 불필요한 앱 종료 |
| 로컬 `.env`와 로그 | 노트북 분실·공유 시 비밀 노출 | 계정 잠금, FileVault 확인, 로그 폴더 권한 |

## 8. 출처

읽은 날짜는 모두 **2026-11-19**이다. "읽음"은 페이지를 읽었다는 뜻이고, 안내서의 해석은 이 문서의 책임이다.

| 대상 | URL | 쓴 곳 |
|---|---|---|
| Cloudflare Quick Tunnels | https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/ (정식 URL은 `/tunnel/get-started/quick-tunnels/`로 표기됨) | 2장·5장 |
| Cloudflare Tunnel 시작(대시보드·토큰 방식) | https://developers.cloudflare.com/tunnel/setup/ | 2장 |
| Cloudflare 로컬 관리 터널 만들기 | https://developers.cloudflare.com/tunnel/advanced/local-management/create-local-tunnel/ | 3장 (2) |
| Cloudflare 설정 파일(ingress) | https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/ | 3장 (2) |
| Cloudflare macOS 서비스 | https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/as-a-service/macos/ | 4장 (3) |
| Cloudflare Access 정책 | https://developers.cloudflare.com/cloudflare-one/policies/access/ | 5장 |
| Cloudflare Zero Trust 요금·무료 플랜 | https://www.cloudflare.com/plans/zero-trust-services/, https://www.cloudflare.com/plans/free/ (사용자 수 한도 못 찾음) | 5장 |
| Tailscale Funnel | https://tailscale.com/kb/1223/funnel (페이지 표기 Last validated Jan 20, 2026) | 2장·3장 |
| Tailscale CLI funnel | https://tailscale.com/docs/reference/tailscale-cli/funnel (Last validated Jan 26, 2026), https://tailscale.com/kb/1311/tailscale-funnel | 3장 (3) |
| Tailscale macOS 변형 | https://tailscale.com/kb/1065/macos-variants (Last validated Jan 5, 2026) | 2장·7장 |
| Tailscale 요금 | https://tailscale.com/pricing | 2장 |
| Vercel 환경변수 | https://vercel.com/docs/environment-variables (last_updated 2026-09-17) | 3장 (4) |
| Apple 잠자기·깨우기 설정 | https://support.apple.com/guide/mac-help/set-sleep-and-wake-settings-for-your-mac-mchle41a6ccd/mac | 4장 (1) |
| Apple launchd 작업 만들기(아카이브, 2016-09-13) | https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html | 4장 (2) |
| Apple 터미널 launchd 안내 | https://support.apple.com/guide/terminal/script-management-with-launchd-apdc6c1077b-5d5d-4d35-9c19-60f2397b2369/mac | 4장 (2) |
| 로컬 man 페이지 | `man caffeinate`, `man launchctl`, `man launchd.plist` (이 Mac의 macOS에서 읽음) | 4장 |
| 저장소 근거 | `frontend/next.config.ts`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/api/chat.py` | 1장 |

- 읽지 못한 URL: Apple `man8/caffeinate.8.html`(404), Cloudflare `.../get-started/create-local-tunnel/`(404, 위 `/tunnel/advanced/local-management/…`로 대체). `ss64` 등 비공식 사이트는 쓰지 않았다.
- 웹 페이지 조회는 요약 에이전트를 거쳤으므로 인용은 짧은 요지이며, 명령·키 이름은 확정 전에 `--help`·`man`으로 한 번 더 대조한다.
