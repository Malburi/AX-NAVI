---
name: flow
description: 처리 흐름 추적 단축 호출(별칭). "/flow [기능·API·화면]" 요청 시 ax-navi:trace-logic(진입점부터 DB/외부 시스템까지 흐름 추적)으로 위임한다. (trace가 아닌 flow로 명명한 이유: 하네스가 프로젝트마다 로컬 trace 스킬을 배포하므로 이름 충돌 방지)
---

# /flow — trace-logic 별칭

이 스킬이 호출되면 **즉시 Skill 도구로 `ax-navi:trace-logic`을 호출**하고, 사용자가 `/flow` 뒤에 쓴 내용 전부를 args로 그대로 전달한다. 절차는 전적으로 trace-logic 본편을 따른다.

예: `/flow 로그인 처리` → `Skill(skill="ax-navi:trace-logic", args="로그인 처리")`
