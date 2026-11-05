---
id: RFP-31
label: RFP
title: 다음 주(W1) 작업용 mock 데이터 사전 생성(Anthropic API, 상한 20 USD, 로컬 전용)
sch: SCH-01
status: todo
priority: 권장
rfp: [RFP-9장]
created: 2026-11-04
done: -
---

# RFP-31 · 다음 주(W1) 작업용 mock 데이터 사전 생성

## Index
- [1. 이슈](#1-이슈)
- [2. 완료 조건](#2-완료-조건)
- [3. mock 세트](#3-mock-세트)
- [4. 규칙](#4-규칙)
- [5. 관련](#5-관련)
- [6. 진행 기록 (실시간 갱신)](#6-진행-기록-실시간-갱신)
- [7. 결과 보고](#7-결과-보고)
- [8. 메모](#8-메모)

## 1. 이슈
사용자 요청(2026-11-04): 다음 주 작업에 필요한 데이터의 결과를 **미리 mock으로 만들어 두어** 크레딧을 아낀다. Anthropic API로 생성하고, `mock/` 폴더에 넣고, `.gitignore`로 추적하지 않으며, **mock 생성 API 상한은 20 USD**다. 별도 pane의 서브에이전트가 진행하고 이 티켓에 기록한다.

## 2. 완료 조건
- [ ] `mock/` 폴더가 있고 `.gitignore`에 등록되어 커밋되지 않는다(`git check-ignore mock/README.md`로 확인).
- [ ] 생성 스크립트는 `scripts/mock/`(커밋 대상)에 있고 모든 호출이 `scripts/mock/_common.py`를 거쳐 **누적 20 USD 상한**이 코드로 강제된다.
- [ ] §3의 세트가 만들어졌거나 건너뛴 이유가 §6에 있다. 세트마다 `manifest.json`(생성 모델·프롬프트 해시·비용·개수)이 있다.
- [ ] 누적 사용액이 §7에 있고 20 USD를 넘지 않았다(원장 `mock/ledger.json`과 콘솔 값을 같이 적는다).
- [ ] 값(등급·성분코드·기준일·제품명)은 파일·API 확인 결과에서 **코드가 가져온 것**이고 LLM은 문장만 썼음을 확인했다(검증 스크립트 결과).

## 3. mock 세트
| 세트 | 내용 | 쓰는 W1 티켓 | 모델 | 어림 비용(제 추정) |
|---|---|---|---|---|
| M1 `chat_responses/` | **`/chat` 응답 fixture**: PRD 15.3 시나리오 S1~S8의 응답(`summary`·`detail`·`citations[]`·`fixed_notice`·`emergency`·`disclaimer`·`route`)과 스트리밍 이벤트 순서(응급이면 `emergency` 첫 이벤트, 진행 상태 이벤트). 값은 RFP-21 §4의 실제 값과 `data/` 파일에서 코드가 가져오고, 쉬운 요약 문장만 LLM | BE-06, FE-01, FE-02 | Haiku 4.5 (요약 품질이 부족하면 Sonnet 5.5 일부) | $1~3 |
| M2 `traces/` | **에이전트 경로(trace) fixture**: 기대 경로 스키마(필수·권장·금지 도구, 순서, 호출 상한)와 정상·판정 도구 생략·금지 도구 호출·호출 상한 초과·인용 청크 ID 환각 등 Pass/Warn/Fail 사례. 대부분 코드로 생성 | BE-08 경로 채점기, AG-01 | 거의 없음(코드) | $0~1 |
| M3 `judge_outputs/` | **judge 출력 fixture**: J1·J3·J4·J5 구조화 JSON(`items`·`reason`·`overall_pass`)과 형식 오류·재시도 사례. RFP-28 사전 시험 결과(`data/credit_use/judge_dryrun.jsonl`)를 가공하고 부족한 칸만 생성 | BE-08 judge 실행기 | Sonnet 5.5(사고 끔) | $1~3 |
| M4 `question_templates/` | **질문 틀 확장**: 모호·근거 없음·범위 외(복용 중단·의료진 우회)·오정보 등 AG-04 후보 틀(자리 표시 `{약A}`). 제품명은 BE-10 뒤 코드가 채움. 오탈자·축약·표기 변형은 `scripts/credit_use/variants.py`가 코드로 만든다 | AG-04 | Haiku 4.5 | $1~2 |
| M5 `validator_pairs/` | **Validator 입력쌍**: (증거 묶음, 답변, 기대 판정) — 근거에 없는 주장·등급 틀림·안전 단정·복용 중단 지시·의료진 우회 문장 등 차단·수정되어야 하는 사례와 통과 사례 | AG-07 테스트 | Haiku 4.5 | $1~2 |
| 합계 | | | | **약 $4~11(상한 $20)** |

## 4. 규칙
- **상한 20 USD는 코드가 강제**한다(`scripts/mock/_common.py`, 원장 `mock/ledger.json`). 호출 전에 누적 + 예상 최대 비용이 20을 넘으면 중단한다. 에이전트는 상한을 올리거나 우회하지 않는다.
- **로컬 전용**: `mock/`는 커밋하지 않는다. 스크립트(`scripts/mock/`)와 이 티켓은 커밋한다.
- **합성·가상 데이터**만 만든다. 질문·답변 속 사람은 가상 인물이고, 값은 파일·API 확인 결과에서 가져온다. LLM이 등급·성분코드·고시번호·기준일을 새로 만들지 않는다(검증 스크립트로 확인).
- 모든 mock 레코드에 `"mock": true`와 생성 모델·세트 버전을 남긴다.
- 키는 환경변수(`ANTHROPIC_API_KEY`)로만 읽고 값은 기록하지 않는다.
- 평가 시험셋 후보(`data/credit_use/pool_test.jsonl`)는 열람·수정하지 않는다(개선 중 열람 금지, RFP-26-04).

## 5. 관련
- 선행: 없음
- 관련: RFP-28(사전 시험·예산 모듈), RFP-26(judge 루브릭), PRD-07 15장(시나리오), BE-06·FE-01·FE-02·BE-08·AG-01·AG-04·AG-07
- 관련 문서: `P2-doc/PJ2-PRD.md` 15장, `tickets/doc/RFP-21.md` §4, `tickets/doc/RFP-26.md` §7.5·§7.6

## 6. 진행 기록 (실시간 갱신)
- 2026-11-04 · 티켓 작성, `mock/`·`scripts/mock/_common.py`(상한 20 USD) 준비. 별도 pane의 서브에이전트가 시작한다.

## 7. 결과 보고
(작업이 끝나면 세트별 개수·비용·검증 결과를 적는다.)

## 8. 메모
- 사용자 지정: 상한 20 USD, `/mock` 폴더, `.gitignore` 등록(2026-11-04).
- 이 mock은 **W1 개발·테스트용**이며 평가 측정(AG-11·12·14)의 결과 값으로 쓰지 않는다. 측정은 실제 에이전트·judge 호출로 한다.
