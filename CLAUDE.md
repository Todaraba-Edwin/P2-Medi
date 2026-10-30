# CLAUDE.md: MediAgent(P2-Medi) 작업 지침

MediAgent는 공공 보건·의약품 데이터 기반 Agentic RAG 에이전트 프로젝트다. 이 파일은 저장소(P2-Medi)에서 작업할 때 따라야 할 맥락과 규칙이다. 문서(RFP, PRD, 아키텍처 문서, 평가 리포트, 발표 자료)는 `P2-doc/`에 둔다. 요구사항 원본은 `P2-doc/PJ2-RFP.md`이고, 일정과 티켓은 저장소 루트의 `schedule.md`와 `tickets/`에 둔다.

## 1. 프로젝트 한 줄 정의

사실은 공공 API·문서에서 가져오고, LLM은 설명과 종합만 맡는 근거 기반 질의응답 에이전트다. RAG와 Agent를 잘 설계하고, 다루고, 구현하는 과정이 목적이며, 약품 정보 조회·병용·연령·임부 금기 확인·국가건강검진 안내·보건사업 자격 안내가 이를 다루기 위한 도메인이다.

방향성과 단계는 RFP(`P2-doc/PJ2-RFP.md`)의 3주 일정과 주차별 완료 기준을 따른다. 주차 완료 기준에 미달하면 다음 주 범위를 줄인다.

진단·처방·복용량 결정을 하는 서비스가 아니다. 공공데이터 기반 정보 제공이며, 응답의 결과는 의료적 판단을 대신하지 않는다.

## 2. 서브에이전트

| 에이전트 | 정의 파일 | 맡는 일 |
|---|---|---|
| `schedule-writer` | [`.claude/agents/schedule-writer.md`](.claude/agents/schedule-writer.md) | `schedule.md`와 `tickets/` 작성·갱신, 진행 현황과 Top 5 관리. 이 두 곳 밖의 파일은 읽기만 한다 |
| `tickets-writer` | [`.claude/agents/tickets-writer.md`](.claude/agents/tickets-writer.md) | 티켓 문서의 본문(설명·해설) 작성. `#` 제목과 `##` 소제목을 분리하고 상단에 Index(목차 링크)를 둔다. 상태·일정은 다루지 않는다 |
| `documents-writer` | [`.claude/agents/documents-writer.md`](.claude/agents/documents-writer.md) | PDF·DOCX 등 문서 파일을 읽고 마크다운으로 정리해 `P2-doc/`에 기록. `#` 제목, `## Index`, `## 1.` 번호 소제목, `### (1)` 세부 항목 규칙. `.env`는 열지 않는다 |
| `git-actor` | [`.claude/agents/git-actor.md`](.claude/agents/git-actor.md) | git 작업 전담: 커밋, 브랜치, 병합, 태그, `.gitignore` 관리. 파일 내용은 고치지 않는다 |

역할은 이렇게 나눈다. 일정 표, 티켓 파일 생성, 상태·완료일은 `schedule-writer`가, 티켓 본문의 설명 작성은 `tickets-writer`가, git과 관련된 모든 작업은 `git-actor`가 전담한다. 키워드(SCH, RFP, PRD, AG, BE, FE), 문서 형식, 브랜치 정책(git-flow), 보고 형식은 각 정의 파일에서 확인한다.

커밋 메시지는 `[keyword] 라벨-번호 커밋내용` 형식이며 내용은 한글로 쓴다. 예: `[docs] RFP-01 FR 의미 설명 추가`. 티켓이 없는 저장소 공통 작업은 `[chore] 커밋내용`으로 쓴다. push는 사용자가 요청할 때만 한다.

### herdr 환경(`HERDR_ENV=1`)에서의 실행 규칙

