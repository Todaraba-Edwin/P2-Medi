# prompts/

프롬프트·도구 설명 파일을 두는 곳이다(BE-15, RFP-29-01 A). 파일 이름에 버전을 붙인다: `agent_system@v1.md`, `tool_check_contraindications@v1.md`.

- 내용을 바꾸면 새 버전 파일을 만든다(`@v2`). 로그의 `prompt_version`에 이 이름을 적는다.
- `llm_cache`는 프롬프트 파일 내용 해시를 키에 넣으므로 고치면 캐시가 무효가 된다.
- 비밀값·실제 사용자 질문을 넣지 않는다.
