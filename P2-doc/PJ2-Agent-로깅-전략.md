# Can I PPiyak(MediAgent) 에이전트 로깅·병목 대응 전략

**LOGGING STRATEGY: 에이전트 로깅·병목 대응 전략**

- 작성일: 2026-11-06 (Pre-Week, 코드 전 설계 문서)
- 담당 티켓: [`tickets/doc/RFP-34.md`](../tickets/doc/RFP-34.md) (결정 RFP-34-01~05)
- 근거 문서: `CLAUDE.md` 1·3·4·5장, `tickets/doc/RFP-22.md`(§6 도구, §8, §14.2, RFP-22-05·06), `tickets/doc/RFP-23.md`(§4 노드·상태, §5 평가), `tickets/doc/RFP-26.md`(§7.6 경로, §7.7 신뢰성), `tickets/doc/RFP-29.md`(§4.3 개발 하네스, §6 H13·H16), `tickets/doc/RFP-32.md`(LLM 캐시), `tickets/doc/PRD-07.md`(PRD-07-01·02), `tickets/doc/PRD-08.md`(PRD-08-04, 읽기만), `P2-doc/PJ2-RFP.md` 7·9·12장, `P2-doc/PJ2-PRD.md` 6.2절(NFR), `tickets/backend/BE-01.md`, `tickets/backend/BE-08.md`, `evaluation/mock_gen/llm_cache.py`, `evaluation/mock_gen/_common.py`
- 상태: **확정(결정 RFP-34-01~05 모두 A, 2026-11-06 사용자 "권장대로")**, 코드 없음. 구현은 새 티켓 없이 기존 티켓 완료 조건으로 나눴다(9장: L1·L5 → BE-15, L2 → AG-01, L3 → BE-08·AG-16, L4 → BE-06). 아래 "제안" 표기는 작성 당시 그대로 두며, 8장 결정 범위 안의 제안은 확정으로 읽는다.
- 표기: **사실**(문서·코드에서 확인), **제안**(이 문서의 설계안, 결정 전), **측정 전·확인 못 함**(값이 없음). 모든 수치 목표는 측정 전이며 비워 둔다.
- 하네스 문서(`P2-doc/PJ2-Agent-Harness.md`, RFP-33)는 이 문서를 쓰는 시점(2026-11-06)에 아직 없었다. 겹치는 하네스 제안은 "RFP-33 참고"로 연결만 하고, 규칙 ID는 기존 RFP-29 §6(H1~H16)을 쓴다. RFP-33 결정(2026-11-06) 뒤 RFP-29 §6에 H17~H21이 더해졌고, 하네스 동작 어휘 `warn`·`flag`는 PJ2-Agent-Harness.md 3.6절을 따른다.

