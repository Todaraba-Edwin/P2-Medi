# PJ2 API 응답 확인 · e약은요와 DUR 두 서비스

## Index
- [1. 확인 방법](#1-확인-방법)
- [2. 결과 요약](#2-결과-요약)
- [3. 서비스별 응답](#3-서비스별-응답)
- [4. 설계에 영향을 주는 사실](#4-설계에-영향을-주는-사실)
- [5. 열린 항목](#5-열린-항목)
- [6. 다시 실행하는 법](#6-다시-실행하는-법)

> 관련: [RFP-21](../tickets/doc/RFP-21.md) · [RFP 5.2절](PJ2-RFP.md#52-사전-주간-api-실측-확인과-실현-가능성-rfp-21) · [API 엔티티·값](PJ2-API-엔티티.md) · [목 픽스처](../tests/fixtures/api/manifest.json) · [프로브](../scripts/api_probe/probe.py)
> 2026-11-01 실제 호출로 확인한 값이다. 인증키는 `.env`에서 환경변수로만 읽었고 이 문서와 저장소에는 키 값이 없다. 원본 응답은 `data/api_samples/`(git 제외)에 있다. 응답은 시간이 지나면 바뀔 수 있다.

## 1. 확인 방법

- FastAPI 프로브(`scripts/api_probe/`)로 세 서비스를 호출했다. `/battery`가 항목별 호출을 한꺼번에 실행하고 `/probe/{service}/{operation}`이 한 건씩 호출한다.
- 호출은 약 60회이고, 개발계정 일일 한도(10,000)에 비해 작다.
- 이 확인은 BE-01(FastAPI 초기화), BE-02, BE-03의 응답 샘플 확인에 해당한다.

## 2. 결과 요약

| 서비스 | 환경변수 접두사 | 결과 |
|---|---|---|
| 의약품개요정보(e약은요) | `DRDEASYDRUG_*` | 정상. 전체 4,746건. **성분 필드가 없고 전문의약품이 없다** |
| DUR 품목정보 | `DURPrdlstInfoService03_*` | 정상. 오퍼레이션 9개 모두 응답. 전문의약품 포함 |
| DUR 성분정보 | `DURIrdntInfoService03_*` | 정상(2026-11-01 키 교체 후). 오퍼레이션 이름은 `…02`. 교체 전에는 키 길이가 70이라 403(키 미등록)이었다 |

## 3. 서비스별 응답

### (1) e약은요 `getDrbEasyDrugList`

- 필드(14개): `entpName`, `itemName`, `itemSeq`, `efcyQesitm`(효능), `useMethodQesitm`(사용법), `atpnWarnQesitm`(경고), `atpnQesitm`(주의사항), `intrcQesitm`(상호작용), `seQesitm`(부작용), `depositMethodQesitm`(보관), `openDe`, `updateDe`, `itemImage`, `bizrno`.
- `itemName=타이레놀` 7건, 필터 없이 `totalCount` 4,746건. 응답 시간 약 0.5초.
- **성분 필드(성분명·성분코드)가 없다.** 연결 키는 `itemSeq`(품목기준코드)다.
- **전문의약품이 없다.** `메토트렉세이트`, `알렌드로네이트`, `포사맥스`, `포사맥스플러스`, `마빌`, `엠티엑스`, `메토젝트`는 모두 0건이다.

### (2) DUR 품목정보 `DURPrdlstInfoService03`

| 오퍼레이션 | 의미 | `itemName=타이레놀` 결과 |
|---|---|---|
| `getDurPrdlstInfoList03` | 품목 정보 | 5건 |
| `getUsjntTabooInfoList03` | 병용금기 | 0건 (응답 약 3초로 느림) |
| `getSpcifyAgrdeTabooInfoList03` | 특정연령대금기 | 1건 |
| `getPwnmTabooInfoList03` | 임부금기 | 0건 |
| `getOdsnAtentInfoList03` | 노인주의 | 0건 |
| `getCpctyAtentInfoList03` | 용량주의 | 4건 |
| `getMdctnPdAtentInfoList03` | 투여기간주의 | 0건 |
| `getEfcyDplctInfoList03` | 효능군중복 | 3건 |
| `getSeobangjeongPartitnAtentInfoList03` | 서방정분할주의 | 1건 |

- 품목 정보 필드: `ITEM_SEQ`, `ITEM_NAME`, `ENTP_NAME`, `ITEM_PERMIT_DATE`, `ETC_OTC_CODE`(전문/일반), `CLASS_NO`, `MATERIAL_NAME`(성분 문자열, 예 `메토트렉세이트,,25,밀리그램,USP,`), `EE_DOC_ID`·`UD_DOC_ID`·`NB_DOC_ID`(효능효과·용법용량·사용상의 주의사항 문서 ID), `EDI_CODE`, `CHANGE_DATE` 등.
- 전문의약품이 있다: `메토트렉세이트` 21품목, `알렌드론` 31품목.
- 금기·주의 응답 공통 필드: `INGR_CODE`(예 `D000147`), `INGR_NAME`, `ITEM_SEQ`, `ITEM_NAME`, `NOTIFICATION_DATE`(고시일자, `YYYYMMDD`), `PROHBT_CONTENT`(내용), `REMARK`, `CHANGE_DATE`.
- 필터: `itemName`이 동작하고, `itemSeq`도 동작한다(메토트렉세이트 주사제 `itemSeq`로 병용금기 460건).
- 주의: 품목정보 상세 응답의 키 `"TYPE_NAME  "`는 끝에 공백이 있다. 선택 필드는 문자열이 아니라 JSON null로 온다(2026-11-01 정정: 앞서 "문자열 `"null"`"이라 적은 것은 프로브가 null을 문자열로 출력한 착오였다). 날짜 표기는 세 가지가 섞여 있다(`20140109`, `2026-10-22`, `1979January9th`).

### (3) DUR 성분정보 `DURIrdntInfoService03`

| 오퍼레이션 | 의미 | 전체 건수 |
|---|---|---|
| `getUsjntTabooInfoList02` | 병용금기 | 1,836 |
| `getSpcifyAgrdeTabooInfoList02` | 특정연령대금기 | 233 |
| `getPwnmTabooInfoList02` | 임부금기 | 1,459 |
| `getOdsnAtentInfoList02` | 노인주의 | 112 |
| `getCpctyAtentInfoList02` | 용량주의 | 708 |
| `getMdctnPdAtentInfoList02` | 투여기간주의 | 98 |
| `getEfcyDplctInfoList02` | 효능군중복 | 406 |

- 서비스 이름은 `…Service03`인데 오퍼레이션 이름은 `…List02`로 끝난다. `…List03`은 "서비스 없음(400)"이 나온다. 서방정분할주의는 이 서비스에 없다.
- 응답은 `items` 안에 `{"item": {...}}`가 한 겹 더 싸여 있다.
- 필드: 병용금기는 `INGR_CODE`·`INGR_KOR_NAME`과 상대 성분 `MIXTURE_INGR_CODE`·`MIXTURE_INGR_KOR_NAME`·`PROHBT_CONTENT`·`NOTIFICATION_DATE`·`DEL_YN`, 임부금기는 `GRADE`(예 `1등급`), 특정연령대금기는 `AGE_BASE`, 용량주의는 `MAX_QTY`를 갖는다.
- 필터: `ingrCode`(`D000762` 형식)가 동작한다. `ingrName`, `ingrEngName`은 무시되어 전체가 돌아온다.
- **키**: 처음 `.env`의 성분정보 키는 길이 70이었고 403(`SERVICE_KEY_IS_NOT_REGISTERED_ERROR`)이었다. 2026-11-01 사용자가 키를 교체한 뒤 길이 64의 계정 키(세 서비스가 같은 값)가 되어 성분정보 오퍼레이션 7개가 모두 자기 키로 정상 응답한다(전체 21회 호출 실패 0건).

## 4. 설계에 영향을 주는 사실

1. **e약은요에는 성분이 없다.** RFP 5장의 "제품명·성분·효능·주의사항"은 사실과 다르다. 성분은 DUR 품목정보(`MATERIAL_NAME`, `INGR_CODE`)나 KIDS 제품 쌍에서 얻고, e약은요와는 `itemSeq` ↔ `ITEM_SEQ`로 잇는다. BE-02·BE-10·BE-12에 영향이 있다.
2. **전문의약품은 e약은요에 없다.** 가설 문서 TC-14·15의 약(메토트렉세이트, 알렌드로네이트)은 e약은요에서 라벨 문장을 얻을 수 없다. DUR 품목정보는 사용상의 주의사항을 문서 ID(`NB_DOC_ID`)로만 가리킨다. 본문이 필요하면 의약품 제품 허가정보 API(RFP 5.1 (4), 미신청)가 후보다. "TC-14·15가 실패할 때 신청"이라는 설계 결정 4를 "이미 실패가 예상된다"는 근거로 다시 볼 수 있다.
3. **성분코드 체계가 두 가지다.** DUR API는 `D000147` 형식이고 KIDS 파일은 `100501ATE`·`192101ATB` 형식이다. RFP 5.1 (7)의 "파일과 API 일치율"을 같은 성분코드의 일치로 정의할 수 없다. 영문 성분명 정규화나 품목 단위(`ITEM_SEQ`) 연결이 필요하다.
4. **고시일자 필드가 있다.** 5.1 (7)의 "확인 전 사항"에 답한다. API 응답에 `NOTIFICATION_DATE`가 있어 "API가 파일보다 최신"인지 비교할 수 있다. 다만 두 값이 같은 기준인지는 아직 대조하지 않았다.
5. **연령금기 오퍼레이션**: 품목 단위는 `getSpcifyAgrdeTabooInfoList03`(`itemName`, `itemSeq`), 성분 단위는 `getSpcifyAgrdeTabooInfoList02`(`ingrCode`)다.
6. **병용금기 품목정보 API는 느리다**(약 3초). 평가에서 API를 끄는 설계(5.1 (7))와 맞다.
7. **응답 정규화가 필요하다**: 키 이름의 공백, 선택 필드의 JSON null, 날짜 표기 세 가지, `items` 한 겹 싸임, 결과 0건일 때 `items` 키 없음. 자세한 규칙은 `P2-doc/PJ2-API-엔티티.md` 8장.

## 5. 열린 항목

1. (해결, 2026-11-01) `.env`의 `DURIrdntInfoService03_API_KEY` 교체로 성분정보가 정상이다.
2. 허가정보 API(`DrugPrdtPrmsnInfoService08`) 활용신청 시점. 사용자 결정이 필요하다.
3. KIDS 제품코드와 DUR 품목정보 `EDI_CODE`가 같은 코드인지 대조(가정: 같다).
4. `NOTIFICATION_DATE`와 KIDS 고시일자·고시번호가 같은 기준인지 대조.
5. 임부금기(`getPwnmTabooInfoList03`), 노인주의, 투여기간주의의 0건은 `itemName=타이레놀` 결과일 뿐이다. 다른 약으로 필드를 더 확인한다.

## 6. 다시 실행하는 법

```
.venv/bin/uvicorn scripts.api_probe.app:app --port 8765
curl http://127.0.0.1:8765/battery
curl "http://127.0.0.1:8765/probe/dur-item/getSpcifyAgrdeTabooInfoList03?itemName=타이레놀"
```

또는 `.venv/bin/python scripts/api_probe/probe.py`. 결과 표는 `data/api_samples/report.md`에 쓴다.
