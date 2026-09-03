---
name: wiki
description: 프로젝트 위키 생성/갱신 단축 호출(별칭). "/wiki" 요청 시 ax-navi:generate-wiki(하네스 산출물 기반 위키 페이지 세트 생성, call graph 시각화 포함)로 위임한다.
---

# /wiki — generate-wiki 별칭

이 스킬이 호출되면 **즉시 Skill 도구로 `ax-navi:generate-wiki`를 호출**하고, 사용자가 `/wiki` 뒤에 쓴 내용 전부를 args로 그대로 전달한다. 절차는 전적으로 generate-wiki 본편을 따른다.