## Index
- [1. 한눈에 보기](#1-한눈에-보기)
- [2. 무엇을 볼 것인가](#2-무엇을-볼-것인가)
- [3. 로그 레벨과 실행 모드](#3-로그-레벨과-실행-모드)
- [4. 스키마와 마스킹·보관](#4-스키마와-마스킹보관)
- [5. 도구 선택 비교](#5-도구-선택-비교)
- [6. 로그로 답할 질문과 평가 지표 연결](#6-로그로-답할-질문과-평가-지표-연결)
- [7. 병목 대응 전략(플레이북)](#7-병목-대응-전략플레이북)
- [8. 결정사항](#8-결정사항)
- [9. 구현 티켓 생성안](#9-구현-티켓-생성안)
- [10. 확인하지 못한 것과 출처](#10-확인하지-못한-것과-출처)

## 1. 한눈에 보기

### (1) 왜 로그가 필요한가
- **에이전트는 경로가 비결정적이다.** 같은 질문에도 `model`이 고르는 도구 순서·횟수가 달라진다(PJ2-RFP.md 12장 "에이전트 경로 비결정성" 행). 최종 답만 보면 "판정 도구를 건너뛰고 우연히 맞힌 답"과 "제대로 맞힌 답"을 구분할 수 없다(RFP-26 §7.6).
- **하네스가 실제로 막았는지 확인해야 한다.** `guardrail_in`·호출 상한 8·되돌림 2·Validator·`finalize`(RFP-23 §4.2, RFP-29 §6)가 "설계됨"이라는 것은 문서 상태이고 동작이 아니다(RFP-29 §9). 차단 사유가 로그에 남아야 "어느 규칙(H?)이 몇 번 막았는가"를 셀 수 있다.
- **개선은 실패 기록에서 시작한다.** "실패 1개당 하네스 부품 1개"(RFP-22 §4 14번)와 실패 기록 양식(RFP-29 §7.3)은 경로 기록이 있어야 채울 수 있다.
- **비용이 빠듯하다.** OpenAI 보유 크레딧 $8에 본 측정 어림이 약 $4.8이다(PJ2-RFP.md 9.7절, 2026-11-07 4조건 재계산, 제 추정·측정 전). 어디서 토큰이 새는지 로그 없이 알 수 없다.

### (2) 이 문서의 결론(제안)
| 항목 | 제안 | 결정 |
|---|---|---|
| 기본 단위 | **한 요청 = 한 trace**, 노드·도구·모델 호출마다 **span** 한 줄(JSONL) | 설계 |
| 모드 | `dev` / `eval` / `service` 세 모드. **기본값은 가장 엄격한 `service`** | 설계 |
| 서비스 모드 | 질문 원문·해시·약 이름·프로필을 남기지 않고 **내용 없는 지표만** | RFP-34-01 |
| 도구 | **로컬 JSONL + LangGraph 콜백/스트림**, 필드 이름은 OpenTelemetry GenAI 규약에 맞춤. 외부 SaaS는 쓰지 않음 | RFP-34-02 |
| 저장·보관 | 로컬 `logs/`(git 제외), 개발 14일, 평가는 실행 결과와 함께 프로젝트 종료까지 | RFP-34-03 |
| 병목 수정 | "측정 → 가설 → 한 번에 하나 → 재측정", 측정 기간 중 평가 조건 동결 | RFP-34-04 |
| 개발 비용 | 개발·디버깅용 OpenAI 누적 상한을 원장으로 코드 강제 | RFP-34-05 |

### (3) 원칙과의 충돌 점검(요약)
| 원칙 | 출처 | 이 전략의 처리 |
|---|---|---|
| 질문·대화 내용을 저장·로그하지 않는다 | NFR-04, PJ2-RFP.md 7장, CLAUDE.md 1장 | 서비스 모드에서는 내용 필드를 **코드가 버린다**(쓰기 전 화이트리스트). 충돌 없음 |
| trace는 합성 평가 질문에만 | RFP-22-06 A | 전체 trace는 `eval`(합성 평가 세트)과 `dev`(개발자가 넣는 합성·가상 입력, 로컬)에서만. `service`는 trace 없음 |
| 서비스 모드에서도 내용 없는 지표를 남길지 | RFP-22 §14.2 "구현 때 정할 것" | **결정으로 올림**: RFP-34-01 |
| 외부 AI 전송·보관 고지 | NFR-05, PRD-07-02 | 외부 추적 SaaS를 쓰지 않아 전송 대상이 늘지 않음. 쓰게 되면 합성 질문에만(RFP-34-02 B) |
| 비밀값을 코드·로그·응답에 남기지 않는다 | CLAUDE.md 3장 | 쓰기 전 비밀 패턴 마스킹 + 저장소 커밋 차단 + 테스트(§4 (3)) |
| 사진·음성 미저장 방향 | PRD-08-04 A(2026-11-06, 저장하지 않음) | 사진·음성 바이트와 변환 원문은 어느 모드에서도 로그하지 않는다 |
| 평가 재현성·캐시 | RFP-32-02 A, `MEDIAGENT_EVAL=1` | `eval` 모드 = `MEDIAGENT_EVAL=1` = 캐시 off. 평가 trace에 캐시 적중이 하나라도 있으면 실행 무효(§4 (4)) |
| judge 모델·루브릭 고정 | RFP-26-01, H16 | judge span에 모델 ID·루브릭 버전을 남기고 BE-08의 불일치 거부와 같은 값 사용 |

## 2. 무엇을 볼 것인가

### (1) 한 요청의 흐름과 trace의 모양
6노드 그래프(RFP-23 §4.2·§4.5, RFP-23-01 A)를 그대로 span 계층으로 옮긴다.

```
trace (요청 1건, trace_id)
├─ span node=guardrail_in      → harness_event(응급 표시·범위 외 거절)
├─ span node=router            → 모델 호출 1회(구조화 출력), route·intent
├─ span node=model   (step 1)  → 모델 호출, tool_calls 요약
├─ span node=tools   (step 1)
│   ├─ span tool=identify_drug        → 후보 수, 품목기준코드
│   └─ span tool=identify_drug        (병렬이면 같은 step)
├─ span node=model   (step 2)
├─ span node=tools   (step 2)
│   └─ span tool=check_contraindications → 판정 결과 요약, 파일·API 일치
├─ …  (steps ≤ 8, 되돌림 ≤ 2)
├─ span node=validator         → verdict, 위반 규칙 ID
└─ span node=finalize          → 고정 문구·119·기준일 부착 여부, 종료 사유
```

- 도구 6개(`identify_drug`, `check_contraindications`, `search_notice`, `search_reason`, `search_label`, `get_label_section`, RFP-22 §6)는 `tools` 노드 span의 **자식 span**으로 각각 남긴다. 단일 `ToolNode`에 6개를 등록해도(RFP-23 §4.3) 도구별 지연·실패를 따로 볼 수 있어야 하기 때문이다.
- 고정 파이프라인(C1·C1+, AG-16)도 같은 스키마로 남긴다. 그래야 경로 채점기(BE-08)와 비교 표(RFP-23 §5.7)가 조건과 상관없이 같은 코드로 돈다.

### (2) span마다 남기는 것
| 범주 | 항목 | 왜 | 비고 |
|---|---|---|---|
| 식별 | `trace_id`, `span_id`, `parent_id`, `node`, `tool`, `step` | 경로 재구성 | `step`은 `model` 호출 순번(상태 `steps`, RFP-23 §4.4) |
| 입력 요약 | 원문이 아닌 **요약**: 인자 이름·개수, 성분코드·품목기준코드 목록, 질문 길이 | 무엇을 넣었나 | 원문은 `eval`·`dev`에서만 별도 필드(§3) |
| 출력 요약 | 결과 건수, `evidence_ids`(청크 ID), 판정 요약(해당/목록에 없음·등급), 오류 코드 | 무엇을 받았나 | 도구 결과 원문은 남기지 않고 청크 ID로 다시 찾는다 |
| 지연 | `latency_ms`, 시작·끝 시각 | 병목 | 단조 시계로 잰다 |
| 토큰·비용 | `tokens_in`, `tokens_out`, `tokens_cached`, `cost_usd` | 비용 병목 | 단가는 PJ2-RFP.md 9.7절 값(측정 전 재확인) |
| 재시도 | `retry`, `error_type` | 공공 API·LLM 실패 | 형식 오류 재시도 포함 |
| 상한 | `model_calls_so_far`(상한 8), `rollbacks_so_far`(상한 2) | NFR-10, H12 | RFP-22-05 |
| 캐시 | `cache`(`off`/`hit`/`miss`/`stored`), `cache_key12` | 평가 오염 방지 | `llm_cache.py`의 키 앞 12자 |
| 하네스 | `harness_event`(규칙 ID H1~H16 + 동작: block/rewrite/rollback/append) | 하네스가 막았나 | RFP-29 §6. 새 하네스 이벤트 이름은 RFP-33 참고 |
| 검증 | `verdict`(pass/fix/fail), `violations`(규칙 ID 목록) | Validator 효과 | AG-07 |
| 데이터 | `source`(file/api/snapshot), `file_api_match`(일치/불일치/API 끔), `data_as_of`(기준일 2026-07-21 등) | 근거·기준일 | 일치율은 평가 점수와 섞지 않는다(BE-08) |
| 종료 | `end_reason`(정상/호출 상한/안내 전환/거절/오류) | 경로 평가 지표 | RFP-26 §7.6 "종료 사유" |

### (3) trace 머리(요청 단위)에 남기는 것
`mode`, `run_id`(평가 실행), `item_id`(평가 문항 ID), `condition`(C0~C3), `repeat_idx`(`pass^3`용 1~3, 1은 본 측정 결과를 재사용, RFP-35-09 A), `branch_type`(분기 유형 라벨, 문항에서 복사), `model`, `prompt_version`(`prompts/*@v1`, RFP-29 §7.2 6번), `tool_schema_version`, `graph_version`(git 커밋 앞 7자), `api_enabled`, `data_as_of`, `total_latency_ms`, `total_cost_usd`, `end_reason`.

## 3. 로그 레벨과 실행 모드

### (1) 모드 정하기(제안)
- 환경변수 `MEDIAGENT_MODE=dev|eval|service`. **값이 없거나 틀리면 `service`**(가장 엄격한 쪽이 기본값).
- `eval`은 평가 스크립트(BE-08)만 켠다. 이때 `MEDIAGENT_EVAL=1`도 함께 켜서 `llm_cache.py`가 캐시를 끄게 한다(RFP-32 §9.4). 둘이 어긋나면(예: `eval`인데 `MEDIAGENT_EVAL`이 없음) 시작하지 않는다.
- `service`에서는 trace 코드가 **아예 돌지 않는다**(RFP-22 §14.2의 "trace 코드가 아예 돌지 않도록"). 남는 것은 (2)의 내용 없는 지표뿐이다(RFP-34-01).

### (2) 모드별로 남기는 것과 남기지 않는 것
| 항목 | `dev` (로컬 개발) | `eval` (합성 평가 세트) | `service` (실제 사용, 배포) |
|---|---|---|---|
| 입력 출처 | 개발자가 넣는 합성·가상 질문, mock(`data/mock/`), 스냅샷 | AG-04 개발셋·시험셋(합성) | 실제 사용자 |
| 질문 원문 | 로컬 파일에만 남김(`input_text`, 합성임을 `input_source`로 표시) | 남김(문항 파일에 이미 있는 합성 문장) | **남기지 않음** |
| 질문 해시 | 남김 | 남김(문항 ID로 충분) | **남기지 않음**(짧은 질문은 사전 대입으로 되돌릴 수 있다) |
| 약 이름·성분코드·프로필 | 남김 | 남김 | **남기지 않음**(약 이름 + 임신 여부는 건강 정보) |
| 모델 출력 원문 | 남김 | 남김(judge·경로 채점 입력) | **남기지 않음** |
| 도구 결과 | 요약 + 청크 ID | 요약 + 청크 ID | 남기지 않음 |
| 노드·도구 이름, 지연, 토큰, 비용 | 남김 | 남김 | **집계값만**(요청별 행 대신 분 단위 합계, RFP-34-01 A) |
| 하네스 이벤트·종료 사유 | 남김 | 남김 | **건수만**(규칙 ID별 카운트) |
| 오류 | 스택 포함 | 스택 포함 | 오류 유형·건수만(메시지에 입력이 섞일 수 있어 메시지는 버림) |
| 비밀값 | 마스킹 | 마스킹 | 마스킹 |
| 사진·음성(PRD-08) | 남기지 않음 | 해당 없음(평가는 텍스트) | 남기지 않음 |
| 저장 위치 | 로컬 `logs/dev/` | 로컬 `logs/eval/<run_id>/` | 서버 표준 출력(호스트 로그) |
| 외부 전송 | 없음 | 없음(RFP-34-02 A) | 없음 |

### (3) 로그 레벨
| 레벨 | 쓰임 | 모드 |
|---|---|---|
| `TRACE` | span 전체(입출력 요약·원문 필드) | `dev`·`eval`만 |
| `INFO` | 요청 시작·끝, 종료 사유, 집계 지표 | 세 모드(서비스는 집계만) |
| `WARN` | 상한 도달, 되돌림, Validator 수정, 파일·API 불일치, 캐시 미스(replay) | 세 모드(서비스는 건수만) |
| `ERROR` | 도구·LLM 실패, 스키마 위반, 마스킹 실패 | 세 모드(서비스는 유형만) |

## 4. 스키마와 마스킹·보관

### (1) span 레코드 예시(JSONL 한 줄, `eval` 모드)
값은 가상 예시이며 측정값이 아니다.

```json
{"schema": "mediagent.span@v1", "mode": "eval", "run_id": "2026-11-20T10-00_C2_dev",
 "trace_id": "t-7f3a…", "span_id": "s-0005", "parent_id": "s-0004",
 "item_id": "DEV-NORM-PG-003", "condition": "C2", "repeat_idx": 1, "branch_type": "정상-임부",
 "node": "tools", "tool": "check_contraindications", "step": 2,
 "input_summary": {"ingr_codes": ["D000147", "D000448"], "profile": {"pregnant": true}},
 "output_summary": {"hits": 1, "grades": ["2"], "evidence_ids": ["L2:preg:D000448"]},
 "source": "file", "file_api_match": "API 끔", "data_as_of": "2026-07-21",
 "latency_ms": null, "tokens_in": null, "tokens_out": null, "cost_usd": null,
 "model": null, "cache": null, "retry": 0,
 "model_calls_so_far": 2, "rollbacks_so_far": 0,
 "harness_event": null, "verdict": null, "end_reason": null,
 "prompt_version": "agent_system@v1", "graph_version": "a1b2c3d"}
```

### (2) 필드 정의
| 필드 | 타입 | 필수 | 뜻 | OpenTelemetry GenAI 대응(참고) |
|---|---|---|---|---|
| `schema` | str | 예 | 스키마 버전(`mediagent.span@v1`). 바꾸면 버전을 올린다 | - |
| `mode` | enum | 예 | `dev`/`eval` (service는 span 없음) | - |
| `run_id` | str | eval | 평가 실행 ID(BE-08 결과 파일 이름과 같음) | - |
| `trace_id`, `span_id`, `parent_id` | str | 예 | 계층 | trace/span id |
| `item_id`, `condition`, `repeat_idx`, `branch_type` | str/int | eval | 문항·조건·반복·분기 유형 | - |
| `node` | enum | 예 | 6노드 중 하나(C1은 같은 이름의 단계) | `gen_ai.operation.name`(모델 호출일 때) |
| `tool` | enum/null | - | 도구 6개 중 하나 | `gen_ai.tool.name` |
| `step` | int | 예 | `model` 호출 순번 | - |
| `route`, `intent` | str | router | 정상/거절/안내 전환, 의도 라벨 | - |
| `input_summary`, `output_summary` | obj | 예 | 원문이 아닌 요약(§3 (2)) | - |
| `input_text`, `output_text` | str | dev·eval | 원문(합성 입력만) | `gen_ai.input.messages`, `gen_ai.output.messages` |
| `evidence_ids` | list[str] | 도구·답 | 청크 ID | - |
| `latency_ms` | int | 예 | 지연 | span 길이 |
| `tokens_in`, `tokens_out`, `tokens_cached` | int | 모델 | 토큰 | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens` |
| `cost_usd` | float | 모델 | 단가 × 토큰(로컬 계산) | - |
| `model` | str | 모델 | 모델 ID(`gpt-6-luna`, judge `claude-sonnet-5-5`) | `gen_ai.request.model` |
| `provider` | str | 모델 | `openai`/`anthropic`/`upstage` | `gen_ai.provider.name` |
| `cache`, `cache_key12` | enum/str | 모델 | 캐시 상태 | - |
| `retry`, `error_type` | int/str | 예 | 재시도·오류 | `error.type` |
| `model_calls_so_far`, `rollbacks_so_far` | int | 예 | 상한 카운터 | - |
| `harness_event` | obj/null | - | `{"rule": "H4", "action": "append", "detail": "119 최상단"}` | - |
| `verdict`, `violations` | str/list | validator | 검증 결과 | - |
| `source`, `file_api_match`, `data_as_of` | str | 도구 | 데이터 출처·일치·기준일 | - |
| `end_reason` | enum | finalize | 종료 사유 | - |
| `prompt_version`, `tool_schema_version`, `graph_version` | str | 예 | 버전(재현성) | - |

- 필드 이름을 OpenTelemetry GenAI 규약과 일대일로 맞추지는 않는다(규약이 개발 중 단계라 바뀔 수 있다). **대응표만 두고**, 나중에 OTel로 옮길 때 변환 함수 하나로 끝나게 한다.

### (3) 비밀·개인정보 마스킹 규칙
1. **화이트리스트 쓰기**: 로거는 §4 (2)의 필드만 받는다. 모르는 필드는 버리고 `WARN`을 남긴다(새 필드가 조용히 원문을 싣는 것을 막는다).
2. **모드 필터**: `service`에서는 `input_text`·`output_text`·`input_summary`·`output_summary`·`evidence_ids`·`error` 메시지를 쓰기 전에 버린다. 필터는 로거 안의 한 함수이고 단위 테스트로 고정한다(H13, RFP-29 §6).
3. **비밀 패턴 마스킹**(모든 모드): 환경변수 값(이름이 `_KEY`·`_SECRET`·`_DB_URL`로 끝나는 것)과 `sk-`·`serviceKey=`·`postgres://`·JWT 패턴을 `***`로 바꾼다. RFP-32 §9.6의 검색 패턴과 같다. 공공 API 요청 URL은 `serviceKey`를 지운 뒤 남긴다(RFP-32 §5).
4. **마스킹 실패는 쓰지 않는다**: 마스킹 함수가 예외를 내면 그 줄을 버리고 `ERROR`(유형만)를 남긴다.
5. **커밋 차단**: `logs/`를 `.gitignore`에 넣고, pre-commit 비밀 검사(BE-15, RFP-29-01 A)가 `logs/`를 다시 한 번 막는다.

### (4) 캐시와 로그의 정합(RFP-32)
- 모델 호출 span의 `cache`는 `llm_cache.py`의 결과를 그대로 적는다: `off`(캐시 안 씀), `hit`(저장본, 비용 0), `miss`→`stored`(record에서 호출 후 저장), `replay`에서 미스면 `error_type=CacheMiss`.
- 캐시 적중 span의 `latency_ms`·`cost_usd`는 **실제 호출의 값이 아니다.** 지연·비용 집계에서 `cache != "off"`인 span은 따로 센다(섞으면 지연이 실제보다 작게 보인다).
- **평가 오염 검사(제안, Sensor)**: `eval` 실행 결과의 모델 span 가운데 `cache != "off"`가 하나라도 있으면 그 실행을 무효로 표시한다. BE-08의 H16 검사(모델 ID·루브릭 버전·세트 해시)와 같은 자리에서 돈다.
- 실제 호출 비용 원장은 지금처럼 `_common.call()`(Anthropic, `data/mock/ledger.json`)이 맡고, OpenAI도 같은 구조의 원장을 둔다(RFP-34-05). 로그의 `cost_usd` 합과 원장 증가분을 실행마다 대조해 어긋나면 `WARN`.

### (5) 보관 기간과 위치(RFP-34-03 A 기준)
| 종류 | 위치 | 보관 | 커밋 |
|---|---|---|---|
| 개발 trace | `logs/dev/YYYY-MM-DD.jsonl` | 14일 뒤 삭제(시작 시 정리) | 안 함 |
| 평가 trace | `logs/eval/<run_id>/spans.jsonl` + BE-08 결과 파일 | 프로젝트 종료(발표)까지, 이후 사용자 판단 | 안 함(요약 수치만 리포트·문서) |
| 서비스 지표 | 서버 표준 출력, 분 단위 집계 | 호스트 기본 보관(확인 못 함), 앱에서 따로 저장하지 않음 | 해당 없음 |
| 비용 원장 | `data/mock/ledger.json`(Anthropic), OpenAI 원장(신규) | 프로젝트 종료까지 | 안 함 |

- 평가 trace에는 시험셋 문항이 들어 있다. **개선 중에는 시험셋 trace를 열람하지 않는다**(RFP-26-04, PJ2-RFP.md 9.1절 8번). 요약 스크립트는 기본으로 개발셋만 읽고, 시험셋은 플래그와 기록을 남길 때만 연다.

## 5. 도구 선택 비교

### (1) 후보
| 후보 | 무엇 | 장점 | 단점 | 질문 전송·저장 | 1인·3주·무료 적합 |
|---|---|---|---|---|---|
| A. 로컬 JSONL + LangGraph 콜백/스트림 | LangGraph `stream_mode`(`updates`·`debug`)·LangChain 콜백으로 노드·모델·도구 이벤트를 받아 JSONL로 씀 | 설치 없음, 경로 채점기(BE-08)·mock trace(`data/mock/traces/`)와 같은 파일 형식으로 바로 이어짐, 모드 필터를 우리 코드가 강제 | 화면(시각화)이 없음, 집계 스크립트를 직접 씀 | 없음(로컬) | **높음** |
| B. 로컬 SQLite | A의 레코드를 SQLite 테이블에 | SQL 집계가 쉬움 | 스키마 변경마다 마이그레이션, 동시 쓰기 주의 | 없음 | 중간(A + 요약 때 적재로 충분) |
| C. OpenTelemetry SDK + 로컬 수집기 | OTel span을 로컬 파일·Jaeger 등으로 | 표준 규약, 나중에 어떤 백엔드로도 이동 | GenAI 규약이 개발 중 단계, 수집기·뷰어 설치와 학습 시간 | 로컬이면 없음 | 낮음~중간(3주 안에 이득 작음) |
| D. Langfuse 셀프호스트(Docker) | 오픈소스(MIT) 추적 서버를 로컬에서 | 화면·평가·프롬프트 관리, 사용량 제한 없음 | Docker 구성 유지, 서버 하나가 더 생김 | 로컬이면 없음 | 중간(시각화가 꼭 필요할 때) |
| E. Langfuse 클라우드(Hobby) | 무료 50k 단위/월, 30일, 사용자 2명 | 설치 없음, 화면 | 질문이 외부로 전송·보관됨 | **있음** | 합성 평가 질문에만이면 가능 |
| F. LangSmith 클라우드(Developer) | 무료 5k base trace/월, 14일, 1석 | LangGraph와 연결이 가장 쉬움 | 질문 외부 전송, 무료 한도가 평가 규모(실행 약 1,370회 × span 여럿, PJ2-RFP.md 9.7절)에 빠듯할 수 있음(trace 단위 계산 방식 확인 못 함) | **있음** | 합성 평가 질문에만이면 가능 |

- 가격·한도는 §10 출처의 2026-11-06 조회 값이다. 약관(데이터 처리·학습 여부·지역 기본값)은 **확인 못 함**.

### (2) 권장안과 대안
- **권장(RFP-34-02 A)**: **A(로컬 JSONL + LangGraph 콜백/스트림)**. 필드 이름에 OTel 대응표를 두어(§4 (2)) C로 옮길 길을 열어 둔다. 집계는 표준 라이브러리 또는 pandas로 하고, 필요하면 요약 때만 B(SQLite)로 적재한다.
  - 이유: ① 경로 채점기·신뢰성 집계기(BE-08)가 trace를 **파일로 직접** 읽어야 한다. ② 서비스 모드 필터를 우리 코드가 강제해야 H13의 Sensor가 된다(외부 SDK는 기본으로 입력을 싣는다). ③ 외부 전송 고지(NFR-05) 범위를 늘리지 않는다. ④ 설치·계정이 없다.
- **대안(RFP-34-02 B)**: 화면이 꼭 필요해지면 **합성 평가 질문 실행(`eval`)에만** D(Langfuse 셀프호스트)를 병행한다. E·F(클라우드)는 합성 질문만 보낸다는 조건에서 가능하지만 약관을 확인하기 전에는 쓰지 않는다.
- **하지 않을 것**: 서비스 모드에서 어떤 외부 추적 도구도 켜지 않는다(RFP-22-06 A).

### (3) LangGraph에서 받는 방법(설계 의견, 구현 때 확인)
- 노드 단위: `graph.stream(..., stream_mode=["updates", "debug"])`로 노드 이름·상태 변화를 받는다. `debug`는 상태 전체를 싣기 때문에 **로거에 넘기기 전에 요약**한다(원문이 섞인다).
- 모델·도구 단위: LangChain 콜백 핸들러(`on_chat_model_start/end`, `on_tool_start/end`)에서 토큰·지연·도구 이름을 받는다. 비동기 호출은 `RunnableConfig`를 명시적으로 넘겨야 콜백이 전파된다(LangGraph 문서). 
- 하네스 이벤트: `guardrail_in`·`validator`·`finalize`는 우리 코드라 이벤트를 직접 쓴다(콜백에 의존하지 않음).
- `gpt-6-luna` 응답의 토큰 사용량 필드 이름과 병렬 도구 호출 표시 방식은 **확인 못 함**(BE-15 호출 확인 스크립트에서 확인).

## 6. 로그로 답할 질문과 평가 지표 연결

### (1) 질문 목록
| # | 로그로 답할 질문 | 먼저 볼 필드 | 연결 지표(정의는 바꾸지 않음) |
|---|---|---|---|
| Q1 | 어떤 문항에서 필수 도구를 안 불렀나(판정 도구 생략)? | `tool`, `item_id`, 문항의 기대 경로 | 경로 평가 필수 도구 호출률·판정 도구 생략(RFP-26 §7.6, 9.4절) |
| Q2 | 금지 도구를 불렀나, 순서를 어겼나? | `tool`, `step` | 금지 도구 호출 수·순서 위반 수 |
| Q3 | 같은 도구·같은 인자를 반복했나? | `tool`, `input_summary` | 불필요·중복 호출률(Warn) |
| Q4 | 호출 상한 8·되돌림 2에 걸렸나, 몇 번째 step에서? | `model_calls_so_far`, `rollbacks_so_far`, `end_reason` | 종료 사유 분포, NFR-10 |
| Q5 | 답이 인용한 청크 ID가 도구가 돌려준 ID 안에 있나? | `evidence_ids`(도구) vs 답의 인용 | 인용 청크 ID 검증(환각 인용) |
| Q6 | 응급 문항에서 119가 LLM 호출 **전에** 표시되었나? | `guardrail_in`의 `harness_event` 시각 vs 첫 모델 span 시각 | 안전 응답률(119), NFR-06 |
| Q7 | 성분명만 있는 입력·인젝션 입력에서 하네스가 막았나? | `harness_event.rule`, `route` | 안전 응답률(거절), H8. 성분명 입력 처리 규칙은 RFP-33 참고 |
| Q8 | Validator가 무엇을 몇 번 고쳤나/막았나? | `verdict`, `violations` | 안전 응답률, 실패 기록 양식(RFP-29 §7.3) |
| Q9 | 3회 반복에서 경로·판정이 흔들린 문항은? | `repeat_idx`, `tool` 집합, 판정 요약 | `pass^3`·`pass@3`·불안정 문항·판정 일치율·경로 일관성(RFP-26 §7.7) |
| Q10 | 지연의 대부분은 어디서 생기나(모델/도구/공공 API)? | `latency_ms`를 `node`·`tool`별로 합산 | 비용 보조 지표(지연) |
| Q11 | 토큰은 어디서 새나(프롬프트·도구 결과 누적)? | `tokens_in`을 `step`별로 | 비용 보조 지표(토큰) |
| Q12 | 파일과 API 판정이 다른 경우는? | `file_api_match` | 별도 관찰값(평가 점수와 섞지 않음, BE-08) |
| Q13 | 평가 실행에 캐시가 섞였나? | `cache` | 재현성(H16), RFP-32-02 |
| Q14 | C1과 C2의 호출 수·지연 차이는? | `condition`, `model_calls_so_far`, `total_latency_ms` | 결과 표 틀의 평균 호출 수(RFP-23 §5.7), 가설 H-E2 |

### (2) 지표와의 관계
- 로그는 지표를 **계산하는 입력**이고 지표의 정의·목표는 PJ2-RFP.md 9장이 원본이다(CLAUDE.md 5장). 이 문서는 정의를 바꾸지 않는다.
- 경로·신뢰성 지표는 judge 없이 코드가 이 로그에서 계산한다(RFP-26-05·06). 그래서 `eval` trace의 필드가 빠지면 지표를 계산할 수 없다: **필수 필드 누락은 실행 실패로 본다**(BE-08 경로 채점기의 입력 검사).
- 원인 사례 2건 이상을 붙이는 규칙(RFP-23 §5.6 3번, 9.1절)은 `item_id`로 trace를 찾아 붙인다. 시험셋 사례는 최종 보고 때만 연다.

## 7. 병목 대응 전략(플레이북)

### (1) 절차: 측정 → 가설 → 한 번에 하나 → 재측정
1. **측정**: 같은 입력 묶음(개발셋 부분집합, 예: 분기 유형별 몇 문항씩. 크기는 RFP-34-04에서 고정)으로 기준값을 잰다. 지연·비용은 **캐시 off**로 잰다.
2. **가설**: "병목은 X이고 Y를 바꾸면 Z가 줄어든다"를 한 문장으로 적는다. 로그의 어떤 필드로 확인할지 함께 적는다.
3. **한 번에 하나**: 프롬프트·도구·그래프·캐시 중 **하나만** 바꾼다. 바꾼 것은 `prompt_version`·`graph_version`에 남는다.
4. **재측정**: 같은 입력 묶음으로 다시 잰다. **정확도 지표(경로 Pass 비율, 판정 일치)도 함께** 재서 성능을 얻고 정확도를 잃지 않았는지 본다. k/n과 구간으로 기록하고 칸당 n이 8 이하면 유의성을 주장하지 않는다(9.1절).
5. **기록**: 병목 기록 한 줄(아래 (3) 양식)을 남긴다. 효과가 없으면 되돌린다.

### (2) 병목 유형별 진단과 수정 후보
| 유형 | 진단 신호(먼저 볼 로그 필드) | 수정 후보 | 수정 후 확인 기준(측정 전 값은 비워 둠) | 하지 말 것 |
|---|---|---|---|---|
| (a) 지연 | `latency_ms`를 `node`·`tool`별 합산, `model_calls_so_far`, 같은 `step`에 도구가 여러 개인지(병렬 여부), `source=api`의 지연, `retry` | 도구 호출 묶기(이미 `check_contraindications` 하나로 묶음), 병렬 도구 호출(`gpt-6-luna` 지원 확인 못 함), 공공 API 응답 캐시(공개 데이터만, 사용자와 연결 안 함, PJ2-RFP.md 7장), 평가·개발은 파일 기준(API 끔) | 요청당 중앙값·상위 지연: 기준 ___ ms → ___ ms. 경로 Pass 비율 하락 없음 | 응답 시간 목표 수치를 측정 전에 정하지 않는다(NFR-06). 지연을 줄이려고 필수 도구·Validator를 빼지 않는다 |
| (a') 공공 API 한도 | `source=api` 요청 수/일, HTTP 403·429 | 스냅샷·응답 캐시(RFP-32), 같은 요청 재호출 금지, 호출 간격 | 일일 요청 수 ___ / 10,000 | 평가에서 API를 켜지 않는다(BE-08) |
| (b) 비용 | `tokens_in`의 `step`별 증가(도구 결과 누적), `tokens_out`, `cost_usd`, `cache` 미스율 | 도구 결과를 필드 제한·청크 ID로 줄이기(RFP-22 §4 12번), 시스템 프롬프트 단축(버전 올림), 개발은 캐시 `record/replay`, 개발 중 부분집합 실행, OpenAI 원장 상한(RFP-34-05) | 실행당 평균 비용 ___ USD → ___ USD. 정확도 하락 없음 | 측정 도중 모델을 바꾸지 않는다. 비용을 줄이려고 평가 문항을 측정 뒤에 빼지 않는다(9.2절 축소 순서를 따르고 이유 기록) |
| (c) 루프·상한 초과 | `end_reason=호출 상한`, 같은 `tool`·같은 인자 반복, `rollbacks_so_far` | 도구 설명(docstring)의 경계 문장 보강, 오류 메시지에 다음 행동 적기(RFP-22 §4 3번), 같은 호출 반복 감지(개선 단계), 종료 sensor(AG-13) | 상한 종료 비율 ___ → ___ (k/n) | 상한 8·되돌림 2를 결과를 보고 몰래 바꾸지 않는다(RFP-22-05, 바꾸면 이유와 날짜를 남기고 이전 결과와 섞지 않음) |
| (d) 데이터 적재·검색 | 적재 스크립트 시간·행 수, DB 크기(BE-09 500MB 실측), `search_*` 도구 `latency_ms`, 검색 0건/관련 없음 비율 | 성분 쌍 단위 적재(23,619쌍) 대 제품 쌍 단위(512,464건) 선택(BE-09), pgvector 색인(종류는 BE-05·BE-10에서 시험), 청크 단위·차원 축소(PJ2-RFP.md 12장), 적재 재현 스크립트 | DB 크기 ___ MB / 500MB, 검색 지연 ___ ms | Supabase 일시정지 상태로 측정하지 않는다(시연·측정 전 깨움). 색인을 바꾼 뒤 이전 검색 지표와 섞지 않는다(색인 버전 기록, BE-08) |
| (e) 개발 병목 | 테스트 실행 시간, 외부 호출 수(`source=api`, `cache=off` 모델 span), 같은 실패 재현 실패 | API 스냅샷으로 오프라인 테스트(RFP-32, `data/mock/api_snapshots/`), LLM `replay`로 결정적 재현, mock trace(`data/mock/traces/`)로 채점기 테스트, 느린 테스트 분리(표시만) | 단위 테스트 전체 ___ 초, 외부 호출 0 | 캐시·mock 값을 평가 측정 값으로 쓰지 않는다(CLAUDE.md 4장). replay 결과로 정확도를 보고하지 않는다 |
| (f) 평가 병목 | judge span 수·`cost_usd`, 형식 오류 재시도, 실행 시간(150문항 × 조건 × 반복) | 코드 채점 우선(9.1절 3번), 부분집합 리허설, 중단 장치(호출 수·비용 상한, RFP-15 §8.3 ③), 실패 문항만 이어서 실행(같은 설정·같은 `run_id` 접두) | 1회 전체 실행 ___ 분·___ USD | **측정 도중 judge 모델·루브릭·평가 세트·C1 규칙을 바꾸지 않는다**(RFP-26-01, H16). 개선 중 시험셋을 열지 않는다(RFP-26-04) |

### (3) 병목 기록 양식
RFP-29 §7.3 실패 기록과 같은 자리(AG-13)에 둔다. 실패(정확도)와 병목(성능)을 한 표에서 구분한다.

| 기록 ID | 유형(a~f) | 관찰(로그 필드·값) | 가설 | 바꾼 것 하나 | 전 | 후 | 정확도 영향 | 판정 |
|---|---|---|---|---|---|---|---|---|
| (예) B-01 | (b) 비용 | step 3 이후 `tokens_in` 급증 | `get_label_section` 본문이 길다 | 절 본문 길이 제한(v2) | 측정 전 | 측정 전 | 측정 전 | 측정 전 |

### (4) 측정 기간의 동결 규칙(RFP-34-04 A 기준)
- **동결 대상**: 평가 세트(개발셋·시험셋 해시), judge 모델 ID·루브릭 버전, C1·C1+ 규칙, 지표 정의, 모델 ID, 호출 상한.
- **동결 기간**: 기준선 측정 시작(AG-11)부터 최종 재측정(AG-14)까지.
- **허용**: 병목 수정은 에이전트 쪽(프롬프트·도구·그래프·캐시 설정)에서 하고, 수정마다 `prompt_version`·`graph_version`이 바뀐다. 개선 확인은 **개발셋**으로만 한다.
- **성능 수정도 변경이다**: 캐시·병렬화·프롬프트 단축처럼 "정확도와 무관해 보이는" 수정도 C2·C3 설정 식별자에 남기고 정확도 지표를 함께 잰다.
- 동결 대상을 바꿔야 하면 이유와 날짜를 PJ2-RFP.md 9장에 남기고 이전 결과와 섞지 않는다(CLAUDE.md 5장).

## 8. 결정사항
원본은 [`tickets/doc/RFP-34.md`](../tickets/doc/RFP-34.md) §3 결정 현황이다. 아래는 요약이다. **2026-11-06 사용자 "RFP-34-01~05 권장대로"로 5건 모두 A로 정해졌다.**

| 번호 | 질문 | 선택지 | 권장 | 상태 | 본문 |
|---|---|---|---|---|---|
| RFP-34-01 | 서비스 모드에서 무엇을 남길까? | A) 내용 없는 집계 지표만(원문·해시·약 이름·프로필 없음) / B) 마스킹한 원문 포함 요청별 기록 / C) 아무것도 남기지 않음 | ★A | 결정됨(2026-11-06): A | §3 (2) |
| RFP-34-02 | 추적 도구를 무엇으로 할까? | A) 로컬 JSONL + LangGraph 콜백/스트림, 외부 SaaS 안 씀 / B) A + 합성 평가 실행에만 Langfuse 셀프호스트 병행 / C) 합성 평가 실행에 LangSmith·Langfuse 클라우드 | ★A | 결정됨(2026-11-06): A | §5 (2) |
| RFP-34-03 | 로그를 어디에 얼마나 둘까? | A) 로컬 `logs/`(git 제외), 개발 14일, 평가는 프로젝트 종료까지, 서비스는 앱 저장 없음 / B) SQLite 한 파일에 모두 / C) Supabase 테이블 | ★A | 결정됨(2026-11-06): A | §4 (5) |
| RFP-34-04 | 병목 수정 중 평가 조건을 어떻게 동결할까? | A) 기준선~최종 재측정 동안 세트·judge·루브릭·C1 규칙·지표·모델·상한을 동결, 성능 수정도 버전 기록 + 정확도 동시 측정, 개발셋으로만 확인 / B) 동결 없이 최종에만 재측정 | ★A | 결정됨(2026-11-06): A | §7 (4) |
| RFP-34-05 | 개발·디버깅 중 OpenAI 비용 상한을 둘까? | A) 원장으로 개발용 누적 상한을 코드 강제(본 측정 몫을 남김, 초안 2.5 USD) / B) 상한 없이 쓰고 모자라면 충전 | ★A | 결정됨(2026-11-06): A | §4 (4), §7 (2) (b) |

