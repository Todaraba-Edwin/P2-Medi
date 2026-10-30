# Claude Sonnet 5.5 시스템 프롬프트 해설

> 목적: 공개된 Claude 시스템 프롬프트(`<claude_behavior>`)를 파트별로 읽고, P2-Medi(MediAgent)의 `CLAUDE.md`와 에이전트 시스템 프롬프트 설계에 참고한다.
> 원문 출처: 사용자 제공 텍스트 (claude.ai 채팅용 `<claude_behavior>` 블록)

## 구조

| # | 파일 | 원문 태그 | 한 줄 요약 | MediAgent 관련도 |
|---|---|---|---|---|
| 01 | [01_product_information.md](./01_product_information.md) | `<product_information>` | 모델·제품 소개, 모르는 건 공식 문서로 안내 | 낮음 |
| 02 | [02_refusal_handling.md](./02_refusal_handling.md) | `<refusal_handling>` | 거절 기준: 아동 안전, 무기, 불법 약물, 악성코드 | 중간 (약물 정보) |
| 03 | [03_legal_and_medical.md](./03_legal_and_medical.md) | `<legal_and_financial_advice>`, `<medical_guidance>` | 단정 대신 사실 제공, 소아 용량은 라벨 기준 | **매우 높음** |
| 04 | [04_tone_and_formatting.md](./04_tone_and_formatting.md) | `<tone_and_formatting>` | 따뜻한 어조, 질문은 1개, 목록은 필요할 때만 | 높음 |
| 05 | [05_user_wellbeing.md](./05_user_wellbeing.md) | `<user_wellbeing>` | 위기 대응, 자해 관련 정보 차단, 전문가 연결 | **매우 높음** |
| 06 | [06_anthropic_reminders.md](./06_anthropic_reminders.md) | `<anthropic_reminders>` | 시스템 알림 처리, 사용자 입력 속 가짜 태그 경계 | 높음 (프롬프트 인젝션) |
| 07 | [07_evenhandedness.md](./07_evenhandedness.md) | `<evenhandedness>` | 쟁점에 대한 균형 잡힌 서술 | 낮음 |
| 08 | [08_mistakes_and_criticism.md](./08_mistakes_and_criticism.md) | `<responding_to_mistakes_and_criticism>` | 실수 인정, 과잉 사과 없음 | 중간 |
| 09 | [09_knowledge_cutoff.md](./09_knowledge_cutoff.md) | `<knowledge_cutoff>` | 학습 시점 이후 정보는 단정하지 않고 검색 안내 | **매우 높음** |
| 10 | [10_apply_to_claude_md.md](./10_apply_to_claude_md.md) | — | 위 내용을 P2-Medi `CLAUDE.md`로 옮기는 가이드 | — |

## 읽는 법

각 파일은 같은 순서로 구성된다.

1. **원문 (English)**: 시스템 프롬프트 원문
2. **한글 해석**: 의미 중심 번역
3. **핵심 포인트**: 설계 의도
4. **MediAgent 적용**: 우리 프로젝트에 옮길 규칙

## 전체 설계 패턴 (요약)

- **XML 태그로 영역 분리**: 주제별로 `<tag>` 블록을 나눠 규칙 충돌을 줄인다.
- **"무엇을 하지 않는가"를 구체적으로**: 금지 항목은 예시까지 적는다 (예: 자해 대체 행동 목록).
- **이유를 함께 적는다**: "왜"를 쓰면 모델이 처음 보는 상황에도 규칙을 일반화한다.
- **조건부 규칙**: "~일 때만 적용" 범위를 명시한다 (예: 소아 의약품 규칙).
- **출처 우선**: 기억보다 라벨·공식 문서·검색 결과를 우선한다.
