---
name: scaffold
description: 신규 기능 생성 단축 호출(별칭). "/scaffold [기능명]" 요청 시 total-ito:scaffold-feature(프로젝트 컨벤션 기반 신규 기능 스캐폴딩)로 위임한다.
---

# /scaffold — scaffold-feature 별칭

이 스킬이 호출되면 **즉시 Skill 도구로 `total-ito:scaffold-feature`를 호출**하고, 사용자가 `/scaffold` 뒤에 쓴 내용 전부를 args로 그대로 전달한다. 절차는 전적으로 scaffold-feature 본편을 따른다.

예: `/scaffold 주문 취소 기능` → `Skill(skill="total-ito:scaffold-feature", args="주문 취소 기능")`
