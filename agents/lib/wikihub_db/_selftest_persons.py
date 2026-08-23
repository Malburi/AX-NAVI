# 담당자 등록·발행 기록 연결·권한 부여 경로 회귀 셀프테스트(무의존, sqlite 임시파일)
"""python agents/lib/wikihub_db/_selftest_persons.py 로 직접 실행한다.

발행 시 받은 담당자 정보가 사람 마스터에 남고, 페이지 버전·발행 로그가 그 사람을 가리키며,
권한 표가 기본값으로 채워지고, 구 스키마 DB 도 컬럼이 자동으로 붙는지 검증한다.
실패 시 AssertionError 로 즉시 종료한다.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, select, inspect, text
import models as m
import store as s
import config
import publish as pub


def _new_store():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    store = s.WikiStore(f"sqlite:///{tmp.name}", engine_name="sqlite")
    store.ensure_schema()
    return store, tmp.name


PERSON = {
    "company": "한빛에스아이", "department": "금융서비스1팀", "employee_no": "20231234",
    "person_name": "김유지", "phone": "010-1234-5678", "email": "yujin.kim@hanbit.co.kr",
}


def test_seed_and_meta():
    store, path = _new_store()
    try:
        with store.engine.connect() as conn:
            roles = {r[0] for r in conn.execute(select(m.roles.c.role_code))}
            perms = {r[0] for r in conn.execute(select(m.permissions.c.perm_code))}
            pairs = conn.execute(select(m.role_permissions)).all()
        assert roles == {"admin", "manager", "editor", "reader"}, roles
        assert "wiki.view" in perms and "acl.manage" in perms, perms
        assert len(pairs) == sum(len(v) for v in m.BUILTIN_ROLE_PERMISSIONS.values()), len(pairs)
        assert store.get_meta("schema_version") == str(m.SCHEMA_VERSION)
        assert store.access_control_enabled() is False, "기본은 OFF 여야 한다"
        store.ensure_schema()  # 두 번 돌려도 중복이 생기지 않는다
        with store.engine.connect() as conn:
            assert len(conn.execute(select(m.role_permissions)).all()) == len(pairs)
        print("ok seed_and_meta")
    finally:
        store.engine.dispose()
        os.unlink(path)


def test_person_upsert():
    store, path = _new_store()
    try:
        pid, created = store.upsert_person(**{k: PERSON[k] for k in
                                              ("company", "employee_no", "person_name",
                                               "department", "phone", "email")})
        assert created is True
        pid2, created2 = store.upsert_person(company=PERSON["company"],
                                             employee_no=PERSON["employee_no"],
                                             person_name="김유지", phone="010-9999-0000")
        assert pid2 == pid and created2 is False, "같은 회사·사번이면 같은 사람"
        row = store.get_person(pid)
        assert row["phone"] == "010-9999-0000", "바뀐 값만 갱신"
        assert row["email"] == PERSON["email"], "안 준 값은 보존"

        # 다른 회사의 같은 사번은 다른 사람이다 (협력사 혼재 대응)
        other, created3 = store.upsert_person(company="다른회사", employee_no="20231234",
                                              person_name="이철수")
        assert other != pid and created3 is True

        try:
            store.upsert_person(company="", employee_no="1", person_name="x")
            raise AssertionError("회사명 없이 등록되면 안 된다")
        except s.StoreError:
            pass
        print("ok person_upsert")
    finally:
        store.engine.dispose()
        os.unlink(path)


def test_publish_records_publisher():
    store, path = _new_store()
    workdir = tempfile.mkdtemp()
    wiki_dir = os.path.join(workdir, "_workspace", "wiki")
    os.makedirs(wiki_dir)
    with open(os.path.join(wiki_dir, "Home.md"), "w", encoding="utf-8") as f:
        f.write("# 주문관리시스템\n\n첫 발행 본문.\n")
    try:
        counts = pub.publish(store, workdir, wiki_dir, "ORDER", "backend", "backend",
                             system_name="주문관리시스템", summary="최초 발행",
                             publisher=dict(PERSON), owner_role="owner",
                             set_as_system_owner=True)
        assert counts["created"] == 1, counts

        person = store.find_person(PERSON["company"], PERSON["employee_no"])
        assert person is not None and person["person_name"] == "김유지"

        versions = store.list_versions("ORDER", "backend", "Home.md")
        assert versions[0]["author"] == "김유지(20231234)", versions[0]["author"]

        with store.engine.connect() as conn:
            pv = conn.execute(select(m.page_versions.c.author_person_id)).first()
            assert pv[0] == person["person_id"], "버전 이력이 사람 마스터를 가리켜야 한다"
            log = conn.execute(select(m.publish_log.c.publisher_person_id)).first()
            assert log[0] == person["person_id"], "발행 로그가 사람 마스터를 가리켜야 한다"
            sysrow = conn.execute(select(m.systems.c.owner_person_id)).first()
            assert sysrow[0] == person["person_id"], "대표 담당자가 지정돼야 한다"

        owners = store.list_system_owners("ORDER")
        assert len(owners) == 1 and owners[0]["owner_role"] == "owner", owners
        assert owners[0]["email"] == PERSON["email"]
        assert owners[0]["component_key"] == "backend"
        print("ok publish_records_publisher")
    finally:
        store.engine.dispose()
        os.unlink(path)


def test_grants_and_permission_check():
    store, path = _new_store()
    try:
        pid, _ = store.upsert_person(company="한빛에스아이", employee_no="20231234",
                                     person_name="김유지")
        reader, _ = store.upsert_person(company="한빛에스아이", employee_no="20239999",
                                        person_name="박열람")

        # 통제가 꺼져 있으면 누구든 통과한다 (지금 운영과 동일)
        assert store.can(reader, "wiki.view", "ORDER") is True
        store.set_access_control(True)
        assert store.can(reader, "wiki.view", "ORDER") is False, "권한 없으면 차단"

        store.grant_access(reader, "reader", scope_type="system", system_key="ORDER")
        assert store.can(reader, "wiki.view", "ORDER") is True
        assert store.can(reader, "wiki.publish", "ORDER") is False, "열람자는 발행 못 한다"
        assert store.can(reader, "wiki.view", "SETTLE") is False, "다른 시스템은 안 보인다"

        store.grant_access(pid, "admin", scope_type="global")
        assert store.can(pid, "wiki.view", "SETTLE") is True, "global 은 모든 시스템에 적용"
        assert store.can(pid, "acl.manage", "ORDER") is True

        assert store.revoke_access(reader, "reader", "system", "ORDER") == 1
        assert store.can(reader, "wiki.view", "ORDER") is False
        assert len(store.list_grants(person_id=reader)) == 0
        assert len(store.list_grants(person_id=reader, include_inactive=True)) == 1, "회수 이력은 남는다"

        store.write_access_log("view", "denied", person_id=reader, system_key="ORDER",
                               page_path="Home.md")
        with store.engine.connect() as conn:
            assert conn.execute(select(m.access_log.c.result)).first()[0] == "denied"
        print("ok grants_and_permission_check")
    finally:
        store.engine.dispose()
        os.unlink(path)


def test_upgrade_from_v1_shape():
    """v2 컬럼이 없는 구 DB 를 열어도 ensure_schema 가 ALTER 로 붙인다."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}", future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE wikihub_systems ("
            " system_key VARCHAR(100) NOT NULL PRIMARY KEY, display_name VARCHAR(200) NOT NULL,"
            " description VARCHAR(1000), owner VARCHAR(200), repo_url VARCHAR(500),"
            " tags VARCHAR(500), is_archived BOOLEAN NOT NULL, created_at DATETIME NOT NULL,"
            " updated_at DATETIME NOT NULL)")
        conn.exec_driver_sql(
            "INSERT INTO wikihub_systems VALUES ('LEGACY','구 시스템','','','','',0,"
            "'2026-01-01 00:00:00','2026-01-01 00:00:00')")
    engine.dispose()

    store = s.WikiStore(f"sqlite:///{tmp.name}", engine_name="sqlite")
    try:
        store.ensure_schema()
        cols = {c["name"] for c in inspect(store.engine).get_columns("wikihub_systems")}
        assert "owner_person_id" in cols, cols
        with store.engine.connect() as conn:
            row = conn.execute(text("SELECT system_key, owner_person_id FROM wikihub_systems")).first()
            assert row[0] == "LEGACY" and row[1] is None, "기존 행은 그대로, 새 컬럼만 NULL"
        store.ensure_schema()  # 재실행해도 ALTER 를 또 치지 않는다
        print("ok upgrade_from_v1_shape")
    finally:
        store.engine.dispose()
        os.unlink(tmp.name)


def test_publisher_validation():
    person = config.resolve_publisher({"WIKI_PUBLISHER_COMPANY": "한빛에스아이"},
                                      {"employee_no": "20231234", "person_name": "김유지"})
    assert person["company"] == "한빛에스아이", "env 값이 쓰여야 한다"
    warnings = config.validate_publisher(person)
    assert any("소속" in w for w in warnings) and any("이메일" in w for w in warnings), warnings

    try:
        config.validate_publisher({"company": "한빛", "employee_no": "", "person_name": "김"})
        raise AssertionError("사번 없이 통과하면 안 된다")
    except config.ConfigError as e:
        assert "사번" in str(e)

    try:
        config.validate_publisher({**PERSON, "email": "not-an-email"})
        raise AssertionError("잘못된 이메일이 통과하면 안 된다")
    except config.ConfigError:
        pass

    assert config.validate_publisher(dict(PERSON)) == [], "정상 입력엔 경고가 없다"
    print("ok publisher_validation")


if __name__ == "__main__":
    test_seed_and_meta()
    test_person_upsert()
    test_publish_records_publisher()
    test_grants_and_permission_check()
    test_upgrade_from_v1_shape()
    test_publisher_validation()
    print("\n전체 통과")
