---
name: modify
description: 수정 작업 단축 호출(별칭). "/modify [내용]" 요청 시 ax-navi:safe-modify(사전 영향 분석→적용→사후 안전성 평가)로 위임한다. "modify로 고쳐줘" 같은 표현도 트리거.
---

# /modify — safe-modify 별칭

이 스킬이 호출되면 **즉시 Skill 도구로 `ax-navi:safe-modify`를 호출**하고, 사용자가 `/modify` 뒤에 쓴 내용 전부를 args로 그대로 전달한다. 이 파일에서 절차를 재정의하지 않는다 — 절차는 전적으로 safe-modify 본편을 따른다.

예: `/modify 주문 취소 버튼 오류 고쳐줘` → `Skill(skill="ax-navi:safe-modify", args="주문 취소 버튼 오류 고쳐줘")`
