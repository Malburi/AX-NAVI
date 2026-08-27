---
name: impact
description: 영향도 분석 단축 호출(별칭). "/impact [대상]" 요청 시 total-ito:analyze-impact(변경 대상의 직간접 영향·위험도 분석)로 위임한다.
---

# /impact — analyze-impact 별칭

이 스킬이 호출되면 **즉시 Skill 도구로 `total-ito:analyze-impact`를 호출**하고, 사용자가 `/impact` 뒤에 쓴 내용 전부를 args로 그대로 전달한다. 절차는 전적으로 analyze-impact 본편을 따른다.

예: `/impact ORDER 테이블에 STATUS 컬럼 추가` → `Skill(skill="total-ito:analyze-impact", args="ORDER 테이블에 STATUS 컬럼 추가")`
