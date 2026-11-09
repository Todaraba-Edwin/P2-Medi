---
name: delegation-brief
description: 메인 pane이 긴 작업을 별도 pane의 서브에이전트에 맡길 때 쓰는 지시서 양식과 herdr pane 열기·시작·감시·종료 절차. 문서 작성, 조사, 코드 작성, 점검처럼 컨텍스트를 많이 쓰는 일을 위임할 때 쓴다.
---

# delegation-brief

> 출처: `CLAUDE.md` 2장 "herdr 환경에서의 실행 규칙"과 "메인 pane의 역할과 위임"을 절차로 요약했다. **위임 기준·에이전트/모델 표·시작 옵션은 `CLAUDE.md` 2장이 원본이므로 여기에 복제하지 않는다**(표는 그쪽을 읽는다). 등록 결정: RFP-30-03(2026-11-09).

## 1. 지시서 양식
지시서는 로컬 전용 `data/mock/briefs/{날짜}-{주제}.md`에 쓴다(`.gitignore` 대상, 커밋 안 함). pane에는 "지시서 경로를 읽고 수행하라"만 보낸다.

```
# 지시서: {제목} ({날짜})
(맥락 한두 줄. 비밀값 금지, .env 열지 않음, 커밋·push 하지 않음)

## 1. 목표
## 2. 먼저 읽을 파일
## 3. 고치지 않을 파일   (동시에 다른 pane이나 메인이 고치는 것)
## 4. 산출물 경로
## 5. 검증 방법          (check_schedule.py가 일시적으로 실패하면 그 이유)
## 6. 보고 형식          (아래)
```

보고 형식: `## <에이전트> 보고` 아래 작업, 변경 파일(신규·수정 개수와 경로), 확인한 것·확인하지 못한 것, 결정 현황(번호·질문·★), 가정·확인 필요, `check_schedule` 결과. 비용이 큰 호출은 지시서에 상한을 적는다.

## 2. herdr 절차 (요약)
1. `test "${HERDR_ENV:-}" = 1` 확인. 아니면 중단.
2. `herdr pane list`로 workspace와 `cwd`가 P2-Medi인지 보고, 메인 pane ID를 **명시**해 `herdr pane split <메인 pane ID> --direction right --cwd "$PWD" --no-focus`. `--current`와 `$HERDR_PANE_ID` 직접 사용은 피한다.
3. `herdr pane rename <pane> <에이전트 이름>`.
4. `herdr agent start <이름> --kind claude --pane <pane> -- --agent <이름> --permission-mode acceptEdits --disallowedTools 'Read(./.env)' 'Read(./.env.*)'` (`--model`은 CLAUDE.md 2장 표에 따른다).
5. `herdr agent prompt <이름> "<지시서 경로를 읽고 수행하라>"`. 완료 대기는 전경 `sleep` 대신 백그라운드 감시 루프(`herdr agent get <이름>`의 `agent_status`가 `working`이 아닐 때까지)를 쓴다.
6. `herdr agent read <이름> --source recent-unwrapped --lines 120`로 보고를 읽는다.
7. 검수는 가볍게: `git status`, `wc -l`, `grep -n '^## '`, `check_schedule.py`처럼 작은 사실 확인만 한다(CLAUDE.md 2장 4번).
8. `herdr pane close <pane>` 후 `herdr pane list`로 사라졌는지 확인.

## 3. 닫지 않는 경우
에이전트가 `working`·`blocked`이거나 timeout으로 끝났을 때, 사용자 답·승인이 필요할 때, pane 입력창에 사용자가 적은 내용이 있을 때. 승인 창에는 입력을 임의로 보내지 않고 사용자에게 알린다.

## 4. 주의
- 같은 파일을 두 pane이 동시에 고치지 않게 파일 소유를 나눈다.
- 같은 일에 여러 관점이 필요하면 회차마다 관점을 나누고 앞 회차 결론을 알려 주지 않는다(앵커링 방지).
- 새 에이전트 정의 파일은 만들지 않는다. 맞는 것이 없으면 전역·일반 에이전트를 쓴다.