본문 태그: 서비스 지표 범위(RFP-34-01), 도구 선택(RFP-34-02), 보관(RFP-34-03), 동결(RFP-34-04), 개발 비용 상한(RFP-34-05).

## 9. 구현 티켓 생성안
> **반영됨(2026-11-06)**: 새 티켓을 만들지 않고 아래 "대안" 열대로 기존 티켓 완료 조건에 붙였다(L1·L5 → BE-15, L2 → AG-01, L3 → BE-08·AG-16, L4 → BE-06, 동결 규칙 → AG-13). 아래 표는 결정 전 생성안이며 기록으로 남긴다.

| 안 | 내용 | SCH(제안) | 선행(제안) | 대안(기존 티켓에 붙이기) |
|---|---|---|---|---|
| L1 로깅 모듈 | `MEDIAGENT_MODE`, span 스키마 `@v1`, 화이트리스트·모드 필터·비밀 마스킹, JSONL 쓰기·14일 정리, 단위 테스트(H13: 서비스 모드에 내용 필드가 남지 않음, 비밀 마스킹, `eval`↔`MEDIAGENT_EVAL` 일치) | SCH-01 | BE-01(골격·pytest) | BE-15 개발 하네스에 포함(BE-01이 커서 2026-11-09 BE-15로 분할, BE-01 §5 메모) |
| L2 그래프 계측 | 6노드 span, 도구 6개 자식 span, 콜백 핸들러(토큰·지연), 하네스 이벤트, 캐시 상태 연결(`llm_cache.py`) | SCH-02 | L1, AG-01 | AG-01 완료 조건에 "trace 필드 채움" 추가 |
| L3 요약·병목 리포트 스크립트 | trace → 노드·도구별 지연·토큰·비용 표, 종료 사유 분포, 상한 도달, 캐시 비율, 원장 대조, 병목 기록 초안 | SCH-02 | L1, L2 | BE-08의 결과 파일 요약에 포함 |
| L4 서비스 집계 지표 | RFP-34-01 A의 분 단위 집계(요청 수·지연·오류 유형·규칙별 차단 건수), 내용 필드 없음 테스트 | SCH-03 | BE-06 | BE-06 완료 조건에 추가 |
| L5 OpenAI 비용 원장 | `_common.py`와 같은 구조의 원장과 개발 상한(RFP-34-05) | SCH-01 | BE-15 호출 확인 | BE-15 `gpt-6-luna` 호출 확인 스크립트와 함께 |

