"""`data/` 원본 파일 이름 상수(한 곳). 이름이 바뀌면 이 모듈만 고친다.

병용금기 JSON 이름은 사용자 지정 이름에서 공백 오타를 없애고 확장자 `.json`을 붙인 것이다(2026-11-11, 사용자 가정 승인 대기).
기준일은 파일 이름 끝 `_YYYYMMDD`에서 코드로 읽는다(`doc_meta.parse_base_date`).
"""

from __future__ import annotations

COMBO_JSON_NAME = "한국의약품안전관리원_병용금기약물(AI 학습용)_20260731.json"
PREG_CSV_NAME = "한국의약품안전관리원_임부금기약물_20260721.csv"
AGE_CSV_NAME = "한국의약품안전관리원_연령금기_20260721.csv"
DOSE_CSV_NAME = "한국의약품안전관리원_용량주의약물_20260721.csv"
LACT_CSV_NAME = "한국의약품안전관리원_수유부주의_20251127.csv"
GOSI_PDF_NAME = "「의약품 병용금기 성분 등의 지정에 관한 규정」 개정고시 전문.pdf"
