---
id: RFP-30
label: RFP
title: 개발 하네스 사례 조사(OMC·gajae-code 등)와 차용할 스킬 후보
sch: SCH-01
status: done
priority: 권장
rfp: [RFP-8장]
created: 2026-11-04
done: 2026-11-05
---

# RFP-30 · 개발 하네스 사례 조사와 차용할 스킬 후보

> **📌 이 티켓에서 사용자가 답할 것 (대기 0건)** — RFP-30-01·02에 모두 답했고(2026-11-05 02는 "권고를 따름" A) 이 티켓은 종결했다. `.claude/`에 스킬·에이전트 정의 2개와 증거 규칙 1줄을 반영했다.
> 한눈에 보기: [schedule.md 지금 해야 할 일 (Top 5)](../../schedule.md#지금-해야-할-일-top-5)에서 같은 번호와 순서를 확인한다.

## Index
- [1. 이슈](#1-이슈)
- [2. 완료 조건](#2-완료-조건)
- [3. 조사 대상과 질문](#3-조사-대상과-질문)
- [4. 차용 기준](#4-차용-기준)
- [5. 지금까지 확인한 것](#5-지금까지-확인한-것)
- [6. 결과 양식](#6-결과-양식)
- [7. 관련](#7-관련)
- [8. 메모](#8-메모)
- [9. 결정 현황](#9-결정-현황)
- [10. 진행 기록 (실시간 갱신)](#10-진행-기록-실시간-갱신)
- [11. 조사 결과](#11-조사-결과)
  - [11.1 저장소 판별](#111-저장소-판별)
  - [11.2 설치·권한 요구](#112-설치권한-요구)
  - [11.3 스킬 후보 5개와 직접 쓸 때의 모습](#113-스킬-후보-5개와-직접-쓸-때의-모습)
  - [11.4 관점별 정리](#114-관점별-정리)
  - [11.5 미확인과 한계](#115-미확인과-한계)
  - [11.6 작업 중 적용할 스킬·에이전트 후보와 튜닝 제안](#116-작업-중-적용할-스킬에이전트-후보와-튜닝-제안)
- [12. 2차 상세 조사와 응용 제안](#12-2차-상세-조사와-응용-제안)
  - [12.1 읽은 범위와 방법](#121-읽은-범위와-방법)
  - [12.2 OMC 상세](#122-omc-상세)
  - [12.3 gajae-code 상세](#123-gajae-code-상세)
  - [12.4 응용 제안: 원형, 우리가 바꾼 점, 남길 증거](#124-응용-제안-원형-우리가-바꾼-점-남길-증거)
  - [12.5 11.3 후보의 수정과 RFP-30-02 연결](#125-113-후보의-수정과-rfp-30-02-연결)
  - [12.6 아직 미확인](#126-아직-미확인)

## 1. 이슈
사용자 질문(2026-11-04): Pre-Week는 RFP·PRD를 쓰는 기간인데, **PRD 작성으로 이대로 넘어갈지, 하네스로 프로젝트를 제어하는 부분에서 OMC·gajae-code 같은 사례를 살펴보고 이 프로젝트에 인용·첨가할 수 있는 에이전트 스킬을 추려 붙이는 고민을 먼저 할지.** 이 티켓은 그 조사의 범위·기준·결과 양식을 정해 두고, 순서는 결정 RFP-30-01로 묻는다.

RFP-29(하네스 전략)는 **제품 안쪽**(런타임·평가·개발 하네스의 Guide·Sensor)을 다뤘고 개발 하네스는 최소(pytest·ruff·pre-commit·Claude Code 훅)로 정했다(RFP-29-01 A). 이 티켓은 그 위에서 **코딩 에이전트(Claude Code)를 제어하는 스킬·워크플로 사례**를 볼지를 다룬다.

## 2. 완료 조건
- [x] (RFP-30-01) 조사 순서가 정해져 있다(D 병행: PRD는 메인 pane, 조사는 별도 pane, 2026-11-04).
- [x] 조사를 하기로 했다면 §3 대상별로 §6 양식의 후보 표가 채워져 있다(차용·보류·제외와 이유, 2026-11-04).
- [x] 차용하기로 한 스킬·절차가 `CLAUDE.md` 또는 `.claude/`에 반영되었다(2026-11-05, RFP-30-02 A): `.claude/skills/requirements-interview/SKILL.md`, `.claude/agents/plan-critic.md`, `CLAUDE.md` 2장·5장.
- [x] (RFP-30-03) 스킬 4개가 등록되었다(2026-11-09, B): 기존 `requirements-interview`에 `pr-consistency`·`project-code-review`·`decision-register`·`delegation-brief`를 더해 `.claude/skills/`에 5개가 있다(RFP-30-02의 "정의 파일 2개 이내" 제한을 이 결정으로 확장). `CLAUDE.md` 2장에 목록 반영.
- [x] (RFP-30-07 A, 2026-11-18) `.claude/agents/schedule-writer.md` 작업 범위 절에 "Bash `cd` 금지·절대 경로·명령 하나씩" 규칙을 넣었다(정의 파일 보강, 새 정의 파일 없음). 정의 파일 변경은 커밋됐다(`3957015`).
- [x] 설치한 외부 플러그인이 없다(해당 없음). 외부 코드는 설치·복사하지 않았고 출처 URL·읽은 날짜만 정의 머리에 적었다.

## 3. 조사 대상과 질문
| 대상 | 무엇인가(검색 요약, §5) | 확인할 질문 |
|---|---|---|
| OMC(oh-my-claudecode) | Claude Code용 멀티 에이전트 오케스트레이션 플러그인(마켓플레이스 설치) | 어떤 스킬·에이전트가 우리 워크플로(티켓·결정·`check_schedule.py`)에 맞는가 |
| gajae-code(gjc) | 저장소에 붙여 쓰는 외부 코딩 에이전트 하네스(인터뷰 → 계획 → 비판 → 실행, 승인 게이트) | `deep-interview`가 PRD·결정 정리에 쓸 만한가 |
| (선택) 그 밖의 사례 | Claude Code 기본 스킬·서브에이전트·훅 | 이미 있는 `.claude/agents/*` 4개와 겹치는가 |
- **우리 쪽 전제**: 지금 워크플로는 `CLAUDE.md` 규칙, 서브에이전트 4개(schedule-writer·tickets-writer·documents-writer·git-actor), herdr pane 실행, `check_schedule.py`다. 새 스킬은 이 위에 **얹히거나 대체할 때의 이득**으로 평가한다.

## 4. 차용 기준
| 기준 | 질문 |
|---|---|
| 겹침 | 이미 있는 규칙·서브에이전트와 같은 일을 하는가(그러면 중복) |
| 충돌 | `CLAUDE.md` 규칙(결정 번호, 카드, Top 5 유지, 커밋은 git-actor, `.env` 읽기 금지)과 부딪히는가 |
| 보안 | 플러그인이 파일·셸·네트워크에 어떤 권한을 요구하는가, 출처가 확실한가 |
| 비용 | 에이전트·스킬 수가 많아 토큰·설정 부담이 커지는가 |
| 가치 | 이 프로젝트의 목표(Agent-RAG 설계·평가 수치)에 직접 도움이 되는가, 아니면 도구 만지기에 시간이 가는가 |
| 증거 | 포트폴리오에서 "내가 설계한 하네스"로 설명 가능한가(차용한 것과 직접 만든 것을 구분) |

## 5. 지금까지 확인한 것
> **웹 검색 요약일 뿐이며 README 원문·소스를 읽은 것이 아니다.** 아래 내용은 사실로 확정하지 않는다. 조사를 하기로 하면 원문으로 확인한다.
- **OMC(Yeachan-Heo/oh-my-claudecode)**: Claude Code 마켓플레이스 플러그인으로 설치하는 멀티 에이전트 오케스트레이션. 에이전트·스킬 수는 출처마다 다르게 나온다(예: 28 에이전트 변형·32 스킬 / 19 에이전트·38 스킬). 팀 단위 오케스트레이션, 지속 실행 루프, 모델 라우팅, 실시간 HUD가 언급된다.
- **gajae-code(gjc)**: 어떤 저장소·워크트리에도 붙이는 외부 하네스. 인터뷰 → 계획 → 비판 → 변경(승인 게이트) 순서의 계획 게이트 워크플로, 기본 워크플로 스킬 4개(`deep-interview` 등). **실험적·베타**라고 스스로 밝히며, 같은 이름의 저장소가 여럿 검색되어 원본이 무엇인지 확인하지 못했다.
- 둘 다 **규모가 크고 외부 코드**라서 설치하지 않고 아이디어·스킬 구성만 읽는 쪽이 안전한지 먼저 판단해야 한다.

## 6. 결과 양식
| 사례 | 후보 스킬·절차 | 하는 일 | 겹치는 기존 장치 | 판단(차용·보류·제외) | 이유 | 반영할 곳 |
|---|---|---|---|---|---|---|
| gajae-code | `deep-interview` | 모호한 요구를 구체 요구로 정리(라운드 방식 세부는 미확인) | RFP-24 누락 점검, 결정 번호 | **차용(절차만)** | 질문을 1개씩 하고 모호도를 점수로 관리하는 방식은 OMC 쪽 SKILL.md에서 확인됨. 우리는 결정 번호·선택지·권장 형식이 이미 있어 형식은 유지하고 "목표·제약·기준 3축 점검"만 가져온다 | PRD-01 작성 절차(`.claude/skills/` 신규 또는 티켓 메모) |
| OMC | `deep-interview` | 소크라테스식 질문 1개/라운드, 모호도 점수(목표·제약·기준), 4·6·8라운드에 반론·단순화·온톨로지 점검, 스펙 파일 출력 | 위와 같음 | **차용(아이디어)** | 임계값 0.2 이하일 때만 스펙 확정, 승인 전 실행 금지. `.omc/` 상태 파일·`state_write` 도구는 불필요 | PRD-01 |
| OMC | `ralplan`(Planner·Architect·Critic) | 계획 초안 → 아키텍트·크리틱 독립 검토 → 승인 대기 | `self-review`, `spec-panel` 스킬, RFP-24 점검 | **보류** | 구조는 좋으나 3주·1인에 과함. 크리틱 관점만 PRD 검토 체크리스트로 쓴다 | PRD 검토 절차 |
| OMC | `critic` 에이전트 | 읽기 전용 검토, REJECT/REVISE/ACCEPT 판정, 모든 지적에 file:line 근거 | `self-review`, `code-review` | **차용(관점)** | "근거 없는 의견 금지" 규칙은 Sensor 쪽 사고방식과 맞음 | RFP-29 §6 매트릭스, 검토 지침 |
| OMC | `verify` | 완료 선언 전 테스트·빌드 실행 증거 요구 | `check_schedule.py`, pytest | **차용(규칙 1줄)** | "증거 없이 완료라 하지 않는다"는 5장 규칙과 같은 취지 | CLAUDE.md 5장 또는 BE-15 |
| OMC | `review` | 표준 준수와 의도 부합을 따로 보는 2축 리뷰, 재현된 지적만 보고 | 내장 `code-review` 스킬 | **보류** | 내장 스킬로 충분 | - |
| OMC | `agent-doc-discipline` | 에이전트가 읽는 문서(티켓·스킬)를 단독으로 읽혀도 되게 작성 | `tickets-writer`, 티켓 카드 규칙 | **차용(체크리스트)** | 완료 조건·다음 행동을 닫는 규칙이 티켓 품질에 직접 도움 | `tickets-writer` 정의 |
| OMC | `team`·`autopilot`·`ralph`·`execute`·HUD·알림 | 다중 에이전트 병렬 실행, 지속 루프 | herdr pane, git-actor | **제외** | 충돌: 커밋·일정은 전담 에이전트가 맡는 규칙과 부딪히고 `~/.omc` 쓰기, 외부 CLI·웹훅 설정이 붙음 | - |
| gajae-code | `ralplan`·`ultragoal`·`autoresearch` | 계획 비판, 목표·증거 추적, 조사 미션 | schedule.md·티켓, `deep-research` | **제외** | 외부 바이너리 설치 필요, 베타, 우리 티켓 체계와 중복 | - |

## 7. 관련
- 선행: 없음
- 후속: PRD-01(요구 정리 절차에 `deep-interview` 같은 아이디어가 쓰일 수 있음), BE-15(개발 하네스)
- 관련: RFP-29(하네스 전략, 개발 하네스 최소 결정), RFP-22(Agent 101), `CLAUDE.md` 2장(서브에이전트)·5장
- 관련 문서: `tickets/doc/RFP-29.md` §4.3·§6

## 8. 메모
- 이 티켓은 **조사 티켓**이고 코드를 만들지 않는다. 시간 상자는 2시간(제 제안)이며 넘으면 중단하고 결과를 적는다.
- "설치"와 "아이디어 차용"을 구분한다. 외부 플러그인 설치는 권한·공급망 부담이 있어, 기본은 **README의 스킬 구성만 읽고 `.claude/`에 직접 작성**하는 쪽이다.

## 9. 결정 현황
| ID | 질문 | 선택지 | 권장(★) | 상태 | 읽을 곳 | 답해야 넘어가는 것 |
|---|---|---|---|---|---|---|
| RFP-30-01 | PRD 작성으로 먼저 넘어갈까, 하네스 사례(OMC·gajae-code 등) 조사를 먼저 할까? | A) **PRD 먼저**(PRD-01 → PRD-07), 조사는 **시간 상자 2시간**(PRD-01 초안 뒤 또는 W1 첫날), 설치 없이 아이디어·스킬만 추려 차용 / B) **조사 먼저**(11-05 반나절), 그 뒤 PRD / C) 조사하지 않음(RFP-29 최소 하네스로 충분) | **결정됨(2026-11-04, 사용자 제안)**: 선택지 밖의 **D) 병행** — PRD 작업은 메인 pane(Claude)에서 진행하고 조사는 **별도 pane의 서브에이전트**에게 시킨다. 권장 A와 다른 점은 조사를 "PRD 뒤 시간 상자"가 아니라 **PRD와 동시에** 하는 것이고, 메인 작업을 막지 않으므로 순서 문제가 사라진다. 조사 범위·기준은 이 티켓 §3·§4, 시간 상자 2시간은 그대로 적용한다. (원래 권장) ★A. Pre-Week 마감이 11-06이고 산출물은 PRD-01·07이다. 포트폴리오 핵심은 제품 안쪽 하네스이고 개발 하네스는 이미 최소로 정했다. 외부 대형 플러그인은 기존 규칙·서브에이전트와 겹치고 권한·토큰 부담이 있다. 다만 요구 정리 아이디어(`deep-interview`)는 PRD 작성에 도움이 될 수 있어 PRD-01 초안 뒤에 짧게 본다 | 완료 | [RFP-30 §9](#9-결정-현황) | PRD-01 착수 순서, 조사 여부 |
| RFP-30-02 | 조사 결과 중 어떤 스킬·절차를 이 프로젝트에 직접 써서 붙일까? | A) **질문 정리 스킬 `requirements-interview` + 계획 점검 스킬 `plan-critic`**(`.claude/`에 정의 파일 2개를 우리 규칙으로 직접 작성) + 증거 규칙 1줄(`CLAUDE.md` 5장, "완료 보고에는 `check_schedule.py` 결과를 붙인다") / B) 질문 정리 스킬만 / C) 추가하지 않음(현행 서브에이전트·규칙으로 충분) | **결정됨(2026-11-05, 사용자 "권고를 따름")**: A. ★A. 조사 결과 외부 플러그인 설치는 권고하지 않고(§11.2) 아이디어만 직접 쓰는 쪽이 설계 증거로도 남는다. 질문 정리는 PRD 작성(PRD-01·07)에 바로 쓰이고, 계획 점검은 읽기 전용이라 위험이 작다. 새 정의 파일은 2개 이내로 제한한다(조사 제안). 다만 두 스킬의 설계안은 시험하지 않은 제 추정이며 실제 프롬프트는 열어 보지 못했다(§11.5) | 완료 | [RFP-30 §11.3·§11.6](#113-스킬-후보-5개와-직접-쓸-때의-모습) | `.claude/` 스킬 작성 여부(PRD-01 검토 절차 포함) |
| RFP-30-03 | `.claude/skills/`에 스킬을 몇 개 더 등록할까? (RFP-30-02의 "정의 파일 2개 이내" 제한을 확장하는 결정) | A) 등록하지 않음(requirements-interview만) / B) **스킬 4개 추가**: 이미 만든 `pr-consistency`(PR 전 기준 문서 일치성)·`project-code-review`(Agent-RAG 안전 불변식 코드 검토)와 새로 쓰는 `decision-register`(결정 동기화 절차)·`delegation-brief`(지시서·herdr 위임 절차) / C) 2개만 추가(`pr-consistency`·`decision-register`) | **결정됨(2026-11-09, 사용자 "권고를 따름")**: B. ★B. 네 스킬은 CLAUDE.md 5장·2장에 이미 있는 절차를 한 곳에 모은 것이라 새 규칙을 만들지 않고, 새 서브에이전트 정의는 더하지 않는다(에이전트 총량 불변). 외부 코드 설치 없음 | 완료 | [RFP-30 §9](#9-결정-현황) | `.claude/skills/` 등록 범위 |
| RFP-30-04 | Recap "현재 상태"가 길어지는 문제를 어떻게 막을까? | A) **단락 1개만 두고 갱신 때 이전 단락은 `schedule-changelog.md`로 이동** / B) 현행(단락 누적) 유지 | **결정됨(2026-11-11, 사용자 "A 권장대로")**: A. ★A. Recap이 약 28KB까지 커져 읽기 어려웠다. 에이전트·스킬 총량은 불변(`.claude/agents/schedule-writer.md` 갱신 규칙 한 줄만 추가). CLAUDE.md 5장은 메인이 판단 | 완료 | [RFP-30 §9](#9-결정-현황) | Recap 구조 |
| RFP-30-05 | `schedule.md` Top 5를 어떤 구조로 둘까? | A) **트랙 4표**(Agent·BackEnd·FrontEnd·Docs, 트랙당 최대 5행)로 나누고 행마다 `진행`(병렬·부분 병렬·직렬)과 `지금 할 수 있는 것`을 표시 / B) 현행 단일 5행(직렬 N·병렬 A·B) 유지 | **결정됨(2026-11-18, 사용자 지시 "Top-5 를 4개의 열로 나누고 Agent, BackEnd, FrontEnd, Docs 리스트업 확장 / … 직렬로 인한 작업지연보다는 동시에 병렬 처리할 수 있도록")**: A. ★A. 단일 5행은 Agent 직렬만 보여 BE·FE·Docs의 독립 작업이 Top 5 밖에서 놀았다. 절 제목 `## 지금 해야 할 일 (Top 5)`와 앵커는 그대로 둔다(티켓 카드 링크 유지). 에이전트·스킬 총량 불변(`check_schedule.py`·`schedule-writer.md` 규칙 갱신만) | 완료 | [schedule.md 지금 해야 할 일 (Top 5)](../../schedule.md#지금-해야-할-일-top-5) | Top 5 구조, `check_schedule.py` 검사 |
| RFP-30-06 | Top 5 트랙별 작업을 어떤 환경·모델로 돌릴까? | A) **FrontEnd = VS Code Claude Code(Fable 5.2, 사용자 실행), BackEnd·Agent = herdr pane Opus 5.5, Docs = herdr pane Sonnet 5.5**, 지시서·명령 안내에 환경·대상·모델 3줄 고지 / B) 모두 herdr pane 기본 모델 | **결정됨(2026-11-18, 사용자 지시 "FrontEnd의 경우 vscode-claudecode-fable5.2 / BackEnd, Agent의 경우, 현재 세션의 별도의 pane에서 Opus5.5로 / Docs 의 경우, sonnet 으로 … 해당 작업 환경, 대상, 모델")**: A. ★A. 트랙 병렬에서 어디서 어떤 모델로 도는지 사용자가 한눈에 확인하려고 | 완료 | `CLAUDE.md` 2장 "메인 pane의 역할과 위임" 2번 | 지시서 머리·명령 안내 형식 |
| RFP-30-07 | `schedule-writer` 정의에 "Bash `cd` 금지·절대 경로" 규칙을 넣을까? | A) 넣는다(`git -C <절대 경로>`, 명령은 하나씩, 파일 읽기·검색은 Read·Grep 우선) / B) 넣지 않는다 | **결정됨(2026-11-18, 사용자 "RFP-30-07 동의")**: A. ★A. `cd`가 든 복합 명령이 `.env` 차단 규칙과 겹쳐 매번 승인 창이 떴다(2026-11-18 하루 7회). 적용 위치는 `.claude/agents/schedule-writer.md` 작업 범위 절(Bash 규칙 줄 아래, 정의 파일은 `.claude/`라 메인·`git-actor` 커밋 대상). 에이전트·스킬 총량 불변(기존 정의 보강) | 완료 | `.claude/agents/schedule-writer.md` | 정의 파일 보강(커밋됨 `3957015`) |
| RFP-30-08 | 일정을 SCH 안에서 어떤 단위로 굴릴까? | A) **2일 스프린트**: S1 인증(11-19~20)·S2 프로필·온보딩+Naver(11-21~22)·S3 chat 연동+배포 도메인(W3 초), 스프린트마다 데모 시나리오·시험·짧은 리포트 / B) 주 단위 SCH만 유지 | **결정됨(2026-11-18 밤, 사용자 답)**: A. ★A. 인증·프로필이 W2~W3 범위로 들어왔고(AG-10-06 A) 확장이라 매 2일마다 데모로 확인해 미달 시 줄일 자리를 찾기 쉽다. 에이전트·스킬 총량 불변. 스프린트 표는 `schedule.md` Top 5 아래 "스프린트 표"에 둔다. 리포트는 `P2-doc/report/`(로컬 전용, 6장) 짧은 md+PDF 한 쌍 | 완료 | [schedule.md 스프린트 표](../../schedule.md#스프린트-표-rfp-30-08-a) | 스프린트별 데모·리포트 |

| RFP-30-09 | FrontEnd 작업을 어디서 돌릴까? (RFP-30-06 A의 "FrontEnd = VS Code만"을 넓히는 결정) | A) 터미널 herdr pane `claude-fable-5-1`(메인이 지시·감시) / B) VS Code Fable 5.2(사용자 실행) / C) 둘 다 허용, 작업마다 고름(무인·밤 작업은 터미널, 보면서 다듬을 때는 VS Code) | **결정됨(2026-11-19 밤, 사용자 "RFP-30-09 C, 오늘밤엔 터미널에서")**: C. ★C. 확인 사실(2026-11-19 메인 확인): 터미널 CLI 2.1.311에서 `claude-fable-5-1`은 정상 응답하고 `claude-fable-5-2`는 `unrecognized_model` 경고를 낸다. RFP-30-06 A의 BackEnd·Agent·Docs 규칙은 그대로다. `CLAUDE.md` 2장·메모리는 메인이 반영했다(미커밋). 에이전트·스킬 총량 불변 | 완료 | `CLAUDE.md` 2장 "Top 5 트랙별 실행 환경·모델" | FrontEnd 지시서 머리의 실행 환경 줄 |

## 10. 진행 기록 (실시간 갱신)
- 2026-11-04 · 결정 RFP-30-01(D 병행)에 따라 별도 pane에서 조사 서브에이전트를 시작한다. 이 티켓 §6 표를 채우고 §11에 조사 결과를 적도록 지시했다(수정 범위는 이 파일만).
- 2026-11-04 · **조사 완료, 결정 RFP-30-02 올림**(차용할 후보 5개 중 무엇을 직접 쓸지). 설치는 권고하지 않는다(§11.2).
- 2026-11-04 · 조사 서브에이전트가 두 저장소의 README와 OMC `skills/`·`agents/` 일부 원문(WebFetch)을 읽고 §6 표와 §11을 채웠다. 설치·실행 없음. 확인 못한 것은 §11.5에 적었다.
- 2026-11-04 · 2차 상세 조사: 두 저장소의 에이전트·스킬·훅 원문을 더 읽고 §12에 기록했다(응용 제안 12건은 §12.4). 설치·실행 없음, 수정 범위는 이 파일만.

- 2026-11-11 · **RFP-30-04 A 등록**: Recap "현재 상태" 1단락 규칙(이전 단락은 `schedule-changelog.md`로 이동)을 `.claude/agents/schedule-writer.md`에 한 줄 추가했다. 티켓은 `done` 유지(대기 결정 0건).
- 2026-11-09 · **RFP-30-03 B 등록**: 사용자 "권고를 따름"으로 스킬 4개(`pr-consistency`·`project-code-review`·`decision-register`·`delegation-brief`)를 등록했다. 앞의 두 스킬 머리의 "등록 대기"를 이 번호로 고쳤고 새 두 스킬을 `.claude/skills/`에 작성했다. 티켓은 `done` 유지(대기 결정 0건).
- 2026-11-05 · **RFP-30-02 A 반영, 종결**: `.claude/skills/requirements-interview/SKILL.md`(질문 한 가지씩·결정 번호·티켓 결정 현황 표 초안만·승인 전 구현 금지)와 `.claude/agents/plan-critic.md`(Read·Glob·Grep만, REJECT/REVISE/ACCEPT, `파일:줄` 근거, 읽기 전 예측 3개)를 직접 작성했고 CLAUDE.md 2장에 둘을 등록, 5장에 증거 규칙(완료·종결 보고에 `check_schedule.py` 결과와 변경 파일 목록)을 추가했다. 외부 코드는 설치하지 않았다. `failure-trace`(AG-12·13용)와 훅(#8)은 포함하지 않고 AG와 BE-15에서 따로 정한다.

## 11. 조사 결과
> 읽은 범위: 아래 URL의 README·디렉터리 목록·SKILL.md·agent .md. WebFetch는 작은 모델의 요약을 돌려주므로 **원문 그대로가 아니라 요약본**이다. 인용이 중요해지면 사람이 원문을 다시 열어야 한다. 조사일 2026-11-04.

### 11.1 저장소 판별
| 저장소 | 사실(출처 페이지 표시) | 판단 |
|---|---|---|
| [Yeachan-Heo/gajae-code](https://github.com/Yeachan-Heo/gajae-code) | 포크 표기 없음, 별 3.1k, 포크 433, 커밋 13,347, MIT, README 현재 버전 v0.15.3 | **원본**(추정 근거: 포크 표기 없음, 다른 넷이 이곳을 "forked from"으로 가리킴) |
| [chlee1001/gajae-code](https://github.com/chlee1001/gajae-code) | 포크, 별 0, 커밋 4,319 | 포크 |
| [phdgil/gajae-code](https://github.com/phdgil/gajae-code) | 포크, 별 0, 커밋 906, 이름에 `visual-suggestion`이 보임, v0.6.0 | 포크 |
| [YoungsPlace/gajae-code](https://github.com/YoungsPlace/gajae-code) | 포크, 별 0, 커밋 1,405, v0.7.0 | 포크 |
| [10kH/gajae-code](https://github.com/10kH/gajae-code) | 포크, 별 0, 커밋 12,291 | 포크 |
- OMC도 같은 작성자(Yeachan-Heo)의 [oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode)이며 별 40.6k, 포크 3.6k, MIT. 사실: 두 프로젝트는 `deep-interview`·`ralplan`·`ultragoal`·`autoresearch` 이름을 함께 쓴다. 추정: 같은 작성자가 개념을 공유한다.
- 에이전트 수는 OMC `agents/` 디렉터리 목록에서 **19개 파일**이 확인되었다(analyst, architect, code-reviewer, code-simplifier, critic, debugger, designer, document-specialist, executor, explore, git-master, planner, qa-tester, scientist, security-reviewer, test-engineer, tracer, verifier, writer). §5의 "28 에이전트·32 스킬" 같은 수치는 이 목록과 맞지 않으며 `skills/`는 약 49개 디렉터리다.

### 11.2 설치·권한 요구
| 대상 | 설치 | 쓰는 위치·권한 | 네트워크·기타 |
|---|---|---|---|
| OMC | 마켓플레이스 플러그인 또는 `npm i -g oh-my-claude-sisyphus@latest` | `~/.omc/`, `.omc/`, `~/.config/claude-omc/`에 쓰기, tmux 사용 | 알림 웹훅·OpenClaw 게이트웨이·Jev 판단 API는 설정해야 켜짐(기본 `shadow`는 기록만 한다고 README가 말함). 세션 데이터 전송 여부는 **미확인** |
| gajae-code | 셸 스크립트로 미리 빌드된 바이너리 설치(`curl ... | sh`, 태그 버전 권장) | 코드 변경 전 승인 필요. macOS 데스크톱 제어 `computer` 도구가 지원 호스트에서 **기본 호출 가능**(`computer.enabled=false`로 끔) | 텔레메트리 서술 **미확인**, 베타라고 스스로 밝힘 |
- 우리 규칙과의 충돌: OMC는 `.omc/`에 상태를 두고 자체 오케스트레이션 모드를 가져, 커밋은 `git-actor`·일정은 `schedule-writer`라는 역할 분리와 겹친다. 둘 다 `.env` 읽기 금지 규칙을 지키는 장치는 없다(미확인). 따라서 **설치는 권고하지 않는다.**

### 11.3 스킬 후보 5개와 직접 쓸 때의 모습
설치 없이 `.claude/skills/`에 우리 규칙으로 직접 쓴다고 가정한 스케치다.
1. **`requirements-interview`**(OMC `deep-interview` 변형, 판단: 차용)
   - 한 번에 질문 1개, 결정 번호 `{티켓}-{nn}` 형식과 A/B 선택지·★ 권장·읽을 곳을 반드시 붙인다.
   - 목표·제약·완료 기준 3축으로 빈 곳을 점검해 남은 모호함을 목록으로 보인다.
   - 결과는 새 파일이 아니라 해당 티켓의 `결정 현황` 표 초안으로만 낸다(결정을 티켓 밖에서 만들지 않는 5장 규칙).
   - 구현은 사용자 승인 전에 시작하지 않는다.
2. **`plan-critic`**(OMC `critic`·`ralplan` 크리틱 역할, 판단: 차용)
   - 읽기 전용(Read/Grep/Glob만). PRD·티켓 초안을 받아 REJECT/REVISE/ACCEPT를 낸다.
   - 모든 지적에 `파일:줄` 근거를 요구하고, RFP 9장 평가 기준 변경 여부, 결정 번호 누락, Top 5 불일치를 고정 점검 항목으로 둔다.
3. **`done-needs-evidence`**(OMC `verify`, 판단: 차용)
   - 완료 보고 전에 `python3 scripts/check_schedule.py` 결과와 변경 파일 목록을 붙이게 한다.
   - 실행 못 했으면 "미실행"으로 쓰게 한다. CLAUDE.md 5장 한 줄 규칙으로도 충분할 수 있다.
4. **`agent-doc-check`**(OMC `agent-doc-discipline`, 판단: 차용)
   - `tickets-writer`가 쓰는 티켓을 "처음 읽는 세션이 혼자 이해하는가"로 점검한다: 완료 조건, 다음 행동, 중복 서술 없음.
   - `check_schedule.py`가 못 잡는 문장 품질만 본다.
5. **`harness-matrix-review`**(우리 자체 안, OMC 직접 대응 없음, 판단: 보류)
   - RFP-29 §6의 Guide·Sensor 매트릭스에서 규칙마다 Sensor가 비어 있는지 점검한다. 외부 사례가 아니라 우리 문서에 필요한 일이라 이 티켓의 범위를 넘을 수 있다.

### 11.4 관점별 정리
- (a) PRD·요구 정리: `deep-interview`가 가장 맞는다. 사실: OMC 쪽 SKILL.md에 모호도 가중치(그린필드 목표 0.40·제약 0.30·기준 0.30), 임계값 0.2, 라운드별 반론·단순화 점검이 있다. gajae-code 쪽 README는 "구체 요구로 정리한다"까지만 밝히며 세부는 미확인이다.
- (b) 결정·티켓 관리: 맞는 외부 스킬 없음. 우리 결정 번호·카드·Top 5 체계가 더 구체적이다. `agent-doc-discipline`의 문서 점검 관점만 쓸 만하다.
- (c) 계획 검토·리뷰·검증: `critic`의 "근거 없는 지적 금지", `verify`의 "증거 없이 완료 금지", `review`의 표준·의도 2축 분리가 참고된다. 내장 `code-review`·`self-review`와 겹치므로 새로 만들 필요는 작다.
- (d) 하네스(Guide·Sensor): 사실로 확인된 것은 `ralplan` 사전 게이트(구체적 기준 없는 실행 요청을 계획으로 돌림)와 승인 전 변경 금지다. 이는 Guide 쪽(지침)이고, 코드로 검사하는 Sensor는 두 사례에서 확인하지 못했다(미확인). 우리 `check_schedule.py`가 Sensor 역할을 이미 한다.
- 비용·가치·증거: 외부 대형 플러그인은 설정·토큰 부담이 크고 포트폴리오에서 "내가 설계한 것"을 흐린다. 위 후보는 규칙 몇 줄 수준이라 1~2시간 안에 직접 쓸 수 있고 설계 증거로도 남는다.

### 11.5 미확인과 한계
- gajae-code `deep-interview`의 실제 절차(라운드, 점수 여부)와 OMC 것과의 동일성: README에 없고 `docs/`에서도 해당 문서를 찾지 못했다.
- OMC 플러그인의 텔레메트리·데이터 전송 기본값, 훅이 요구하는 정확한 권한 범위.
- 두 도구가 `.env` 같은 비밀 파일을 읽지 않도록 막는지.
- `ultragoal`·`autoresearch`의 세부 동작, 에이전트 19개 각각의 프롬프트·도구 제한(`critic`만 확인).
- 별·커밋 수는 조사일 페이지 표시값이며 최종 갱신일은 보지 못했다.
- 출처: https://github.com/Yeachan-Heo/oh-my-claudecode (README, `skills/{deep-interview,ralplan,verify,review,agent-doc-discipline}`, `agents/critic.md`, `agents/`·`skills/` 목록), https://github.com/Yeachan-Heo/gajae-code (README, `docs/` 목록), 위 §11.1의 포크 4곳.

### 11.6 작업 중 적용할 스킬·에이전트 후보와 튜닝 제안
> **원칙**: 그대로 쓰지 않고 우리 규칙(결정 번호, 카드, Top 5, `.env` 금지, 커밋은 git-actor)에 맞게 **프롬프트·도구 권한·출력 형식을 고쳐 쓴다.** 아래 중 이 환경에 이미 있는 항목(스킬·에이전트 이름은 세션 목록에서 확인)은 설치가 필요 없고, OMC·gajae-code 원문은 참고만 한다. "튜닝 제안"은 제 설계안이고 아직 시험하지 않았다(추정).

**A. 작업 단계별 후보**
| 단계 | 후보(출처) | 그대로 쓸 때의 문제 | 튜닝 제안 |
|---|---|---|---|
| PRD·요구 정리 (PRD-01) | 기존 에이전트 `requirements-analyst`, 스킬 `sc:brainstorm`(참고: OMC `deep-interview`) | 질문 형식·산출 위치가 우리 규칙과 다름, 질문을 한꺼번에 던질 수 있음 | 질문 1개씩, 결정 번호·A/B·★·읽을 곳 강제. 산출은 PRD 문서와 티켓 `결정 현황` 표 초안으로만. 목표·제약·완료 기준 3축 빈칸 점검을 마지막에 붙임 |
| 계획·PRD 검토 | 스킬 `sc:spec-panel`, 에이전트 `self-review`(참고: OMC `critic`) | 전문가 다수 의견이 길고 근거 표기가 느슨함 | 읽기 전용으로 제한. 지적마다 `파일:줄` 필수, 판정은 REJECT/REVISE/ACCEPT. 고정 점검: RFP 9장 평가 기준 변경 여부, 결정 번호 누락, Top 5 불일치 |
| 티켓·일정 작성 | 기존 `schedule-writer`·`tickets-writer`(참고: OMC `agent-doc-discipline`) | 이미 역할이 맞아 새 에이전트는 불필요 | `tickets-writer` 정의 끝에 "처음 읽는 세션이 혼자 이해하는가" 체크 3줄(완료 조건, 다음 행동, 중복 서술 없음) 추가 |
| 구현·리팩터 | 스킬 `simplify`, `sc:implement`, 에이전트 `python-expert` | 범위를 넘는 수정, 과한 추상화 | 티켓 번호가 있는 파일만 수정, 평가 기준·judge 설정 파일은 변경 금지 목록에 넣음(5장 평가 기준 유지 규칙) |
| 코드 리뷰·검증 | 스킬 `code-review`, 에이전트 `quality-engineer`(참고: OMC `verify`·`review`) | 완료 선언 때 실행 증거가 빠질 수 있음 | 완료 보고 전에 `check_schedule.py`와 pytest 결과 또는 "미실행" 표기를 필수로. 표준 준수와 의도 부합을 따로 보고 |
| 보안·비밀 | 스킬 `security-review`, 에이전트 `security-engineer` | 일반 점검이라 우리 특수 규칙을 모름 | 점검표에 `.env` 값 노출, 로그·응답에 키 출력, 질문·대화 저장 금지(프로필 최소 저장), 고정 문구 코드 강제를 추가 |
| 평가·실패 분석 (AG-11~13) | 에이전트 `root-cause-analyst`, `quality-engineer` | 시험셋을 열어볼 위험 | 개발셋만 읽도록 경로 제한, 결과는 k/n과 Wilson 95% 구간 형식으로만 보고(RFP-26-04, 9.1절) |
| 외부 조사 | 에이전트 `deep-research`·`deep-research-agent`, 스킬 `sc:research` | 출처 신뢰도 표기가 약함 | 출처 표에 기준일·원문/요약 구분 열 추가, 요약본 근거 단독 사용 금지(이번 조사의 WebFetch 한계) |
| 하네스 점검 (RFP-29) | 자체 제작 `harness-matrix-review`(§11.3의 5번) | 외부 대응물 없음 | Guide·Sensor 매트릭스에서 Sensor가 빈 규칙을 표로 출력. `check_schedule.py`가 못 보는 항목만 대상 |

**B. 우선순위 제안(추정)**
1. 지금 바로(PRD-01 중): 요구 정리 질문 절차 튜닝. 설치 없이 기존 `requirements-analyst`에 규칙 몇 줄을 얹는 쪽이 가장 싸다.
2. W1 안: `plan-critic` 읽기 전용 점검과 "완료엔 증거" 규칙. 포트폴리오에서 Sensor 사고를 보여 주는 증거가 된다.
3. 필요해질 때: 보안 점검표 보강, 평가 분석 에이전트의 경로 제한. 에이전트·스킬을 늘리면 설정·토큰 부담이 커지므로(§4 비용) **새 정의 파일은 2개 이내**로 제한하는 것을 제안한다.

**C. 튜닝할 때 공통으로 고칠 것**
- 도구 권한: 검토류는 Read/Grep/Glob만, 쓰기는 담당 에이전트(schedule-writer 등)에게만. `.env`는 `--disallowedTools`로 막는 기존 방식 유지(CLAUDE.md 3장).
- 출력 형식: 우리 보고 형식(Top 5·Recap)과 결정 번호 형식에 맞춘다. 별도 라벨(D1, Q1) 금지.
- 승인 게이트: 계획 승인 전 파일 변경 금지는 OMC·gajae-code 모두 강조하는 점이라 차용하되, 우리는 이를 코드(훅)로 강제할지 지침으로만 둘지 BE-15에서 정한다. 이 판단은 아직 결정 번호가 없다.
- 증거 구분: 포트폴리오 설명 시 "차용한 아이디어"와 "직접 설계한 것"을 이 표의 열로 구분해 둔다.
- 한계: 위 에이전트·스킬의 실제 프롬프트 내용은 이 조사에서 열어 보지 않았다(이름과 설명만 확인). 튜닝 전에 각 정의를 읽어야 한다. (2차에서 OMC 쪽 일부를 읽었다: §12)

## 12. 2차 상세 조사와 응용 제안
> 목표는 가져다 쓰는 것이 아니라 **원형의 설계 아이디어를 읽고, 우리 문제(Agent-RAG 프로젝트의 요구 정리·결정 관리·평가 분석)에 맞게 바꾼 설계를 남기는 것**이다. 그래서 §12.4는 항목마다 "원형 → 우리가 바꾼 점 → 포트폴리오 증거"를 나눈다. 아래 "제안"은 제 설계안이며 시험하지 않았다(추정).

### 12.1 읽은 범위와 방법
- 방법: raw.githubusercontent.com 원문을 WebFetch로 읽었다. WebFetch는 작은 모델이 요약해서 돌려주므로 **요약본**이다. 문구를 따옴표로 인용한 곳은 그 요약 안의 인용이다. 설치·실행은 하지 않았다.
- OMC(`Yeachan-Heo/oh-my-claudecode`)에서 읽은 것: `agents/{critic,analyst,verifier,tracer,planner}.md`, `skills/{deep-interview,ralplan,verify,review,agent-doc-discipline,minimal-code-discipline,intent,trace,ultragoal}/SKILL.md`, `hooks/hooks.json`, README.
- gajae-code(`Yeachan-Heo/gajae-code`)에서 읽은 것: README, 루트 구조, `AGENTS.md`, `docs/skills.md`, `plugins/gajae-code/` 구조와 `.mcp.json`, `sdk-skills/`·`docs/tools/` 목록.
- 안 읽은 것: OMC의 나머지 에이전트 14개와 스킬 약 40개, gajae-code의 번들 스킬 4개의 프롬프트 본문(§12.3에서 위치를 못 찾음).

### 12.2 OMC 상세
**(1) 에이전트 — 읽은 5개**
| 이름 | 하는 일 | 도구 제한·모델 | 설계에서 눈에 띄는 점 |
|---|---|---|---|
| `critic` | 계획·코드의 최종 품질 관문. 판정 REJECT/REVISE/ACCEPT-WITH-RESERVATIONS/ACCEPT | Write·Edit 차단, Opus | 읽기 전에 문제 3~5개를 **미리 예측**하고 찾음. 계획은 가정 추출·사전 부검·의존성·모호성·실현성·롤백의 6단계로 검토. 심각 1건 또는 주요 3건 이상이면 "ADVERSARIAL 모드"로 승격. 지적은 file:line이나 인용문이 없으면 의견이라 취급. 자기 점검 후 확신 낮은 지적은 "열린 질문"으로 이동 |
| `analyst` | 계획 전 요구 분석. 누락 질문·미정 가드레일·범위 위험·미검증 가정·누락된 완료 기준·엣지 케이스를 구조화해 보고 | Write·Edit 차단, Opus | 시장성은 안 따지고 "명확히 만들 수 있는가"만 봄. 마지막 메시지에 결과 전체를 담아야 함(빈 인사 금지). 결정 항목은 근거와 함께 Open Questions로 |
| `verifier` | 완료 주장이 **새 증거**에 근거하는지 확인 | 도구 목록 미확인 | 요구마다 VERIFIED/PARTIAL/MISSING, 판정 PASS/FAIL/INCOMPLETE. 금지: 같은 컨텍스트에서 자기 작업 승인, 오래된 테스트 출력 신뢰, 컴파일만으로 검증 |
| `tracer` | 관찰된 결과의 원인을 경쟁 가설로 추적 | 미확인 | 관찰과 해석을 분리, 가설 3개 이상을 서로 다른 틀(코드 경로·설정·측정 오류·오케스트레이션)로 생성, 반증 증거를 먼저 찾음, 증거 위계 6단계, 마지막에 "가장 값싼 판별 실험" 1개 제시 |
| `planner` | 인터뷰 후 계획 작성, 구현은 안 함 | 미확인 | 질문은 한 번에 1개, **코드베이스 사실은 사용자에게 묻지 않고 탐색 에이전트로 확인**, 계획 3~6단계, 사용자가 "계획으로 만들어"라고 할 때만 작성, 합의 모드에서 원칙·결정 동인·대안 2개 이상·ADR 포함 |

**(2) 스킬 — 읽은 9개**
| 이름 | 하는 일 | 요구하는 것 | 메모 |
|---|---|---|---|
| `deep-interview` | 모호도 점수로 관문을 두는 소크라테스식 인터뷰 | `AskUserQuestion`, 탐색 서브에이전트, `state_write/read`, `.omc/` 쓰기 | 모호도 = 1 − (목표×0.40 + 제약×0.30 + 기준×0.30), 기존 코드가 있으면 맥락 항목 포함. 임계값 기본 0.2. 4·6·8라운드에 반론자·단순화·온톨로지 점검. 스펙은 `.omc/specs/`에 저장하고 실행은 사용자 승인 후. 점수 계산은 모델이 매긴 판단(코드 계산 여부는 미확인) |
| `intent` | 현업 피드백을 "목표 수준 결정 문서"로 정리 | `docs/intents/<slug>/intent.md` | 질문은 **번호 붙인 묶음**으로 던지고 답도 번호로(`1 yes; 2 uncertain`). 모르는 것은 압박하지 않고 `待确认`으로 남김. 5개 절(문제·목표·사용자와 시스템·제약·미결) 충족이 종료 조건. 에이전트는 사실을 지어내거나 서명하지 않음 |
| `ralplan` | 계획 합의(Planner → Architect·Critic 독립 검토) | `.omc` 상태 | 최대 5회 재검토, 합의 전까지 `pending approval`, 파일 변경·위임 금지. 구체 앵커(파일 경로·이슈 번호·완료 기준) 없는 실행 요청은 계획으로 돌림 |
| `verify` | 완료 전 실행 증거 요구 | 테스트·빌드 실행 | "증거 없이 완료라 하지 않는다" |
| `review` | 표준 준수와 의도 부합을 **분리된 두 축**으로 검토 | 선택적 검증기 서브태스크 | 재현되는 지적만 보고, "지적 없음"도 유효 |
| `agent-doc-discipline` | 에이전트가 읽는 문서의 작성 규율 | 없음 | 단독으로 읽혀도 행동 가능, 완료 기준·다음 행동으로 마무리, 중복·도구가 알려주는 내용 반복 금지 |
| `minimal-code-discipline` | 불필요한 코드 예방 5단계(존재 여부 → 재사용 → 의존성 사다리 → 이해 → 단순함) | 없음 | **보호 경계**(신뢰 경계의 검증, 데이터 손실 방지 오류 처리, 보안 통제, 접근성, 명시된 범위)는 줄이지 않음 |
| `trace` | `tracer`를 가설 레인별 병렬로 돌림 | 팀 모드 | 3개 가설, 반박 라운드, 판별 실험 |
| `ultragoal` | 목표를 순서 있는 스토리로 나누고 **추가만 가능한 장부**(ledger)에 증거와 함께 기록 | CLI(`omc ultragoal`) | Claude의 `/goal`이 세션 한정(Stop 훅)이라 상태가 사라지는 한계를 보완. 쉘이 `/goal` 상태를 직접 못 바꾸고 지시문만 출력한다고 문서가 한계를 밝힘 |

**(3) 훅과 권한(`hooks/hooks.json`)** — 사실: 이벤트 15종 이상에 훅이 걸려 있고 모두 Node 래퍼로 실행된다.
- `UserPromptSubmit`: `keyword-detector`, `skill-injector`(입력어로 모드·스킬을 자동 주입)
- `PreToolUse`: 모든 도구에 `pre-tool-enforcer`, Bash에는 `git-guardrails`
- `PermissionRequest`(Bash): `permission-handler`
- `PostToolUse`: `post-tool-verifier`, 규칙·디렉터리 맥락 주입, 프로젝트 메모리
- `SubagentStart/Stop`: 추적과 `verify-deliverables`
- `Stop`: `context-guard-stop`, `workflow-drift-guard`, `persistent-mode`, `budget-guard`, `code-simplifier`
- 네트워크 호출은 스크립트 이름만으로는 확인되지 않는다(미확인).
- 우리 규칙과의 충돌(추정): `git-guardrails`와 `git-actor`의 git 전담, `persistent-mode`(종료 막기)와 herdr의 "working/blocked/사용자 승인이면 닫지 않음" 규칙, 자동 주입 훅이 CLAUDE.md의 명시적 규칙 순서를 흐릴 가능성. 그래서 **설치는 여전히 권고하지 않는다.**

### 12.3 gajae-code 상세
- **구조(사실)**: Bun 기반 TypeScript 모노레포에 Rust 네이티브(`crates/`)가 붙은 독립 CLI 제품이다. 루트에 `AGENTS.md`, `plugins/`, `sdk-skills/`, `docs/` 등이 있다.
- **번들 스킬 4개**(`deep-interview`, `ralplan`, `ultragoal`, `autoresearch`): `docs/skills.md`가 "바이너리에 번들되어 파일시스템 스킬로 덮어쓸 수 없고, 신뢰 설정과 무관하게 항상 사용 가능"이라고 밝힌다. 그러나 **프롬프트 본문 파일은 이번 조사에서 위치를 찾지 못했다**(`plugins/.../skills`에는 없음). 즉 gajae-code의 `deep-interview`가 OMC 것과 같은지는 여전히 미확인이다.
- **Claude Code용 플러그인**(`plugins/gajae-code/`): 스킬 3개(`gjc-delegation`, `gjc-sdk-guides`, `gjc-sdk-session`), 명령 2개(`delegate_plan.md`, `delegate_execute.md`), MCP 서버 1개(`gjc-coordinator`, 실행 명령 `gjc mcp-serve coordinator`). `scripts/generate-gjc-plugins.ts`가 자동 생성한 파일이라 수정하지 말라고 README가 밝힌다. 즉 Claude Code 쪽에서는 **gjc 바이너리를 호출하는 위임 플러그인**이고, 우리가 읽을 "워크플로 스킬 본문"이 아니다.
- **스킬 신뢰 설정(사실)**: 프로젝트 스킬(`.gjc/skills/`)과 사용자 스킬 로드를 `skills.trustProjectSkills`·`skills.trustUserSkills`로 따로 끈다. Claude Code의 `.claude/skills`는 직접 로드하지 않고 가져오기 원본으로만 인식한다.
- **`AGENTS.md`에서 읽은 규칙(사실)**: 기본 스킬 4개와 역할 에이전트 4개로 **고정**하고 제품 관문 없이 추가하지 않는다. 계획 워크플로는 사용자의 명시적 승인 전까지 실행하지 않으며 지적은 승인 전까지 보류 상태다. 프롬프트는 코드 안에 쓰지 않고 정적 `.md` 파일로 둔다. 검증은 `tsc`를 직접 부르지 않고 `bun run check`로 한다. 역할 에이전트 4개의 이름은 못 찾았다(미확인).

### 12.4 응용 제안: 원형, 우리가 바꾼 점, 남길 증거
각 항목은 "원형을 베끼기"가 아니라 우리 제약(3주·1인, 결정 번호 체계, 평가 사전 고정, 코드 Sensor)에 맞춘 **변형 설계**다.

| # | 원형(출처) | 우리가 바꿀 점(제안) | 포트폴리오에 남길 증거 | 반영 위치 |
|---|---|---|---|---|
| 1 | OMC `deep-interview`의 모호도 점수와 라운드 | 점수를 모델이 매기지 않고 **코드로 셀 수 있는 값**으로 바꾼다: 티켓의 대기 결정 수, 완료 조건 중 "측정 가능"(분자·분모·채점 주체가 있는)으로 표시된 비율. 축은 목표·제약·완료 기준에 **"평가 가능성"**을 더해 RFP 9장과 연결. 질문은 `intent`처럼 번호 묶음으로 받아 우리의 `RFP-22-01~06 권장대로` 답 방식과 맞춘다 | "LLM 판단 점수 → 코드 Sensor로 교체" 한 쌍의 before/after | `requirements-analyst` 지침, `check_schedule.py`에 항목 추가 후보 |
| 2 | `planner`의 "코드베이스 사실은 사용자에게 묻지 않는다" | 우리판: **저장소·RFP·티켓에서 답을 찾을 수 있는 질문은 묻지 않고**, 사용자는 결정 번호가 붙은 선택(A/B/C)만 맡는다. 질문 전에 읽은 곳을 먼저 적게 한다 | 사용자 부담을 줄인 설계 원칙 문서 1단락 | CLAUDE.md 5장 "결정 번호와 소통 방식" 보강 후보 |
| 3 | `analyst`의 출력 절(누락 질문, 미정 가드레일, 범위 위험, 미검증 가정, 누락 완료 기준, 엣지 케이스) | RFP-24 누락 점검 양식과 **절을 맞춘다**. 도메인 절 추가: "금기 조회 실패 시 안전하다고 말하지 않기", "고정 문구 코드 강제", "개인정보 최소 저장" | 도메인 안전 규칙을 점검표에 넣은 근거 | `plan-critic`의 고정 점검 항목 |
| 4 | `critic`의 사전 예측 → 검증 → 자기 점검 → 현실성 점검 | **사전 예측을 RFP-23 §5.1 사전 고정 원칙과 결합**: PRD·평가 설계를 읽기 전에 "이 설계가 깨질 곳 3개"를 기록하고 검토 뒤 맞았는지 비교. 판정은 4단계 대신 3단계(REJECT/REVISE/ACCEPT)로 단순화. 지적 근거는 `파일:줄`, 결정 번호 인용 | 예측 적중 기록 표(작은 표본이라 k/n으로만) | `plan-critic` 정의 |
| 5 | `verifier`의 VERIFIED/PARTIAL/MISSING, "같은 컨텍스트 자기 승인 금지" | **티켓 §2 완료 조건 체크박스마다 증거 열**을 붙이고, 검증은 작성한 pane이 아닌 다른 pane에서 하는 규칙으로 바꾼다(herdr pane 분리와 이미 맞음). 증거는 `check_schedule.py` 출력, 파일 경로, 측정값 | 완료 선언마다 증거 표가 남는 이력 | `done-needs-evidence` 규칙, 티켓 양식 |
| 6 | `tracer`의 경쟁 가설, 증거 위계, 반증 우선, 판별 실험 | **Agent-RAG 실패 분석(AG-12·13)용으로 가설 레인을 재정의**: 검색(리트리벌)·도구 선택(Router)·프롬프트·데이터 갱신(기준일)·**측정(judge·채점기)** 오류. 증거 위계에 "경로 평가(코드 채점)가 judge보다 강한 증거"를 넣는다(RFP-26-05). 개발셋만 열람(RFP-26-04) | 실패 사례별 가설표 1~2건이 있으면 "관찰 → 원인 규명 → 개선 → 수치" 서사를 직접 보임 | AG-12·13 절차 문서, `failure-trace` 스킬(신규 후보) |
| 7 | `minimal-code-discipline`의 보호 경계 | 보호 경계를 우리 목록으로 교체: **금기 판정은 코드, 근거 없는 답변 금지, 고정 문구, 시험셋 열람 금지, `.env` 비열람**. 단순화·정리 작업은 이 목록을 건드리면 중단 | 보호 경계 = Guide-Sensor 매트릭스(RFP-29 §6)와의 대응표 | `simplify` 호출 시 지침, RFP-29 §6 |
| 8 | OMC `Stop` 훅 군(`workflow-drift-guard`, `verify-deliverables`)과 `git-guardrails` | 이름만 보고 하는 **추정**이지만 취지는 "끝내기 전에 코드가 검사"다. 우리판: Claude Code 훅으로 일정·티켓 파일이 바뀐 세션 종료 시 `check_schedule.py`를 돌리고 실패하면 알림. 전부 결정적 스크립트이며 LLM 판단을 쓰지 않는다. `.env` 차단은 기존 `--disallowedTools`를 유지 | Sensor 구현 사례(RFP-29의 Guide/Sensor 구분을 개발 하네스에도 적용) | BE-15(개발 하네스). 훅 사용 여부는 별도 결정 필요 |
| 9 | gajae-code `AGENTS.md`의 "기본 스킬 4개·에이전트 4개 고정, 추가는 관문 필요" | **새 스킬·에이전트를 추가할 때도 결정 번호를 부여**하고 총량 상한(정의 파일 2개 이내, §11.6)을 둔다. 이미 있는 4개 서브에이전트와 겹치면 새로 만들지 않고 기존 정의를 보강 | 하네스 비대화를 막은 판단 기록 | CLAUDE.md 2장 |
| 10 | gajae-code `AGENTS.md`의 "프롬프트는 정적 .md 파일" | 제품 안쪽에 적용: Router·Validator·답변 프롬프트를 코드 문자열이 아니라 **버전 붙은 파일**로 두고, 평가 기록에 프롬프트 파일 해시를 함께 남긴다(judge 루브릭 버전 고정 규칙과 동일 취지) | 프롬프트 버전이 평가 결과와 연결된 재현성 | AG-04·AG-14 설계, RFP-26 §7.5 |
| 11 | gajae-code 스킬 신뢰 스위치(`trustProjectSkills`)와 번들 스킬의 불변성 | 우리판: `.claude/skills/`에 둔 스킬은 **커밋 전 사람이 읽는 것을 규칙으로** 하고(저장소가 신뢰 경계), 외부에서 가져온 문구는 출처 URL·읽은 날짜를 스킬 머리에 적는다 | 공급망 위험을 인지하고 통제한 근거 | 스킬 작성 규칙(RFP-30-02 A 선택 시) |
| 12 | OMC `ultragoal`의 추가 전용 장부 | **신규 도입은 보류.** 우리에겐 `schedule-changelog.md`와 `schedule-done.md`의 종결 기록이 같은 역할이다. 다만 평가 실행 기록(AG-14)은 "측정 시작 후 수정 금지"라서 **추가 전용(append-only) 평가 실행 로그**로 설계하면 사전 고정 원칙을 코드로 지킬 수 있다 | 평가 로그가 수정 불가임을 보인 설계 | AG-14, RFP-23 §5.1 |

### 12.5 11.3 후보의 수정과 RFP-30-02 연결
- 11.3의 5개 후보를 이렇게 조정할 것을 제안한다. 근거는 §12.4의 번호다.
  - `requirements-interview` → **유지, 내용 강화**(#1, #2, #3). 새 파일을 만들기보다 `requirements-analyst` 지침 보강이 먼저다.
  - `plan-critic` → **유지, 사전 예측 방식 추가**(#3, #4, #7).
  - `done-needs-evidence` → **유지, 규칙 1줄에서 티켓 완료 조건의 증거 열로 확대**(#5).
  - `agent-doc-check` → **보류**. `tickets-writer` 정의 보강 3줄이면 충분하다.
  - `harness-matrix-review` → 그대로 보류. 대신 **`failure-trace`(AG-12·13용, #6)를 6번째 후보로 올린다.** 포트폴리오 가치가 가장 크고 "직접 설계한 것"으로 설명하기 좋다. 단, 제품 구현 단계(AG)에서 필요해질 때 쓰는 것이라 지금 만들 필요는 없다.
- RFP-30-02의 선택지 A("질문 정리 스킬 + 계획 점검 스킬(정의 파일 2개) + 증거 규칙 1줄")는 위 조정과 **호환된다**. 다만 A를 고르면 `failure-trace`와 훅(#8)은 포함되지 않으며 각각 AG와 BE-15에서 따로 정한다. 이 단락은 선택지를 바꾸지 않고 참고만 한다. 결정은 사용자가 한다.
- 이 티켓 §6 표의 `gajae-code deep-interview` 행은 "차용(절차만)"으로 적었으나, 근거가 OMC 쪽 SKILL.md이므로 **OMC 기준으로 읽어야 한다**(§12.3). 두 행의 판단이 결과적으로 같은 방향이다.

### 12.6 아직 미확인
- gajae-code 번들 스킬 4개와 역할 에이전트 4개의 프롬프트 본문 위치·내용(소스 트리 `packages/` 하위일 것으로 짐작하나 확인 못 함).
- OMC `deep-interview`의 모호도 점수를 코드가 계산하는지, 모델이 매기는지.
- OMC 훅 스크립트의 실제 동작(파일 읽기 범위, 네트워크 호출, `.env` 접근). 이름만 확인했다.
- OMC 나머지 에이전트 14개(`architect`, `executor`, `code-reviewer`, `security-reviewer`, `test-engineer` 등)와 스킬 약 40개.
- §12.4 항목은 모두 제안이며 시험하지 않았다. 효과가 있는지는 PRD-01 작업에서 써 본 뒤 판단해야 한다.
- 출처: https://github.com/Yeachan-Heo/oh-my-claudecode (`agents/`, `skills/`, `hooks/hooks.json`), https://github.com/Yeachan-Heo/gajae-code (`AGENTS.md`, `docs/skills.md`, `plugins/gajae-code/`, `sdk-skills/`). 조사일 2026-11-04.