- 권장(제 의견): L1+L5는 BE-01을 나누는 안(BE-01 §5)과 함께 정하고, L2는 AG-01, L3은 BE-08, L4는 BE-06에 붙여 **새 티켓을 0~1개**로 둔다.
- 경로 채점기·신뢰성 집계기는 이미 BE-08 완료 조건이다. 이 문서의 스키마가 그 입력 형식이 된다(`data/mock/traces/`의 형식과 맞추는 일은 BE-08에서 확인).

## 10. 확인하지 못한 것과 출처

### (1) 확인하지 못한 것
- `gpt-6-luna` 응답의 토큰 사용량·캐시 토큰 필드 이름, 병렬 도구 호출 지원과 표시 방식(BE-15 호출 확인 스크립트에서 확인).
- LangGraph 1.x에서 `stream_mode="debug"`와 콜백을 함께 쓸 때의 이벤트 중복 여부와 오버헤드(구현 때 확인).
- `data/mock/traces/`(RFP-31)의 필드 구성과 이 스키마의 차이(이 문서 작성 중 열지 않았다. BE-08에서 맞춘다).
- 배포 호스트(AWS 무료 인스턴스)의 표준 출력 로그 보관 기간과 접근 범위.
- 외부 추적 SaaS의 약관(데이터 처리·학습 여부·기본 지역), LangSmith trace 과금 단위가 span 수와 어떻게 대응하는지.
- 모든 지연·비용·크기 값: **측정 전**.

