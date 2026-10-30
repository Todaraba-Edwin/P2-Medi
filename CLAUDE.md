# CLAUDE.md: MediAgent(P2-Medi) 작업 지침

MediAgent는 공공 보건·의약품 데이터 기반 Agentic RAG 에이전트 프로젝트다. 이 파일은 저장소(P2-Medi)에서 작업할 때 따라야 할 맥락과 규칙이다. 문서(RFP, PRD, 아키텍처 문서, 평가 리포트, 발표 자료)는 `P2-doc/`에 둔다. 요구사항 원본은 `P2-doc/PJ2-RFP.md`이고, 일정과 티켓은 저장소 루트의 `schedule.md`와 `tickets/`에 둔다.

## 1. 프로젝트 한 줄 정의

사실은 공공 API·문서에서 가져오고, LLM은 설명과 종합만 맡는 근거 기반 질의응답 에이전트다. RAG와 Agent를 잘 설계하고, 다루고, 구현하는 과정이 목적이며, 약품 정보 조회·병용금기 확인·국가건강검진 안내·보건사업 자격 안내가 이를 다루기 위한 도메인이다.

방향성과 단계는 RFP(`P2-doc/PJ2-RFP.md`)의 3주 일정과 주차별 완료 기준을 따른다. 주차 완료 기준에 미달하면 다음 주 범위를 줄인다.

진단·처방·복용량 결정을 하는 서비스가 아니다. 공공데이터 기반 정보 제공이며, 응답의 결과는 의료적 판단을 대신하지 않는다.

## 2. 서브에이전트

| 에이전트 | 정의 파일 | 맡는 일 |
|---|---|---|
| `schedule-writer` | [`.claude/agents/schedule-writer.md`](.claude/agents/schedule-writer.md) | `schedule.md`와 `tickets/` 작성·갱신, 진행 현황과 Top 5 관리. 이 두 곳 밖의 파일은 읽기만 한다 |
| `git-actor` | [`.claude/agents/git-actor.md`](.claude/agents/git-actor.md) | git 작업 전담: 커밋, 브랜치, 병합, 태그, `.gitignore` 관리. 파일 내용은 고치지 않는다 |

일정, 티켓, 진행률 문서 작업은 `schedule-writer`가, git과 관련된 모든 작업은 `git-actor`가 전담한다. 키워드(SCH, RFP, PRD, AG, BE, FE), 문서 형식, 브랜치 정책(git-flow), 커밋 메시지 형식(`[keyword] 핵심내용`, 한글), 보고 형식은 각 정의 파일에서 확인한다. push는 사용자가 요청할 때만 한다.

### herdr 환경(`HERDR_ENV=1`)에서의 실행 규칙

- 서브에이전트는 **별도 pane**에서 작업한다. 현재 tab에 pane을 나누어 열고, 메인 pane의 포커스와 작업 디렉터리는 그대로 둔다.
- **pane 이름을 붙인다.** 새 pane을 열면 시작 전에 `herdr pane rename <pane> <에이전트 이름>`으로 서브에이전트와 같은 이름을 붙인다(예: `schedule-writer`). 메인 pane의 이름은 `P2-Medi-Main`이다. 이미 열려 있는데 이름이 없는 pane도 같은 방식으로 이름을 붙인다.
- **대상 pane은 ID로 명시한다.** `$HERDR_PANE_ID`는 다른 workspace의 pane으로 풀릴 수 있으므로 이름 변경·종료 같은 명령에 그대로 쓰지 않는다. `herdr pane list`로 workspace(`w3`)와 `cwd`가 P2-Medi인지 확인한 뒤 ID를 지정한다.
- 작업이 **완료되면 그 pane을 종료**한다. 호출마다 pane을 새로 열고 끝나면 닫는다.
- 종료하기 전에 **반영 내용을 Main pane에 보고**한다. 보고에는 변경 파일 수, SCH별 현황, Top 5, 가정·확인 필요 사항을 담는다. 보고만 믿지 않고 변경된 파일을 직접 확인한 뒤 닫는다.
- 다음 경우에는 pane을 닫지 않는다. 에이전트가 `working` 또는 `blocked` 상태이거나 timeout으로 끝났을 때, 사용자의 답이나 승인이 필요할 때, pane 입력창에 사용자가 적은 내용이 남아 있을 때다. 승인 창이 떠 있으면 입력을 임의로 보내지 않고 사용자에게 알린다.
- 열기, 시작, 요청, 보고 읽기, 종료의 구체적인 명령은 정의 파일의 "메인 세션 호출·종료 절차"를 따른다.
