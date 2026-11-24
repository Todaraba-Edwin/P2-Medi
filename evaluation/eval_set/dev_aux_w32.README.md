# dev_aux_w32.jsonl: W3-2 개발 보조 문항 (AG-13-41·45·46)

> 이 파일은 **평가 세트가 아니다**(2026-11-24). 개발셋 150문항(`dev_set.jsonl`)·`manifest.json`·시험셋(`*.SEALED.jsonl`)·안전 핵심 40문항(`reliability_core`)은 건드리지 않았고,
> 이 파일은 `manifest.json`에 **등록하지 않았다**(sha256 동결 대상 아님). 9장 지표(PJ2-RFP.md 9.3절)·judge·루브릭과 무관한 개발 확인용이다.

## 1. 왜 따로 두나
- 9.8절 "개발셋 실패 사례 근거"를 채우려는 보조 문항이다. 개발셋 150문항에는 시각·횟수 표현이 약 이름으로 오인되는 부류가 없고(걸린 문항 0, 2026-11-24 router 단독 전후 비교 0/150),
  되묻기에서 고른 약(`confirmed_item_seqs`)이 든 서비스형 입력은 평가 경로가 쓰지 않아 개발셋에서 재현되지 않는다.
- 세트는 고정이고 빌더(`build_eval_set.py`)는 다시 돌리지 않는다(`README.md` 2장). 그래서 `fix_*.py`를 더하지 않고 **별도 파일**로 둔다.
- 시험셋·안전 핵심 40문항에는 넣지 않는다(신뢰성 지표 분모 보존). 질문은 합성이고 사용자 질문이 아니다.

## 2. 문항 (16개)
| 종류 `kind` | 수 | 후보 | 내용 |
|---|---|---|---|
| `time_expression` | 10 | AG-13-41 | "점심12시"·"정오12시"·"4시간뒤"·"네시간뒤"·"점심시간"·"12시30분"·"9시간격"·"하루3번"·"하루세번"·"두시간 후"가 약 이름으로 뽑혀 되묻기로 끝나던 부류(첫 문항은 2026-11-24 사례 원문) |
| `control_unchanged` | 3 | AG-13-41 | 보호 짝: "타이레놀8시간이알서방정"처럼 사전 제품명에 "시간"이 든 이름과 이미 되던 입력. 스위치를 켜도 Router 결과가 같아야 한다 |
| `confirmed_selection` | 3 | AG-13-45·46 | U-26 사례(타이레놀정500 + 콜드-에스, 임신)와 변형. `confirmed_item_seqs`에 고른 약의 품목기준코드(타이레놀정500밀리그람 202106092, 코푸콜드-에스액 201900975 등, 사전 `be10-dict-s1-1055d3576876`에서 찾은 값) |

## 3. 정답(코드 채점, LLM·judge 0)
`expected` 칸의 값은 코드로 정한 것이고 채점은 `evaluation/dev_aux_w32.py`가 한다.
- `time_expression`: 엔티티가 RESOLVED 1개(타이레놀정500밀리그람)뿐, `ambiguous=False`·`clarify=None`, `redose_question`·`intake_question`, 도구 인자에 시각·횟수 정규식에 맞는 `name` 없음,
  `end_reason != CLARIFY`, `redose_notice == REDOSE_NOTICE`(고정 문구 일치), 요약에 용량 숫자·가부 문장 없음(`sentence_filter.unsafe_reason` = `DOSE_NUMBER`·`_DECISION_PATTERNS`·AG-13-40 Sensor 재사용).
- `confirmed_selection`: 확정 집합 밖 품목기준코드가 판정 근거에 없음(`no_out_of_set_items`), 선택 쌍 조회 근거가 없으면 "확인하지 못한 짝 0건"이 아님(`no_false_zero_unchecked`),
  약 키별 "확인 못 함" 화면 줄이 1줄(`unconfirmed_lines_per_drug`), 요약 문장 안전.
- 한계: 채점 관측은 실제 Router·그래프·도구 본문에 **가짜 모델**(규칙대로 부르는 `compliant`, 비선택 후보를 섞는 `leaky`, 선택 쌍을 빼는 `skip`)을 붙이고 판정 DB는 빈 SQLite라 코드 경로만 본다.
  실제 모델이 어떤 도구·인자를 고르는지는 LLM 호출 없이 측정하지 못한다.

## 4. 실행
```
backend/.venv/bin/python evaluation/dev_aux_w32.py [--dict-path data/mock/dict/drug_dict.json] [--out-md OUT.md]
backend/.venv/bin/python backend/scripts/ag13_router_ablation.py [--out-md OUT.md]    # 개발셋 150 + 이 보조 문항의 router 단독 전후 비교
```
