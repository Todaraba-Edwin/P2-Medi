# PJ2 API 엔티티 · 응답 값과 구조

## Index
- [1. 이 문서와 연결](#1-이-문서와-연결)
- [2. 공통 응답 구조](#2-공통-응답-구조)
- [3. e약은요 엔티티](#3-e약은요-엔티티)
- [4. DUR 품목정보 엔티티](#4-dur-품목정보-엔티티)
- [5. DUR 성분정보 엔티티](#5-dur-성분정보-엔티티)
- [6. 엔티티 관계와 연결 키](#6-엔티티-관계와-연결-키)
- [7. 목 픽스처 9건](#7-목-픽스처-9건)
- [8. 정규화 규칙과 열린 항목](#8-정규화-규칙과-열린-항목)

> 2026-11-01 실제 호출로 확인한 값이다. 필드 의미는 응답에서 관찰한 사실을 우선하고, 명세서가 없어 짐작한 것은 "추정"으로 표시했다(DUR 명세서는 아직 받지 못했다). 인증키는 문서와 픽스처에 없다.

## 1. 이 문서와 연결

| 자료 | 위치 | 쓰임 |
|---|---|---|
| 추적 티켓 | `tickets/doc/RFP-21.md` | 사전 주간 API 실측 확인 |
| RFP 기록 | `P2-doc/PJ2-RFP.md` 5.2절 | 실측 결과와 실현 가능성 판정 |
| 서비스별 응답 요약 | `P2-doc/PJ2-API-응답확인.md` | 오퍼레이션, 건수, 키 상태 |
| 목 픽스처 | `tests/fixtures/api/` | 실제 응답 9건. `manifest.json`이 목록 |
| 필드 조사 | `tests/fixtures/api/field_survey.json` | 오퍼레이션별 필드 이름·타입·채움 비율 |
| 캡처 스크립트 | `scripts/api_probe/capture_fixtures.py` | 픽스처를 다시 만든다 |
| FastAPI 목 | `scripts/api_probe/app.py`의 `/mock`, `/mock/{service}/{case}` | API 호출·한도 없이 픽스처를 돌려줌 |

## 2. 공통 응답 구조

세 서비스 모두 data.go.kr 공통 형식이다.

```
{ "header": { "resultCode": "00", "resultMsg": "NORMAL SERVICE." },
  "body":   { "pageNo": 1, "totalCount": N, "numOfRows": 3, "items": [ ... ] } }
```

| 항목 | 내용 |
|---|---|
| 요청 공통 | `serviceKey`, `pageNo`, `numOfRows`(100까지 확인), `type=json` |
| e약은요·품목정보 `items` | 객체의 배열 `[{...}, {...}]` |
| 성분정보 `items` | `[{"item": {...}}, ...]`로 한 겹 더 싸여 있다 |
| 결과 0건 | `items` 키가 **없다**(`totalCount: 0`). 빈 배열이 아니다. 픽스처 `eyak/empty_rx_methotrexate` |
| 오류 | HTTP 400·403과 `OpenAPI_ServiceResponse.cmmMsgHeader{errMsg, returnAuthMsg, returnReasonCode}`. 확인한 것: 서비스·오퍼레이션 없음 `NO_OPENAPI_SERVICE_ERROR`(코드 12), 키 미등록 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`. 나머지 코드는 명세서 3장 표를 따른다 |
| 시간 | 대부분 0.3~0.7초, 품목정보 병용금기만 약 3초 |

## 3. e약은요 엔티티

서비스 `DrbEasyDrugInfoService`, 오퍼레이션 `getDrbEasyDrugList`. **엔티티 하나: 의약품 개요(DrugEasyInfo)**. 전체 4,746건, 일반의약품 위주이고 전문의약품은 없다.

| 필드 | 타입 | 의미 | 예 / 비고 |
|---|---|---|---|
| `itemSeq` | 문자열 | 품목기준코드(9자리). **다른 서비스와 잇는 키** | `202005623` |
| `itemName` | 문자열 | 제품명 | `어린이타이레놀산160밀리그램(아세트아미노펜)` |
| `entpName` | 문자열 | 업체명 | |
| `efcyQesitm` | 문자열 | 효능 | 문장형 |
| `useMethodQesitm` | 문자열 | 사용법(연령별 용법 포함) | `만 7~12세 소아는 …` |
| `atpnWarnQesitm` | 문자열 | 경고 | |
| `atpnQesitm` | 문자열 | 주의사항 | |
| `intrcQesitm` | 문자열 | 상호작용 | |
| `seQesitm` | 문자열 | 부작용 | |
| `depositMethodQesitm` | 문자열 | 보관법 | 개행 포함 |
| `openDe` | 문자열 | 공개일자 | `20241231` (YYYYMMDD) |
| `updateDe` | 문자열 | 수정일자 | `2026-10-22` (**YYYY-MM-DD, openDe와 형식이 다르다**) |
| `itemImage` | 문자열/null | 제품 이미지 주소 | 7건 중 3건이 null |
| `bizrno` | 문자열 | 사업자등록번호 | |

- **성분 필드가 없다.** 성분은 DUR 품목정보와 `itemSeq`로 연결한다.
- 필터: `itemName`(포함 검색), `entpName`(업체명). `trustEntpName`, `startPage`는 동작하지 않는다.
- 3건 사례: `hit_tylenol`(7건), `empty_rx_methotrexate`(0건), `page2_no_filter`(전체 4,746건, 2쪽).

## 4. DUR 품목정보 엔티티

서비스 `DURPrdlstInfoService03`. 오퍼레이션 9개이고 엔티티는 둘로 나뉜다. **품목(Product)**과 **품목에 걸린 제한(Restriction)**이다. 제한은 DUR 유형마다 필드가 조금씩 다르다.

### (1) 품목 Product: `getDurPrdlstInfoList03`

전문의약품이 포함된다(메토트렉세이트 21품목, 알렌드론 31품목).

| 필드 | 의미 | 예 / 비고 |
|---|---|---|
| `ITEM_SEQ` | 품목기준코드. e약은요 `itemSeq`와 같은 코드 | |
| `ITEM_NAME`, `ENTP_NAME` | 품목명, 업체명 | |
| `ETC_OTC_CODE` | 전문/일반 구분. **이름은 코드인데 값은 이름** | `전문의약품`, `일반의약품` |
| `CLASS_NO` | 분류번호와 분류명 | `[114]해열.진통.소염제` |
| `MATERIAL_NAME` | 원료 성분 문자열(쉼표 구분) | `메토트렉세이트,,25,밀리그램,USP,` |
| `EE_DOC_ID`, `UD_DOC_ID`, `NB_DOC_ID` | 효능효과, 용법용량, **사용상의 주의사항** 문서. **이름은 ID인데 값은 nedrug PDF 주소** | 본문은 주지 않는다 |
| `EDI_CODE` | 보험 EDI 코드(KIDS 제품코드와 연결 후보) | 5건 중 1건만 채워짐 |
| `ITEM_PERMIT_DATE`, `CHANGE_DATE` | 허가일, 변경일 | `2021August23rd` (**영문 월 표기**) |
| `CANCEL_NAME` | 취하/취소 상태 | `정상` |
| `TYPE_CODE`, `TYPE_NAME  ` | DUR 유형 표시(추정). **키 이름 끝에 공백이 있다** | `D`, `용량주의` |
| `CHART`, `BAR_CODE`, `STORAGE_METHOD`, `INSERT_FILE`, `VALID_TERM`, `REEXAM_*`, `PACK_UNIT`, `BIZRNO` | 성상, 바코드, 보관, 첨부문서, 유효기간 등 | 일부 null |

사례: `dur-item/product_tylenol`(5건).

### (2) 제한 Restriction(품목 단위): 특정연령대·임부·노인·용량·투여기간

공통 필드(21개): `TYPE_NAME`(DUR 유형명), `MIX_TYPE`(단일/복합), **`INGR_CODE`**(성분코드, `D000147` 형식), `INGR_NAME`, `INGR_ENG_NAME`, `INGR_ENG_NAME_FULL`(`Acetaminophen(아세트아미노펜)`), `MIX_INGR`(복합제 성분, null 가능), `FORM_NAME`(제형), `ITEM_SEQ`, `ITEM_NAME`, `ITEM_PERMIT_DATE`, `ENTP_NAME`, `CHART`, `CLASS_CODE`, `CLASS_NAME`, `ETC_OTC_NAME`, `MAIN_INGR`(`[M040353]아세트아미노펜`, 주성분 코드와 이름), **`NOTIFICATION_DATE`**(고시일자, `20140109`), **`PROHBT_CONTENT`**(내용, 개행 포함 가능), `REMARK`(비고, null 가능), `CHANGE_DATE`.

- **품목정보의 임부금기에는 `GRADE`가, 연령금기에는 `AGE_BASE`가, 용량주의에는 `MAX_QTY`가, 투여기간주의에는 `MAX_DOSAGE_TERM`이 없다.** 구조화된 값은 성분정보 API(5장)와 KIDS 파일에만 있고, 품목정보에서는 `PROHBT_CONTENT` 문장으로만 온다.
- 서방정분할주의(`getSeobangjeongPartitnAtentInfoList03`)는 16개 필드이고 `INGR_CODE`가 없다.
- 효능군중복(`getEfcyDplctInfoList03`)은 28개 필드이고 `EFFECT_NAME`(`해열진통소염제`), `SERS_NAME`(`아닐리드계 해열진통제`), `FORM_CODE(_NAME)`, `DUR_SEQ`가 더해진다.
- 필터: `itemName`, `itemSeq`.
- 사례: `dur-item/age_taboo_tylenol`(특정연령대금기, 1건).

### (3) 병용금기 UsjntTaboo(품목 단위): `getUsjntTabooInfoList03`

한 행이 **두 품목의 쌍**이다(43개 필드). 한쪽(A)은 접두사 없는 필드(`INGR_CODE`, `ITEM_SEQ`, `ITEM_NAME` …), 다른 쪽(B)은 `MIXTURE_` 접두사 필드(`MIXTURE_INGR_CODE`, `MIXTURE_ITEM_SEQ` …)다. 공통으로 `DUR_SEQ`, `MIXTURE_DUR_SEQ`, `TYPE_CODE`(`A`), `NOTIFICATION_DATE`, `PROHBT_CONTENT`(예 `간 독성`), `REMARK`(예 `methotrexate (1週에 15mg 이상 투여시)`), `CHANGE_DATE`가 있다.

- `itemSeq` 필터가 동작한다(메토트렉세이트 주사제 `197900070` → 460건). `itemName=타이레놀`은 0건이고 응답이 약 3초 걸린다.
- 사례: `dur-item/usjnt_methotrexate_injection`.

## 5. DUR 성분정보 엔티티

서비스 `DURIrdntInfoService03`, 오퍼레이션 이름은 `…List02`. **성분 단위**이고 성분코드는 `D######` 형식이다. 엔티티는 **성분 제한(IngredientRestriction)** 하나이며 유형마다 전용 필드가 있다.

| 오퍼레이션 | 전체 건수 | 공통 필드에 더해지는 전용 필드 |
|---|---|---|
| `getUsjntTabooInfoList02` 병용금기 | 1,836 | 쌍 구조: A `INGR_*`, `ORI`, `CLASS`, `MIX_TYPE`, `MIX` / B `MIXTURE_*` (19개 필드) |
| `getPwnmTabooInfoList02` 임부금기 | 1,459 | **`GRADE`**(`1등급`) |
| `getSpcifyAgrdeTabooInfoList02` 특정연령대금기 | 233 | **`AGE_BASE`**(`18세 이하`) |
| `getCpctyAtentInfoList02` 용량주의 | 708 | **`MAX_QTY`**(`0.25밀리그램`) |
| `getMdctnPdAtentInfoList02` 투여기간주의 | 98 | **`MAX_DOSAGE_TERM`**(`21일`) |
| `getEfcyDplctInfoList02` 효능군중복 | 406 | `EFFECT_CODE`(**값은 이름**, `해열진통소염제`), `SERS_NAME` |
| `getOdsnAtentInfoList02` 노인주의 | 112 | 없음(`FORM_NAME`은 비어 있음) |

- 단일 제한의 공통 필드(13~15개): `DUR_SEQ`, `TYPE_NAME`, `MIX_TYPE`, `INGR_CODE`(`D000762`), `INGR_ENG_NAME`, `INGR_NAME`, `MIX_INGR`, `ORI_INGR`(원료 코드 목록), `CLASS_NAME`, `FORM_NAME`, `NOTIFICATION_DATE`, `PROHBT_CONTENT`, `REMARK`, `DEL_YN`(관찰한 값은 `정상`뿐. 삭제 표시일 것으로 추정).
- 필터: **`ingrCode`만 동작**한다(`D000762` → 19건). `ingrName`, `ingrEngName`은 무시되어 전체가 돌아온다. KIDS 형식 코드(`192101ATB`)를 넣으면 0건이다.
- 사례: `dur-ingr/usjnt_itraconazole`(병용 19건), `dur-ingr/pwnm_grade`(임부 + 등급), `dur-ingr/age_base`(연령 기준).

## 6. 엔티티 관계와 연결 키

```
e약은요 DrugEasyInfo ──itemSeq = ITEM_SEQ──▶ DUR Product ──ITEM_SEQ──▶ 품목 단위 Restriction ─┐
   (성분 없음)                              (MATERIAL_NAME, EDI_CODE)                         INGR_CODE (D######)
                                                                                                │
                              성분정보 IngredientRestriction (병용·임부·연령·노인·용량·투여기간·효능군) ◀─┘

KIDS 파일(성분코드 100501ATE 형식, 제품코드) ── ? ──▶ DUR API   ← 직접 같은 코드가 아니다
```

| 연결 | 실측 | 판단 |
|---|---|---|
| e약은요 ↔ 품목정보 | 같은 품목기준코드(`itemSeq` = `ITEM_SEQ`) | 연결된다 |
| 품목 ↔ 성분 | 품목 단위 제한 응답에 `INGR_CODE`가 있다 | 연결된다 |
| KIDS 파일 ↔ API, **영문 성분명** | 임부금기: API 1,206개 중 정규화 후 정확 일치 770(64%), 접두 일치까지 934(77%). 병용금기: API 475개 중 170(36%) | 일부만 이어진다 |
| KIDS 파일 ↔ API, **품목** | KIDS 제품코드를 품목정보 `EDI_CODE`와 대조: 표본 8개 중 4개 일치. `ITEM_SEQ`와는 0개 | 제품코드는 `ITEM_SEQ`가 아니라 EDI 코드로 보인다. 표본이 작다 |

- 두 목록의 수록 범위와 표기가 달라서(예: `abacavir`는 API에 있고 KIDS 임부금기 CSV에는 없음) 일치율이 낮은 원인은 확인하지 못했다(가정).
- 따라서 파일과 API의 비교는 같은 코드의 일치가 아니라 영문 성분명 정규화 + 품목(`EDI_CODE`) 연결을 합친 **부분 비교**가 되며, 이어지지 않는 경우는 "비교 불가"로 표시해야 한다(RFP 5.1절 (7)의 관찰값).

## 7. 목 픽스처 9건

각 서비스에서 실제 호출 3건씩이다(`tests/fixtures/api/manifest.json`, 캡처 2026-11-01).

| 서비스 | 사례(파일) | 호출 | 보여 주는 것 |
|---|---|---|---|
| e약은요 | `eyak/hit_tylenol` | `itemName=타이레놀` | 정상 응답(7건), 문장형 필드 7개, 일부 null |
| e약은요 | `eyak/empty_rx_methotrexate` | `itemName=메토트렉세이트` | 0건 응답에 `items` 키가 없음 |
| e약은요 | `eyak/page2_no_filter` | `pageNo=2` | 전체 4,746건과 페이지 이동 |
| 품목정보 | `dur-item/product_tylenol` | `getDurPrdlstInfoList03` | 품목 필드 25개, 영문 월 날짜, 키 이름 공백 |
| 품목정보 | `dur-item/age_taboo_tylenol` | `getSpcifyAgrdeTabooInfoList03` | 제한 필드 21개, 고시일자, 문장형 내용 |
| 품목정보 | `dur-item/usjnt_methotrexate_injection` | `getUsjntTabooInfoList03`, `itemSeq` | 병용 쌍 43개 필드, A/`MIXTURE_` 구조, 460건 |
| 성분정보 | `dur-ingr/usjnt_itraconazole` | `getUsjntTabooInfoList02`, `ingrCode=D000762` | `{"item": …}` 한 겹, 성분 쌍, 19건 |
| 성분정보 | `dur-ingr/pwnm_grade` | `getPwnmTabooInfoList02` | 임부 등급 `GRADE`, 1,459건 |
| 성분정보 | `dur-ingr/age_base` | `getSpcifyAgrdeTabooInfoList02` | 연령 기준 `AGE_BASE`, 233건 |

W1에서 클라이언트 단위 테스트는 이 파일들을 입력으로 쓰고, 개발 중에는 FastAPI `/mock`으로 API 호출 없이 돌릴 수 있다. 평가는 파일 기준이라 API를 끈다는 원칙(RFP 5.1절 (7))과도 맞는다.

## 8. 정규화 규칙과 열린 항목

### (1) 클라이언트가 정규화할 것

| 항목 | 내용 |
|---|---|
| 결과 0건 | `items` 키가 없으면 빈 목록으로 본다 |
| `items` 한 겹 | 성분정보는 `{"item": …}`를 벗긴다 |
| JSON null | 선택 필드는 null이 오므로 null을 허용하는 모델로 받는다(문자열 `"null"`은 오지 않았다) |
| 키 이름 공백 | `"TYPE_NAME  "`처럼 끝 공백이 있는 키는 다듬는다 |
| 날짜 | 세 형식이 섞여 있다: `20140109`, `2026-10-22`, `2021August23rd` |
| 이름과 값 불일치 | `ETC_OTC_CODE`, `EFFECT_CODE`는 값이 이름이고 `EE_DOC_ID`·`NB_DOC_ID`는 값이 주소다 |
| 문장 끝 개행 | `PROHBT_CONTENT` 등에 개행이 붙을 수 있다 |

### (2) 열린 항목

1. DUR 명세서를 받지 못해 `TYPE_CODE`, `DEL_YN`, `CLASS_NO` 같은 필드의 공식 의미는 확인하지 못했다.
2. 허가정보 API는 현재 키로 호출하면 403(키 미등록)이다. 활용신청 시점은 사용자 결정이다(RFP 5.2절).
3. 품목 연결(`EDI_CODE`)의 일치율은 표본 8개 기준이다. 더 큰 표본으로 다시 재야 한다.
