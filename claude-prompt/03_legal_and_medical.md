# 03. Legal / Financial & Medical Guidance

> `<legal_and_financial_advice>` + `<medical_guidance>` · MediAgent와 가장 직접적으로 연결되는 파트
>
> 문단별로 원문(영어)과 한글 번역을 나란히 둔다. 원문은 인용(`>`), 번역은 그 아래 본문.

## 문단별 원문 · 번역

### A. `<legal_and_financial_advice>`

#### 1. 법률·금융 질문

> For financial or legal questions (e.g. whether to make a trade), Claude provides the factual information the person needs to make their own informed decision rather than confident recommendations, and notes that it isn't a lawyer or financial advisor.

금융이나 법률 질문(예: 거래를 해야 하는지)에는, Claude는 확신에 찬 추천 대신 사용자가 스스로 충분히 알고 결정하는 데 필요한 사실 정보를 제공하고, 자신이 변호사나 재무 상담가가 아니라는 점을 밝힌다.

### B. `<medical_guidance>`

#### 2. 적용 조건

> This applies only when the person explicitly says the medicine is for a child, and isn't a healthcare professional asking for work.

이 규칙은 사용자가 그 약이 아이를 위한 것이라고 명시적으로 말했고, 업무 때문에 묻는 의료 전문가가 아닐 때에만 적용된다.

#### 3. 소아 용량과 라벨

> Dosing for children's over-the-counter medicines depends on the child's weight and the specific product. For infants and toddlers, a small error can cause real harm. The product's label is the most reliable source, so Claude reports accurately what it says.

소아용 일반의약품의 용량은 아이의 체중과 구체적인 제품에 따라 달라진다. 영유아의 경우 작은 오차도 실제 해를 끼칠 수 있다. 제품 라벨이 가장 믿을 수 있는 출처이므로, Claude는 라벨에 적힌 내용을 정확하게 전달한다.

#### 4. 정보 부족 · 처방약

> If neither the child's age or weight is given, Claude asks for both. If a doctor has prescribed the medicine, Claude defers to the dose on the prescription label and suggests the pharmacist for any questions about it.

아이의 나이도 체중도 주어지지 않았다면, Claude는 둘 다 묻는다. 의사가 그 약을 처방했다면 Claude는 처방 라벨에 적힌 용량을 따르고, 그에 대한 궁금한 점은 약사에게 물어보라고 권한다.

#### 5. 검색 가능 여부에 따른 처리

> If web search is available, Claude uses it to find the product's label and confirms it against an official copy of the same label, such as DailyMed. If web search is not available or Claude can't find the label, Claude doesn't give a number from memory and instead points the person to the label's dosing chart, a pharmacist, or the child's doctor. Claude shares what the label states for the child's age and weight: the dose, plus any instruction to ask a doctor. If the label gives no dose for that age or weight, or says not to use the product, Claude says so and refers the person to their doctor or pharmacist.

웹 검색을 쓸 수 있다면 Claude는 그것으로 제품 라벨을 찾고, DailyMed 같은 동일 라벨의 공식 사본과 대조해 확인한다. 웹 검색을 쓸 수 없거나 라벨을 찾지 못하면, Claude는 기억에 의존한 숫자를 말하지 않고 라벨의 용량표, 약사, 또는 아이의 주치의를 안내한다. Claude는 라벨이 아이의 나이와 체중에 대해 명시한 내용, 즉 용량과 의사에게 물어보라는 안내가 있으면 그것까지 함께 전달한다. 라벨에 해당 나이나 체중에 대한 용량이 없거나 그 제품을 쓰지 말라고 되어 있으면, Claude는 그대로 말하고 사용자에게 의사나 약사와 상담하도록 안내한다.

## 핵심 포인트

- **적용 범위를 좁게 명시**한다 ("아이 약이라고 명시했을 때만").
- **숫자는 출처에서만** 나온다: 라벨 → 공식 사본 대조 → 없으면 숫자 대신 안내.
- **필요한 정보가 없으면 먼저 묻는다** (나이 + 체중).
- **처방이 있으면 처방이 우선**이다.
- "단정적 추천" 대신 **판단 재료(사실)**를 준다.

## MediAgent 적용

이 파트는 MediAgent의 근거 고정(FR-04, FR-05, FR-08) 설계와 거의 같은 구조다.

### FR이란?

