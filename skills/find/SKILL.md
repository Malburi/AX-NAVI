---
name: find
description: 기능/코드 위치 탐색 단축 호출(별칭). "/find [기능·키워드]" 요청 시 ax-navi:find-feature(관련 파일·클래스·메서드·SQL 목록 반환)로 위임한다.
---

# /find — find-feature 별칭

이 스킬이 호출되면 **즉시 Skill 도구로 `ax-navi:find-feature`를 호출**하고, 사용자가 `/find` 뒤에 쓴 내용 전부를 args로 그대로 전달한다. 절차는 전적으로 find-feature 본편을 따른다.

예: `/find 결제 승인 처리` → `Skill(skill="ax-navi:find-feature", args="결제 승인 처리")`
