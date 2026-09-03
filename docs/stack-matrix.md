# Stack Matrix — 지원 스택 매트릭스

AX Navi가 자동 탐지/지원하는 스택 목록과 각 스택에서의 분석/QA 깊이.

---

## 탐지 시그니처

analyzer Step 1~2 에서 다음 파일/문자열로 자동 탐지:

### Java 계열

| 스택 | 탐지 시그니처 | 분석 깊이 |
|------|------------|---------|
| Maven Java | `pom.xml` | HIGH |
| Gradle Java | `build.gradle`, `build.gradle.kts` | HIGH |
| Spring Boot 2/3 | `pom.xml` + `spring-boot-starter-*` | HIGH |
| Spring Framework 3~4 | `pom.xml` + `spring-*` (no boot) | MEDIUM (레거시 패턴 다수) |
| Struts 1.x | `pom.xml` + `org.apache.struts:struts-core` 또는 `WEB-INF/struts-config.xml` | MEDIUM (XML→Action→forward 교차 QA 필요) |
| Struts 2.x | `pom.xml` + `org.apache.struts:struts2-core` | MEDIUM |
| Java EE Web | `WEB-INF/web.xml` | MEDIUM |
| EJB 2.x | `WEB-INF/web.xml` + `ejb-jar.xml` | LOW (레거시, 마이그레이션 대상) |
| MyBatis | `mybatis-spring`, `mybatis-config.xml`, `*Mapper.xml` | HIGH |
| iBatis (레거시) | `ibatis-sqlmap`, `sqlmap-config.xml` | MEDIUM (마이그레이션 대상) |
| JPA / Hibernate | `spring-data-jpa`, `hibernate-*`, `persistence.xml` | HIGH |
| 전자정부 표준프레임워크 | `org.egovframe` 또는 `egovframework.*` | MEDIUM |
| JSP/JSTL | `*.jsp`, `WEB-INF/jsp/*` | MEDIUM |

### Node.js 계열

| 스택 | 탐지 | 깊이 |
|------|------|------|
| Express | `package.json` + `express` | HIGH |
| NestJS | `@nestjs/core` | HIGH |
| Next.js | `next` + `next.config.*` | HIGH |
| Fastify | `fastify` | MEDIUM |
| Koa | `koa` | MEDIUM |
| TypeORM | `typeorm` | HIGH |
| Prisma | `prisma` + `schema.prisma` | HIGH |
| Sequelize | `sequelize` | MEDIUM |
| Mongoose | `mongoose` | MEDIUM |

### 프런트엔드 (SPA/SSR)

| 스택 | 탐지 | 깊이 |
|------|------|------|
| Vue 3 | `package.json` + `vue@^3`, `*.vue` SFC, `<script setup>` | HIGH |
| Vue 2 | `package.json` + `vue@^2`, Options API | MEDIUM (마이그레이션 대상) |
| Nuxt 3 | `nuxt@^3` + `nuxt.config.ts`, `app.vue`, `pages/` | HIGH |
| Nuxt 2 | `nuxt@^2` + `nuxt.config.js` | MEDIUM (마이그레이션 대상) |
| Pinia | `pinia` | HIGH |
| Vuex | `vuex` | MEDIUM (Pinia 마이그레이션 대상) |
| Vue Router | `vue-router` | HIGH |
| Vite | `vite.config.*` + `vite` | HIGH |
| Vue CLI (webpack) | `vue.config.js` + `@vue/cli-service` | MEDIUM (Vite 마이그레이션 대상) |
| React | `react`, `react-dom`, `*.jsx`/`*.tsx` | HIGH (JSX 이벤트 결선 포함, 런타임 동적 route는 수동 검증) |
| Angular (15+) | `@angular/core`, `angular.json` | HIGH |
| AngularJS (1.x) | `angular@^1`, `ng-app` | LOW (마이그레이션 대상) |
| Svelte / SvelteKit | `svelte`, `@sveltejs/kit` | MEDIUM |

### Python 계열

| 스택 | 탐지 | 깊이 |
|------|------|------|
| FastAPI | `fastapi` in requirements/pyproject | HIGH |
| Django | `django` | HIGH |
| Flask | `flask` | MEDIUM |
| SQLAlchemy | `sqlalchemy` | HIGH |
| psycopg | `psycopg` 또는 `psycopg2` | MEDIUM |
| Pydantic | `pydantic` | HIGH |

### .NET 계열