**FR(Functional Requirement)은 기능 요구사항**이다. 프로젝트 요구사항 문서 [`P2-doc/PJ2-RFP.md`](../P2-doc/PJ2-RFP.md)의 기능 요구사항 표에 `FR-01`~`FR-08`로 번호가 매겨져 있다. 아래는 이 파트와 관련된 항목이다.

| ID | 요구사항 (RFP 원문) | 우선순위 | 이 파트와의 연결 |
|---|---|---|---|
| FR-04 | **Citation**: 모든 답변에 출처·조회 시각·조항 표기 | 필수 | 라벨(출처)을 정확히 전달하는 규칙에 대응. 숫자마다 "어디서 나왔는지"를 붙인다 |
| FR-05 | **Validator**: 답변이 원본 API·문서와 일치하는지 점검 후 출력 | 필수 | "공식 사본(DailyMed)과 대조"에 대응. 생성된 답변의 수치를 원본과 다시 비교한다 |
| FR-08 | **근거 없음 처리**: 검색 결과가 없으면 지어내지 않고 모른다고 응답 | 필수 | "라벨을 못 찾으면 기억으로 숫자를 말하지 않는다"에 대응 |

세 항목이 합쳐서 **근거 고정(grounding)**, 즉 "답변의 사실은 조회한 근거에서만 나오게 묶어 두는 것"을 이룬다. 흐름은 다음과 같다.

1. 근거를 **찾는다** (API·문서 조회)
2. 근거가 없으면 **멈춘다** (FR-08)
3. 근거가 있으면 답을 만들고 **출처를 붙인다** (FR-04)
4. 출력 전에 답과 근거가 **일치하는지 확인한다** (FR-05)

참고로 RFP의 나머지 FR 중 이 파트와 간접적으로 이어지는 것은 다음과 같다.
- **FR-02**: 공공 API 조회와 조회 시각 기록. 근거의 공급원이다.
- **FR-06**: 진단·처방 금지 문구 등 Guardrail. 아래 "전문가가 아님을 밝힘" 행과 이어진다.

### 규칙 대응표

| 원문 규칙 | MediAgent 규칙 | 관련 FR |
|---|---|---|
| 라벨이 가장 신뢰할 출처 | e약은요·DUR API 응답이 유일한 사실 출처 | FR-02, FR-04 |
| 공식 사본과 대조 | Validator가 답변 수치를 API 원본 JSON과 대조 | FR-05 |
| 못 찾으면 기억으로 숫자 말하지 않기 | 조회 실패 시 용량·수치 출력 금지, 약사·의사 안내 | FR-08 |
| 나이·체중 없으면 묻기 | 연령 금기·임부 금기 판단에 필요한 정보(나이, 임신 여부)가 없으면 질문 1개로 확인 | FR-01 |
| 처방이 우선 | "처방받은 약이면 처방전과 약사 안내를 따르세요" 고지 | FR-06 |
| 확신 대신 사실 | "같이 드셔도 됩니다" 대신 "DUR 기준 병용금기로 등록되어 있지 않습니다(조회 시각)" | FR-04 |
| 전문가가 아님을 밝힘 | 응답 하단 고지: "공공데이터 기반 정보이며 진단·처방이 아닙니다" | FR-06 |

### 확장: "공식 사본과 대조" = Validation logic (FR-05)

"공식 사본과 대조"는 원문에서는 **모델이 웹 검색으로 직접 하는 행동**이다. MediAgent에서는 이것을 그대로 프롬프트에 옮기지 않고 **코드(Validator 노드)로 구현**한다. 의료 문맥에서 "validation logic"은 보통 *검증 로직 / 유효성 검사 로직*을 뜻하며, 여기서는 **프롬프트가 할 일과 코드가 할 일이 서로 다르다**는 점이 핵심이다.

#### 왜 프롬프트로 맡기면 안 되는가

- 프롬프트는 **부탁**이다. "수치를 원본과 대조하라"고 써도 모델이 지켰는지는 프롬프트 안에서 확인할 수 없다.
- 코드는 **강제**다. 불일치하면 출력 경로 자체가 막힌다. 모델이 어떻게 답했든 결과가 같다.
- 의료 수치(용량, 연령 기준, 병용금기 여부)는 틀렸을 때 피해가 크므로, "대부분 지킨다"가 아니라 "어기면 나갈 수 없다"여야 한다.

#### 두 계층의 역할 구분

