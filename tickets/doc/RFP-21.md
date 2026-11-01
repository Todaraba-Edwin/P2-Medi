---
id: RFP-21
label: RFP
title: Pre-Week 공공 API 3종 실측 확인과 실현 가능성
sch: SCH-00
status: doing
priority: 필수
rfp: [5.2, 10장]
created: 2026-11-01
done: -
---

# RFP-21 · Pre-Week 공공 API 3종 실측 확인과 실현 가능성

## Index
- [이슈](#이슈)
- [완료 조건](#완료-조건)
- [하위 작업](#하위-작업)
- [관련](#관련)
- [메모](#메모)

## 이슈
PJ2-W1 구현을 시작하기 전에 e약은요·DUR 품목정보·DUR 성분정보를 실제로 호출해, 이 프로젝트를 실제 공공 API로 진행할 수 있는지 확인한다. 결과는 RFP 5.2절에 기록하고 서비스별 응답은 `P2-doc/PJ2-API-응답확인.md`에 둔다. 근거는 RFP 10장 사전 행("공공 API 3종 실측 확인(RFP-21)")이다. 2026-11-01 사용자 요청: API 테스트 상황을 Pre-Week에서 확인하고 RFP-번호 문서로 PJ2-RFP.md에 기록한다.

## 완료 조건
- [x] 세 서비스의 키·END_POINT가 동작한다. — FastAPI 프로브로 21회 호출, 실패 0건(2026-11-01). 성분정보는 키 교체 후
- [x] 오퍼레이션·필드·건수가 기록되어 있다. — `P2-doc/PJ2-API-응답확인.md`
- [x] e약은요 명세 5장 원문 오류 8건을 실제 응답과 대조했다. — `P2-doc/IROS_239_e약은요_서비스_v1.0.md` 5장 (3)
- [x] 키가 추적 파일·전체 커밋 이력·`data/api_samples`에 없음을 확인했다. — 2026-11-01
- [x] 시나리오별 실현 가능성 판정이 RFP 5.2절에 기록되어 있다. — 판정: 진행 가능, 조건부 2·미정 1
- [ ] 사용자가 RFP 5.2절의 실측 결과와 판정을 확인한다.
- [ ] 사용자 결정 2건(허가정보 API 활용신청 시점, 파일↔API 성분 연결 규칙)이 기록되거나 W1 이관 사유가 적혀 있다.
- [x] 세 API 각각 실제 호출 3건을 목(mock) 픽스처로 저장했다. — `tests/fixtures/api/`(9건과 `manifest.json`), FastAPI `/mock`, 캡처는 `scripts/api_probe/capture_fixtures.py`
- [x] 응답 값과 엔티티 구조를 파악할 수 있는 문서가 있다. — `P2-doc/PJ2-API-엔티티.md`(공통 응답, 서비스별 엔티티·필드, 연결 키, 정규화 규칙)

## 하위 작업
- [x] FastAPI 프로브 작성(`scripts/api_probe/`, `.venv`는 git 제외)
- [x] `.env.example` 작성(변수 이름만)
- [x] 세 서비스 오퍼레이션별 호출과 응답 샘플 저장(`data/api_samples/`, git 제외)
- [x] `P2-doc/PJ2-API-응답확인.md` 작성
- [x] RFP 5.2절 작성(실측 결과, 시나리오별 판정, W1로 넘기는 것)
- [x] 키 비노출 확인(추적 파일·커밋 이력·샘플 폴더)
- [ ] 사용자가 RFP 5.2절을 확인
- [ ] 사용자 결정 ① 허가정보 API 활용신청 시점
- [ ] 사용자 결정 ② 파일과 API의 성분 연결 규칙(구현은 W1의 BE-09·BE-10)

## 관련
- 선행: 없음
- 상위: [RFP-01](RFP-01.md)(RFP 문서 작성, 2026-11-01 종결)
- 관련 티켓: [RFP-15](RFP-15.md), [RFP-19](RFP-19.md), [BE-01](../backend/BE-01.md), [BE-02](../backend/BE-02.md), [BE-03](../backend/BE-03.md), [BE-09](../backend/BE-09.md), [BE-10](../backend/BE-10.md)
- 관련 문서: [PJ2-RFP.md 5.2절](../../P2-doc/PJ2-RFP.md#52-사전-주간-api-실측-확인과-실현-가능성-rfp-21), [PJ2-RFP.md 10장](../../P2-doc/PJ2-RFP.md#10-일정), [API 응답 확인](../../P2-doc/PJ2-API-응답확인.md), [API 엔티티·값](../../P2-doc/PJ2-API-엔티티.md), [e약은요 명세 정리본 5장 (3)](../../P2-doc/IROS_239_e약은요_서비스_v1.0.md#3-실제-응답-확인-결과-2026-11-01)
- 관련 코드·자료: [목 픽스처 목록](../../tests/fixtures/api/manifest.json), [필드 조사](../../tests/fixtures/api/field_survey.json), [캡처 스크립트](../../scripts/api_probe/capture_fixtures.py), [프로브](../../scripts/api_probe/probe.py), [FastAPI 앱(/mock)](../../scripts/api_probe/app.py)

## 메모
- RFP-01은 2026-11-01 닫혔고 RFP 5.2절은 그 뒤 RFP-21로 추가된 내용이다. RFP-01의 사용자 확인 범위에 들지 않으므로 별도 확인이 필요하다.
- 완료 조건 중 사실 확인 5건은 실행·확인으로 이미 충족해 체크했다. 사용자 확인 2건이 남아 status는 doing이다. 사용자가 확인했다고 알려주기 전에는 done으로 바꾸지 않는다.
- 이 티켓에서 확인한 항목은 BE-01·BE-02·BE-03의 일부 체크박스에 "(Pre-Week RFP-21에서 확인)"으로 연결했다. 그 티켓들의 나머지 W1 구현 조건은 미완이다.
- 가정: 우선순위는 `필수`(사용자 지시). `rfp` 항목은 사용자 지시대로 `5.2`, `10장`으로 적었다.
- 2026-11-01 연결 문서: 응답 값·엔티티 `P2-doc/PJ2-API-엔티티.md`, 목 픽스처 `tests/fixtures/api/`(9건), 서비스별 요약 `P2-doc/PJ2-API-응답확인.md`, RFP 기록 `P2-doc/PJ2-RFP.md` 5.2절. 사용자 결정 2건(허가정보 API 활용신청 시점, 파일↔API 성분 연결 규칙)의 근거 실측: 영문 성분명 정규화 일치 임부 64%·병용 36%, 품목 `EDI_CODE` 표본 8개 중 4개, 허가정보 API는 현재 키로 403(키 미등록). 정정: 앞서 "문자열 null"로 적은 것은 착오이고 실제는 JSON null이다.