| 스택 | 탐지 | 깊이 |
|------|------|------|
| .NET Framework 2~4 | `*.csproj` + `<TargetFramework>net4*` or `v4.*` | MEDIUM (마이그레이션 대상) |
| .NET Core / 5+ | `*.csproj` + `<TargetFramework>net*` or `netcoreapp*` | MEDIUM (`.cs` FULL, project metadata PARTIAL) |
| ASP.NET Core | `Microsoft.AspNetCore.*`, `ControllerBase` | HIGH (Route token·생성자 DI·트랜잭션) |
| Entity Framework | `EntityFramework`, `Microsoft.EntityFrameworkCore` | HIGH |
| Classic ASP.NET MVC | `System.Web.Mvc` | MEDIUM (마이그레이션 대상) |
| WinForms | `System.Windows.Forms`, `Application.Run`, `*.Designer.cs` | MEDIUM (partial class·event 결선, 시각 Designer는 수동 검증) |
| DevExpress WinForms | `DevExpress.*` + WinForms | MEDIUM (기본 event/call은 지원, Grid designer·repository item은 PARTIAL) |

### Nexacro

| 스택 | 탐지 | 깊이 |
|------|------|------|
| Nexacro XJS | `*.xjs`, `nexacro.*`, `this.transaction()` | HIGH (함수·호출·transaction) |
| Nexacro XFDL | `*.xfdl`, `<FDL>`, `<Form>` | MEDIUM (화면·이벤트·Dataset·transaction, 혼합 XML/Script는 변경 전 수동 검증) |

### 데이터베이스

| DB | 탐지 | 깊이 |
|----|------|------|
| Oracle | `ojdbc*`, `oracle.jdbc.*`, `*.pkb`/`*.pks` (PL/SQL) | HIGH |
| PostgreSQL | `postgresql-*`, `pg`, `psycopg` | HIGH |
| MySQL / MariaDB | `mysql-connector-*`, `mariadb-java-client`, `mysql2` | HIGH |
| SQL Server | `mssql-jdbc`, `System.Data.SqlClient`, `tedious` | MEDIUM |
| Tibero (한국) | `tibero-jdbc`, `com.tmax.tibero.jdbc` | MEDIUM |
| Altibase (한국) | `altibase-jdbc` | LOW |
| MongoDB | `mongo-java-driver`, `mongoose`, `motor` | MEDIUM |
| Redis | `jedis`, `redisson`, `redis-py`, `ioredis` | MEDIUM |

### 기타/레거시

| 스택 | 탐지 | 깊이 |
|------|------|------|
| Go | `go.mod` | MEDIUM |
| Rust | `Cargo.toml`, `*.rs` | LOW (현재 discovery-only, 변경 자동화 금지) |
| PHP / Laravel | `composer.json`, `laravel/framework` | LOW |
| Ruby on Rails | `Gemfile`, `rails` | LOW |
| COBOL | `*.cbl`, `*.cob` | LOW (legacy-decoder 적용) |
| ABAP (SAP) | `*.abap`, ABAP 패턴 | LOW (legacy-decoder 적용) |
| Oracle Forms | `*.fmb`, `*.frm` | LOW |
| Classic VB | `*.vbp`, `*.frm` (구) | LOW |

---

## 분석 깊이 의미

| 깊이 | 의미 |
|------|------|
| HIGH | 결정적 어댑터 범위는 자동 분석·컨벤션 추출 가능. 동적 런타임 동작은 별도 검증 |
| MEDIUM | 핵심 구조는 추출하지만 일부 파일/shape가 PARTIAL. 실제 빌드·UI/통합 시나리오 전까지 HOLD |
| LOW | 발견·구조 파악 중심. 자동 코드 변경 금지, 전문 어댑터 또는 수동 분석 필요 |

---

## QA Boundary 매트릭스

스택별 적용되는 4-Boundary (Boundary 5, 6은 모든 스택 공통):

| 스택 | Boundary 1 | Boundary 2 | Boundary 3 | Boundary 4 |
|------|----------|----------|----------|----------|
| Java EE / Struts | Struts XML ↔ Service ↔ Bean | Service ↔ Query XML 양방향 | 스킬 주장 ↔ 코드 | forward ↔ JSP |
| Spring Boot | `@RequestMapping` ↔ 프론트 호출 | `@Entity` ↔ DTO shape | `@Repository` ↔ 호출 위치 | 트랜잭션 전파 ↔ Service 호출 그래프 |
| Express/NestJS | route path ↔ 클라이언트 fetch | 응답 shape ↔ 프론트 타입 | middleware 체인 일관성 | DTO ↔ ORM 모델 |
| FastAPI | `@router` path ↔ 클라이언트 호출 | Pydantic ↔ ORM 필드 | DI 그래프 | status code ↔ 응답 schema |
| Next.js | `app/[route]` ↔ `href` | API 응답 shape ↔ `fetchJson<T>` | 서버 컴포넌트 fetch ↔ 클라이언트 hook | status 전이 |
| Vue 3 / Nuxt 3 | `pages/` 또는 router 경로 ↔ `<NuxtLink>`/`router.push` | `defineProps`/`<script setup>` 타입 ↔ API 응답 shape | Pinia store action ↔ 컴포넌트 호출 | composable (`use*`) 의존 그래프 |
| Vue 2 / Nuxt 2 | `routes.js` 경로 ↔ `<router-link>` | `props`/Options API 타입 ↔ API 응답 | Vuex action/mutation ↔ 컴포넌트 dispatch | mixin ↔ 사용 컴포넌트 |
| .NET Core MVC | `[Route]` ↔ 호출 | EF Entity ↔ DTO | Repository ↔ 호출 위치 | DbContext ↔ Migration |
| WinForms / DevExpress | Designer ↔ partial Form | event ↔ handler | handler ↔ service | binding/Grid column ↔ DTO |
| Nexacro | component event ↔ handler | Dataset ↔ 서버 shape | transaction ↔ endpoint | callback ↔ output Dataset |

