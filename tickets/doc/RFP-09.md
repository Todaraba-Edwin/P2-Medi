---
id: RFP-09
label: RFP
title: FR-08 근거 없음 처리 요구사항 추적
sch: SCH-02
status: done
priority: 필수
rfp: [FR-08]
created: 2026-10-30
done: 2026-11-20
---

# RFP-09 · FR-08 근거 없음 처리 요구사항 추적

## Index
- [1. 이슈](#1-이슈)
- [2. 완료 조건](#2-완료-조건)
- [3. 하위 작업](#3-하위-작업)
- [4. 관련](#4-관련)
- [5. 메모](#5-메모)

## 1. 이슈
RFP 6장 FR-08: "근거 없음 처리: 검색 결과가 없으면 지어내지 않고 모른다고 응답. '금기 목록에 없음'과 '근거 없음(약 미식별·데이터 없음)'을 구분해 안내한다". AG-09의 충족 여부를 추적한다.

## 2. 완료 조건
- [x] (2026-11-20 AG-09 done) AG-09가 done이다.
- [x] (2026-11-20 증거: `backend/tests/test_ag09_no_evidence.py` `test_fact_citing_only_unconfirmed_items_is_dropped`(`:65`)·`test_unconfirmed_guidance_points_to_pharmacy_and_pharmacist`(`:209`)·`test_one_unknown_drug_in_a_pair_is_shown_as_pair_not_checked_by_the_real_tool`(`:163`)) 검색 결과 0건 질문에서 "모른다" 응답과 안내("근처 약국·약사에게 확인")가 나오고 사실 문장이 없음을 확인했다.
- [x] (2026-11-20 pytest 이름: `test_ag09_no_evidence.py::test_not_listed_unidentified_no_code_and_missing_texts_all_differ`(`:132`)·`::test_no_official_site_guidance_and_doctor_only_in_listed_constants`(`:201`), `test_ag08_approved_phrases.py:260`) "금기 목록에 없음"과 "근거 없음(약 미식별)" 응답이 서로 다른 문구로 나옴을 확인했다. 확인: AG-09의 pytest 테스트 이름을 메모에 적는다.

## 3. 하위 작업
- [x] AG-09 완료 확인
- [x] 0건 케이스 결과 확인
- [x] "금기 목록에 없음" / "근거 없음" 구분 확인

## 4. 관련
- 선행: AG-09
- 관련 문서: `P2-doc/PJ2-RFP.md` 6장, `claude-prompt/09_knowledge_cutoff.md`

## 5. 메모
- 2026-11-20 **W2 감사로 done 처리(사용자 지시)**: AG-09 done으로 선행이 충족됐고 증거는 AG-09 §2의 시험 이름(위 완료 조건)으로 기록했다. 새 측정 없음, 읽기·grep만. 남은 일 없음(재검색 보정은 AG-13).
- 2026-11-02 전체 점검(RFP-22-02): 벡터 검색은 항상 k개 청크를 돌려주므로 "0건" 기준은 필터·정확 일치 경로에만 해당한다. 의미 검색의 "근거 없음" 판정 방식(코드 ID 일치 우선, 애매하면 LLM grade)은 RFP-22에서 정한 뒤 이 티켓에 반영한다.
- 2026-11-02 RFP-22-02 결정(A): 의미 검색의 "근거 없음"은 코드 검사 우선, 애매하면 LLM grade로 판정한다(RFP-22 §14.1).