- 서브에이전트는 **별도 pane**에서 작업한다. 현재 tab에 pane을 나누어 열고, 메인 pane의 포커스와 작업 디렉터리는 그대로 둔다.
- **pane 이름을 붙인다.** 새 pane을 열면 시작 전에 `herdr pane rename <pane> <에이전트 이름>`으로 서브에이전트와 같은 이름을 붙인다(예: `schedule-writer`). 메인 pane의 이름은 `P2-Medi-Main`이다. 이미 열려 있는데 이름이 없는 pane도 같은 방식으로 이름을 붙인다.
- **대상 pane은 ID로 명시한다.** `$HERDR_PANE_ID`는 다른 workspace의 pane으로 풀릴 수 있으므로 이름 변경·종료 같은 명령에 그대로 쓰지 않는다. `herdr pane list`로 workspace(`w3`)와 `cwd`가 P2-Medi인지 확인한 뒤 ID를 지정한다.
- 작업이 **완료되면 그 pane을 종료**한다. 호출마다 pane을 새로 열고 끝나면 닫는다.
- 종료하기 전에 **반영 내용을 Main pane에 보고**한다. 보고에는 변경 파일 수, SCH별 현황, Top 5, 가정·확인 필요 사항을 담는다. 보고만 믿지 않고 변경된 파일을 직접 확인한 뒤 닫는다.
- 다음 경우에는 pane을 닫지 않는다. 에이전트가 `working` 또는 `blocked` 상태이거나 timeout으로 끝났을 때, 사용자의 답이나 승인이 필요할 때, pane 입력창에 사용자가 적은 내용이 남아 있을 때다. 승인 창이 떠 있으면 입력을 임의로 보내지 않고 사용자에게 알린다.
- 열기, 시작, 요청, 보고 읽기, 종료의 구체적인 명령은 정의 파일의 "메인 세션 호출·종료 절차"를 따른다.

## 3. 비밀 정보와 환경변수

- API 주소와 인증키는 저장소 루트의 `.env`에 보관한다. `.env`와 `.env.*`는 `.gitignore` 대상이며 커밋하지 않는다.
- **서브에이전트는 `.env`를 열지 않는다.** 시작 옵션 `--disallowedTools 'Read(./.env)' 'Read(./.env.*)'`로 읽기를 막는다. 문서와 티켓, 커밋 메시지에는 **변수 이름만** 쓰고 값은 쓰지 않는다.
- 현재 사용자가 알려준 변수는 아래와 같다. 이 목록은 `.env`를 직접 읽지 않고 사용자가 알려준 내용에 근거한다. 변수가 늘면 사용자가 알려 주는 대로 이름만 추가한다.

| 대상 | 변수 이름 | 용도 |
|---|---|---|
| e약은요 서비스 | `DRDEASYDRUG_END_POINT`, `DRDEASYDRUG_API_KEY` | 서비스 호출 주소, 인증키 |
| 식약처 [DUR 품목정보 OpenAPI](https://www.data.go.kr/data/15059486/openapi.do) | `DURPrdlstInfoService03_END_POINT`, `DURPrdlstInfoService03_API_KEY` | 서비스 호출 주소, 인증키 |
| 식약처 [DUR 성분정보 OpenAPI](https://www.data.go.kr/data/15056780/openapi.do) (성분 단위 버전) | `DURIrdntInfoService03_END_POINT`, `DURIrdntInfoService03_API_KEY` | 서비스 호출 주소, 인증키 |
- 코드에서는 환경변수로만 읽고, 값을 코드나 로그, 응답에 남기지 않는다.

## 4. 데이터 파일

- 내려받은 원본 데이터는 `data/`에 둔다. `data/`는 `.gitignore` 대상이며 커밋하지 않는다. 용량이 크고(병용금기 JSON 약 540MB), 라이선스가 "공공저작물 제2유형(출처표시, 상업적 이용금지)"이라 저장소로 재배포하지 않는다.
- 현재 파일은 한국의약품안전관리원의 [임부금기약물](https://www.data.go.kr/data/15089735/fileData.do) CSV, [병용금기약물(AI 학습용)](https://www.data.go.kr/data/15161282/fileData.do) JSON, 임부금기 항목정의서 xlsx다. 두 데이터의 최신 고시일이 2026-07-21이라 이날을 기준일로 본다.
- 읽을 때 주의한다. 임부금기 CSV는 **CP949** 인코딩이고, 병용금기 JSON은 크므로 한 번에 읽지 말고 스트리밍으로 처리한다. 임부금기의 `금기등급` 1·2는 고시 「의약품 병용금기 성분 등의 지정에 관한 규정」 제3조 제3호의 정의를 따른다. `M`은 고시에 없고 건강보험심사평가원 「기능과 역할」(2021~2026년판 여섯 판)만 "상병에 따른 1등급 또는 2등급"이라고 설명한다. 모델은 이 설명만 인용하고 등급은 상세정보 문구를 그대로 전달하며, 처방·조제 사유 코드의 M(유·조산 치료)과 혼동하지 않는다(RFP-17의 "M 처리 규칙").
- 고시 전문 PDF는 `P2-doc/`에 두고 커밋한다. 정부 고시는 일반적으로 저작권 보호 대상이 아니라고 보지만 법률 검토는 거치지 않았다. PDF 텍스트 추출은 `scripts/pdf_to_text.swift`(macOS PDFKit)로 한다.
- 이 데이터를 쓴 답변과 문서에는 출처(한국의약품안전관리원)와 기준일을 표시한다.
