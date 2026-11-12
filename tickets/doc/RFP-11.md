---
id: RFP-11
label: RFP
title: 비기능 재현성(같은 평가 세트 반복 측정) 추적
sch: SCH-01
status: done
priority: 필수
rfp: [NFR-재현성]
created: 2026-10-30
done: 2026-11-12
---

# RFP-11 · 비기능 재현성 추적

## Index
- [1. 이슈](#1-이슈)
- [2. 완료 조건](#2-완료-조건)
- [3. 하위 작업](#3-하위-작업)
- [4. 관련](#4-관련)
- [5. 메모](#5-메모)

## 1. 이슈
RFP 7장: "재현성: 같은 평가 세트로 개선 전후를 반복 측정 가능". 평가 세트를 버전 고정해 두는 것이 1주차 목표다.

## 2. 완료 조건
- [x] (2026-11-12, AG-04 done 2026-11-12, `git ls-files`로 `evaluation/eval_set/dev_set.jsonl`·`manifest.json` 추적 확인, 시험셋 파일 자체는 로컬 전용이라 해시만 커밋, §5 기록 참조) AG-04가 done이고 평가 세트 파일이 저장소에 버전 관리되고 있다.
- [x] (2026-11-12, §5 "세트 경로·버전·해시 기록") 세트 파일 경로와 버전(또는 커밋)을 `메모`에 기록했다.

## 3. 하위 작업
- [x] AG-04 완료 확인 (2026-11-12 done)
- [x] 세트 버전 기록 (2026-11-12, §5)

## 4. 관련
- 선행: AG-04
- 관련 문서: `P2-doc/PJ2-RFP.md` 7장, 9장

## 5. 메모
- 가정: LLM 호출 비결정성은 2주차 BE-08에서 설정(온도 등)으로 다룬다.
- 2026-11-11 진행 메모(상태 변경 없음): 선행 AG-04는 done이 아니다. 개발셋 `dev_golden`·`dev_reliability_core` 표시와 매니페스트 sha256(개발·시험)은 갖췄으나 Upstage 주 생성기 요건과 시험셋 확인 2건이 남아 있고, 개발셋 정답 수정(AG-04-01 대기)이 승인되면 개발셋 sha256이 바뀐다(측정 시작 전이라 허용). 평가 세트 버전 고정 확인은 AG-04 done 뒤에 한다.
- 2026-11-12 **세트 경로·버전·해시 기록(AG-04 done 반영, schedule-writer, 지시서 `2026-11-12-sw-w1-close.md`)**: 근거는 커밋된 `evaluation/eval_set/manifest.json`이다(시험셋 파일은 열지 않았다, RFP-26-04).
  - 세트 버전 `set_version`: `ag04-v0.1-draft`(manifest `last_updated` 2026-11-11, 사유: BE-05-08 B 병용 기준일 07-31 반영·정답 판정 불변).
  - 개발셋: 경로 `evaluation/eval_set/dev_set.jsonl`(커밋됨), 150문항, sha256 `bc51d083b1df310f8d589475acde6a6dbf171935a770e8c3c217726e0dc26ee3`(파일을 직접 해시해 manifest와 일치 확인).
  - 시험셋: 경로 `evaluation/eval_set/test_set.SEALED.jsonl`(**로컬 전용, 커밋 안 함**, `.gitignore`), 151문항(9.2절 150 + 확장 1), sha256 `79affcf29e27eb418edb494f5bfb3631ef3eace06e79e01e9dc5421b7c13632f`(manifest 값만 읽음, 파일은 열지 않아 해시 재계산은 하지 않음).
  - 커밋: `7beb7ae`(`git log -1 --format=%h -- evaluation/eval_set/manifest.json`, `dev_set.jsonl`도 같은 커밋).
  - 해석 불확실: 이 티켓 조건 "평가 세트 파일이 저장소에 버전 관리"를 개발셋·manifest(해시)·빌더 기준으로 읽었다. 시험셋 파일 자체는 2026-11-10 사용자 결정으로 저장소 밖이라 해시로만 고정된다. 측정 시작 뒤 세트 변경 금지(RFP-34-04, CLAUDE.md 5장)는 이 티켓이 아니라 AG-11 시작에서 시작한다.
