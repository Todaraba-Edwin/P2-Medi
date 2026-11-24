# dev_aux_u30.jsonl: FE-17 U-30-1 개발 보조 문항 (요약 문장 중복)

> 이 파일은 **평가 세트가 아니다**(2026-11-24). 개발셋 150문항(`dev_set.jsonl`)·`manifest.json`·시험셋(`*.SEALED.jsonl`)·안전 핵심 40문항(`reliability_core`)은 건드리지 않았고,
> 이 파일은 `manifest.json`에 **등록하지 않았다**(sha256 동결 대상 아님). 9장 지표(PJ2-RFP.md 9.3절)·judge·루브릭과 무관한 개발 확인용이다.

## 1. 왜 따로 두나
- FE-17 §3.30 U-30-1(ISSUE-035): 병용 질문의 요약에서 "금기 목록에 없음"을 말하는 문장이 두 번 나온다. 개발셋 150문항에는 이 부류(요약 문장 안의 같은 뜻 되풀이)를 재는 문항이 없다.
- 세트는 고정이고 빌더(`build_eval_set.py`)는 다시 돌리지 않는다(`README.md` 2장). 그래서 `fix_*.py`를 더하지 않고 **별도 파일**로 둔다.
- 시험셋·안전 핵심 40문항에는 넣지 않는다(신뢰성 지표 분모 보존). 질문은 합성이고 사용자 질문이 아니다(`u30-text-008`만 2026-11-24 사용자 사례 원문).

## 2. 문항 (8개)
| 종류 `kind` | 수 | 내용 |
|---|---|---|
| `dup_pair` | 4 | 약 이름 쌍의 병용 질문 + 가짜 모델이 **중복 문장을 낸** 요약(문장 순서·길이를 달리함). 두 문항(`u30-dup-002`·`-004`)은 같은 성분(아세트아미노펜)이라 용량주의 겹침 쌍이다 |
| `nodup_pair` | 2 | 중복이 없는 요약. 지우기 코드가 아무것도 바꾸면 안 된다(보호 짝, 용량주의 겹침 1건 포함) |
| `three_drugs` | 1 | 약 3개: 서로 다른 쌍에 대한 "금기 목록에 없음" 문장 두 개는 중복이 아니므로 둘 다 남아야 한다 |
| `text_only` | 1 | 2026-11-24 사용자 사례(`타이레놀정500 먹고 이부프로펜도 먹어도 돼요?`) 문장 그대로. 이부프로펜은 합성 사전에 없어 그래프 없이 문장 목록에 직접 적용한다 |

문항 칸: `id`·`set`(`dev_aux_u30`)·`kind`·`candidate`·`question`·`n_drugs`·`overlap`(선택)·`fake_sentences`(가짜 모델이 내는 문장 `{text, claim_type}`)·`expected`.

## 3. 채점(코드, LLM·judge 0)
`evaluation/dev_aux_u30.py`가 한다. `expected`는 코드로 정한 값이다.
- `not_listed_sentences_le_max`: 요약에 남은 "금기 목록에 없음" 계열 문장 수(`summary_dedupe.classes_of`) ≤ 기준(중복 문항 1, 3약 문항 2).
- `n_dropped`: 지운 문장 수(`SUMMARY_DEDUPE` 이벤트의 `dropped`)가 기대와 같다.
- `keeps_classes`: 약사 확인·안전 단정 금지 뜻이 지운 뒤에도 남고, 지우기 전 뜻 종류 집합과 같다(`after == before`).
- `no_new_text`: 요약이 가짜 모델 문장을 이은 글자뿐이다(새 문장·새 숫자 생성 없음).
- `summary_safe`: `sentence_filter.unsafe_reason`(용량 숫자·가부·권유 표현)이 없다.
- 한계: 가짜 모델이 중복을 내도록 **만든** 문장이라 실제 모델이 중복을 얼마나 내는지는 LLM 호출 없이 측정하지 못한다. 그 측정은 병합 뒤 소액 실제 호출로 한다(`prompt_set@v5`의 `answer_summary@v2`와 코드 지우기 `summary_dedupe`를 각각 한 번에 하나씩 켜는 ablation, 9.8절).

## 4. 실행
```
backend/.venv/bin/python evaluation/dev_aux_u30.py [--dict-path data/mock/dict/drug_dict.json] [--out-md OUT.md]
```
`dedupe_on`은 8/8 통과, `dedupe_off`(스위치 `summary_dedupe` 끔 = 이전 동작)는 중복 문항 4개(`dup_pair`)와 `text_only` 1개 중 `not_listed_sentences_le_max`·`n_dropped`가 통과하지 못하는 것이 정상이다(합성 사전·`data/mock/dict/drug_dict.json` 모두 같은 결과).