| 구분 | 프롬프트 계층 (서비스 레벨, 행동 지침) | 코드 계층 (Agent-RAG 구현, 검증 로직) |
|---|---|---|
| 성격 | 모델이 **어떻게 말하고 판단할지**를 유도 | 출력이 **나가도 되는지**를 결정 |
| 강제력 | 확률적. 지켜질 가능성이 높을 뿐 보장 없음 | 결정적. 같은 입력이면 항상 같은 판정 |
| 어디에 | `prompts/system.md` | `agent/` 그래프의 Validator 노드, `tools/`, 테스트 |
| 검증 가능성 | 사람이 샘플을 읽어 평가 | 단위 테스트·CI로 자동 검증 |
| 실패 시 | 어색하거나 부정확한 답이 나갈 수 있음 | 응답 차단 또는 재생성, 또는 "확인할 수 없음" 응답 |

#### 항목별 배분

| 작업 | 프롬프트 계층 | 코드 계층 (FR) |
|---|---|---|
| 수치·기준이 근거와 일치하는가 | "근거에 없는 숫자는 쓰지 않는다"라고 지시 | 답변에서 숫자·단위·약품명을 추출해 API 원본 JSON/문서 청크와 **문자열·값 비교**. 불일치 시 차단 (FR-05) |
| 출처 표기 | "출처와 조회 시각을 붙인다"라고 지시 | 출처·조회 시각 필드가 비었으면 **출력 거부** (FR-04) |
| 근거가 없을 때 | "모르면 모른다고 말한다"라고 지시 | 검색 결과 0건이면 **LLM 호출 없이** 고정 문구 응답 (FR-08) |
| 진단·처방 금지 | 거절 어조와 안내 문장을 지시 | 금지 패턴·응급 키워드 감지 후 **분기**. 응급이면 119 안내로 라우팅 (FR-06) |
| 필수 정보 부족 | "나이·임신 여부가 필요하면 질문 1개"라고 지시 | Router가 엔티티 누락을 판정해 질문 분기로 이동 (FR-01) |
| 면책 문구 | 문구 톤을 지시 | 응답 하단에 고지 문자열을 **코드가 항상 덧붙임** |

원칙은 **"말투와 판단의 방향은 프롬프트, 사실의 통과 여부는 코드"**다. 규칙을 하나 정할 때마다 *"이게 어겨지면 사고인가?"*를 묻고, 그렇다면 코드로 내린다.

#### Validator가 하는 일 (코드 레벨)

```
답변 초안 + 근거(API JSON·문서 청크)
   │
   ├─ 1. 필수 필드 확인: 출처, 조회 시각, (문서면) 조항·연도
   ├─ 2. 주장 추출: 답변 속 수치·단위·약품명·금기 여부
   ├─ 3. 대조: 추출한 값이 근거에 실제로 있는지 확인
   └─ 4. 판정
        ├─ 모두 일치 → 출력
        ├─ 불일치    → 재생성 (횟수 제한) 후에도 실패하면 차단
        └─ 근거 없음 → "확인할 수 없음" 고정 응답 (FR-08)
```

- 재생성은 **횟수 상한**을 둔다. 무한 재시도는 비용과 지연을 키운다.
- 판정 결과(통과/차단 사유)는 **로그로 남겨** 평가 세트와 오정보 사례 분석에 쓴다.
- 이 로직은 LLM이 아닌 **일반 코드**로 짜는 부분이 많을수록 재현성이 높다. 다만 "문장 속 주장 추출"처럼 규칙으로 어려운 부분은 LLM을 보조로 쓸 수 있으며, 그 경우에도 **최종 비교와 차단 결정은 코드**가 한다.

#### 주의: 이름이 같아도 다른 것

| 용어 | 뜻 | 위치 |
|---|---|---|
| **Validator (FR-05)** | 답변이 근거와 일치하는지 확인하는 **내용 검증** | 에이전트 그래프의 노드 |
| 입력 유효성 검사 | 요청 형식·타입·길이 확인 (예: 빈 문자열, 허용되지 않는 파라미터) | API 계층 (FastAPI 등) |
| 평가 (Ragas, Faithfulness) | 배포 전후에 **품질을 측정**하는 오프라인 작업 | `eval/` |

Validator는 **런타임에 매 응답마다** 돌고, Ragas 평가는 **개발 중에 배치로** 돈다. 둘 다 "충실도"를 다루지만 역할이 다르므로, Ragas 점수가 좋다고 Validator를 생략하지 않는다.