새 스택 발견 시 qa.md의 "스택별 boundary 검증 변형" 섹션에 stub 추가.

---

## 마이그레이션 시나리오 매트릭스

migration-planner가 사전 정의한 변환 시나리오:

| 소스 | 타겟 | 매핑 테이블 템플릿 | 위험도 |
|------|------|---------------|------|
| Struts 1.x | Spring MVC / Spring Boot | Action→Controller, ActionForm→DTO, ActionForward→ViewName, struts-config.xml→`@RequestMapping` | HIGH |
| Struts 2.x | Spring Boot | `@Action`→`@RequestMapping`, interceptor→filter/aspect | MEDIUM |
| iBatis | MyBatis 3 | sqlmap → namespace, parameterClass → parameterType | MEDIUM |
| iBatis / MyBatis | JPA | XML 쿼리 → JPQL/`@Query`/메서드명, ResultMap → Entity | HIGH |
| EJB 2.x | Spring (또는 Spring Boot) | Session Bean → `@Service`, Entity Bean → JPA Entity, MDB → `@KafkaListener`/`@JmsListener` | EXTREME |
| Spring 3~4 (XML) | Spring Boot 3 (어노테이션) | applicationContext.xml → `@Configuration` + `@Bean` | MEDIUM |
| JSP scriptlet | Thymeleaf / React / Vue | `<%...%>` → template syntax, taglib → directive | HIGH |
| Vue 2 (Options API) | Vue 3 (Composition API) | `data/methods/computed` → `<script setup>` + `ref/reactive/computed`, `Vue.extend` → `defineComponent`, filter → method/computed | MEDIUM |
| Vuex | Pinia | `state/mutations/actions` → `defineStore` + state/getters/actions, namespaced modules → 개별 store | MEDIUM |
| Nuxt 2 | Nuxt 3 | `asyncData/fetch` → `useAsyncData/useFetch`, Vuex → Pinia, plugins API 변경, `@nuxtjs/composition-api` 제거 | HIGH |
| Vue CLI (webpack) | Vite | `vue.config.js` → `vite.config.ts`, env 변수 `VUE_APP_*` → `VITE_*`, polyfill 재설정 | LOW~MEDIUM |
| .NET Framework | .NET Core / .NET 8 | `web.config` → `appsettings.json`, `System.Web` → `Microsoft.AspNetCore.*` | HIGH |
| Oracle PL/SQL → Java/Service | DB 로직을 애플리케이션 코드로 | 절차형 → 객체형, 패키지 → 서비스 클래스 | EXTREME |
| Oracle → PostgreSQL | DB 엔진 전환 | 함수/타입/문법 차이, 시퀀스, 힌트, 패키지 | HIGH |
| MySQL → MariaDB | 같은 엔진 변종 | 거의 호환, 일부 함수 차이 | LOW |
| jQuery → Vue/React | 클라이언트 프레임워크 | DOM 조작 → 컴포넌트, AJAX → fetch/axios | HIGH |
| AngularJS (1.x) → Angular (15+) | 동일 이름 다른 프레임워크 | 사실상 전면 재작성 | EXTREME |
| Java 8 → Java 17/21 | 언어 버전 업 | Records, Sealed, Pattern Matching 활용, deprecated 제거 | LOW~MEDIUM |
| Python 2 → Python 3 | 언어 버전 업 | print, unicode, division, 모듈 변경 | MEDIUM |
| Ant → Maven | 빌드 도구 | target → goal, custom task → plugin | MEDIUM |
| Maven → Gradle | 빌드 도구 | pom.xml → build.gradle, plugin 매핑 | MEDIUM |

위험도:
- LOW: 1~2주 PoC, 자동 변환 도구 활용 가능
- MEDIUM: 1~3개월, 모듈 단위 변환, 도구 + 수동
- HIGH: 3~12개월, Phase 분리 + canary 필수
- EXTREME: 6개월+, 사실상 재작성 수준, 비즈니스 동결 위험

---

## 신규 스택 추가 방법

1. analyzer.md의 Step 1~2 탐지 시그니처 표에 추가
2. 분석 깊이 결정 (HIGH/MEDIUM/LOW)
3. qa.md의 boundary 4쌍 정의
4. 필요 시 migration-planner의 매핑 테이블 템플릿 추가
5. 이 문서 갱신

특수 레거시 스택은 legacy-decoder를 우선 활용 (구조 분해 + 의도 추정).
