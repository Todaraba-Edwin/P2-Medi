# prompts/

프롬프트·도구 설명 파일을 두는 곳이다(BE-15, RFP-29-01 A, PRD-16-01). 규칙의 원본은 `P2-doc/PJ2-프롬프트-설계.md` 6장이고, 검사는 `app/llm/prompts.py`(L0)가 한다.

## 파일 이름·버전
- 프롬프트 파일은 `<이름>@v<n>.md`다(예: `agent_system@v1.md`, `tool_check_contraindications@v1.md`). 내용을 바꾸면 새 버전 파일(`@v2`)을 만든다. 이미 채택한 파일을 고쳐 쓰지 않는다.
- 묶음 파일은 `prompt_set@v<n>.yaml`이다. 실행 한 번에 쓰는 프롬프트 파일(`agent_system`·`answer_summary`·`router`·`validator` 등)을 나열한다. 한 묶음에는 같은 이름의 프롬프트를 하나만 둔다.

```yaml
name: prompt_set@v1          # 파일 이름과 같아야 한다
prompts:
  - agent_system@v1
  - answer_summary@v1
  - router@v1
  - validator@v1
```

## 로그 필드
- `prompt_set`: 실행 한 번이 쓴 **묶음 이름**(`prompt_set@v1`). dev·eval·service 모두 기록한다. 버전 문자열일 뿐 내용이 아니라 RFP-34(서비스 모드 내용 없음)와 충돌하지 않는다. 형식이 `prompt_set@v<n>`이 아니면 기록하지 않는다.
- `prompt_version`: 개별 프롬프트 파일 하나(`agent_system@v1`)를 가리키는 기존 필드(dev·eval). 묶음 전체를 대표하는 값은 `prompt_set`이다.
- 캐시: `cached_openai_call(prompt_files=...)`에는 `app.llm.prompts.resolve_prompt_files("prompt_set@v1")`의 결과를 넘긴다(`llm_cache`가 파일 내용 해시를 키에 넣는다).

## 프런트매터(정적)
파일 맨 앞 `---` 블록. 필수 칸: `id`(예 `P-AG01-model`), `version`(파일 이름의 `v<n>`과 같게), `ticket`, `model`, `h_rules`(목록), `golden_ids`(**개발셋 ID `dev-nnn`만**), `status`(`draft`|`adopted`).
- **`last_eval`은 프런트매터에 두지 않는다.** `llm_cache`가 프롬프트 파일 내용 해시를 키에 넣으므로, 평가 결과를 파일에 적으면 프롬프트가 안 바뀌어도 캐시가 무효가 된다. 평가 결과는 설계 문서 3장의 검토 카드에 둔다.
- 프런트매터는 정적 값만 쓴다(실행 중 바뀌는 값·날짜별 갱신 값 금지).

## 금지 내용(L0 검사 대상)
- 비밀값(API 키·`serviceKey=`·`postgres://`·JWT 등, `app/logging/masking.py`의 패턴).
- 실제 사용자 질문, 특히 약 이름이 든 실제 질문 형식(따옴표 문장·`질문:` 줄에 제품명 + 질문 어미). 예시는 `<약이름>` 같은 자리표시자로 쓴다.
- 평가 세트 문항: 개발셋(`evaluation/eval_set/dev_set.jsonl`) 질문 문장이 본문에 들어 있으면 위반이다(공백 무시 일치).
- **시험셋 문항은 L0가 검사하지 않는다.** `test_set.SEALED.jsonl`은 개선 중 열람 금지(RFP-26-04)이고 `manifest.json`의 해시로는 문장 일치를 알 수 없어 구현하지 않았다. 시험셋 문장이 섞이지 않았는지는 **사람이 확인**한다(프롬프트 예시는 직접 지어 쓴다).

## 검사 실행
- `cd backend && .venv/bin/python -m app.llm.prompts` — 위반이 있으면 종료 코드 1, 위반 상세에는 규칙 이름·칸·줄 번호·문항 ID만 나오고 문장 원문은 나오지 않는다.
- 같은 검사가 pre-commit 훅(`check-prompts`)과 pytest(`tests/test_be15_prompts.py`)에서 돈다.
- 한계: 약 이름 질문 형식은 휴리스틱(제품명 꼴 + 질문 어미)이라 놓치거나 오탐할 수 있다. 개발셋 일치는 정확 부분 일치만 본다(말만 바꾼 변형은 못 찾는다).
