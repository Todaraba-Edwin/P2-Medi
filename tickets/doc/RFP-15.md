---
id: RFP-15
label: RFP
title: 1주차 결정사항 확정(LLM·Vector DB·PDF 파서·평가 문항 수)
sch: SCH-01
status: todo
priority: 필수
rfp: [RFP-8장, RFP-9장]
created: 2026-10-30
done: -
---

# RFP-15 · 1주차 결정사항 확정

## Index
- [이슈](#이슈)
- [완료 조건](#완료-조건)
- [하위 작업](#하위-작업)
- [관련](#관련)
- [메모](#메모)

## 이슈
RFP는 "후보 (1주차 확정)"로 LLM `[선택 예정]`, Vector DB(Chroma/Qdrant/pgvector), PDF 파싱(pdfplumber/LlamaParse)을 남겨 두었고, 평가 세트 세트별 `[__]`문항도 1주차 확정이다. 이 결정을 한 곳에 기록한다.

## 완료 조건
- [ ] LLM, Vector DB, PDF 파서 선택과 이유 한 줄씩이 `메모`에 기록되어 있다.
- [ ] 평가 세트 4종(정상/오탈자/범위 외/오정보)의 세트별 문항 수가 정해져 있다.
- [ ] 결정 내용이 PRD-01 또는 README에 반영되어 있다.

## 하위 작업
- [ ] LLM 선택
- [ ] Vector DB 선택
- [ ] PDF 파서 선택
- [ ] 세트별 문항 수 결정

## 관련
- 선행: 없음
- 관련 문서: `P2-doc/PJ2-RFP.md` 8장, 9장

## 메모
- 가정: 오케스트레이션 LangGraph, 백엔드 FastAPI, 평가 Ragas는 RFP에 단일 후보로 적혀 있어 확정으로 본다.
