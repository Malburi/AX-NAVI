---
name: sql
description: SQL 리뷰 단축 호출(별칭). "/sql [쿼리·SQL ID·DDL]" 요청 시 total-ito:review-sql(사용처·성능·보안·트랜잭션·스키마 영향 종합 리뷰)로 위임한다.
---

# /sql — review-sql 별칭

이 스킬이 호출되면 **즉시 Skill 도구로 `total-ito:review-sql`을 호출**하고, 사용자가 `/sql` 뒤에 쓴 내용 전부를 args로 그대로 전달한다. 절차는 전적으로 review-sql 본편을 따른다.

예: `/sql SELECT * FROM ORDERS WHERE STATUS = 'N'` → `Skill(skill="total-ito:review-sql", args="SELECT * FROM ...")`