### (2) 웹 출처(읽은 날짜 2026-11-06)
- LangSmith 가격(Developer: 월 5k base trace, 14일 보관, 1석, US·EU 클라우드): https://www.langchain.com/pricing
- Langfuse 가격(Hobby: 월 50k 단위, 30일, 사용자 2명, 지역 US·EU·일본, 셀프호스트 무료): https://langfuse.com/pricing
- Langfuse 오픈소스·셀프호스트 기능 범위(제3자 정리, 공식 아님): https://www.zenml.io/blog/langfuse-pricing
- OpenTelemetry GenAI span 규약(`gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.*`, 개발 중 단계): https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/
- OpenTelemetry GenAI 에이전트 span 규약: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans
- LangGraph 스트리밍(`updates`·`debug` 등 stream mode, 비동기 콜백 전파): https://docs.langchain.com/oss/python/langgraph/streaming

### (3) 저장소 출처
`tickets/doc/RFP-22.md` §6·§8·§14.2, `tickets/doc/RFP-23.md` §4·§5, `tickets/doc/RFP-26.md` §7.6·§7.7, `tickets/doc/RFP-29.md` §4.3·§6·§7.3, `tickets/doc/RFP-32.md` §5·§9.4·§9.6, `tickets/doc/RFP-15.md` §8.3, `tickets/backend/BE-01.md`, `tickets/backend/BE-08.md`, `tickets/backend/BE-09.md`, `evaluation/mock_gen/llm_cache.py`, `evaluation/mock_gen/_common.py`, `P2-doc/PJ2-RFP.md` 7·9·12장, `P2-doc/PJ2-PRD.md` 6.2절.
