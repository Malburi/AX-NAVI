# wikihub_content_blobs 압축·dedup 저장 경로 회귀 셀프테스트(무의존, sqlite 임시파일)
"""python agents/lib/wikihub_db/_selftest_blobs.py 로 직접 실행한다.

content 본문이 wikihub_content_blobs 로 옮겨진 뒤에도 저장·복원·검색·버전·이관이
기존 계약대로 동작하는지 검증한다. 실패 시 AssertionError 로 즉시 종료한다.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select, insert, update, func
import models as m
import store as s


def _new_store():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    store = s.WikiStore(f"sqlite:///{tmp.file.name if hasattr(tmp, 'file') else tmp.name}", engine_name="sqlite")
    store.ensure_schema()
    return store, tmp.name


def test_encode_roundtrip():
    for text in ["", "짧은 한글", "x" * 5000, "가나다" * 4000]:
        algo, byte_len, data = s.encode_content(text)
        assert byte_len == len(text.encode("utf-8")), byte_len
        assert s.decode_blob(algo, data) == text, algo
    # 큰 본문은 gzip, 작은 본문은 raw
    assert s.encode_content("x" * 5000)[0] == "gzip"
    assert s.encode_content("short")[0] == "raw"
    print("ok encode_roundtrip")


def test_save_get_and_null_content():
    store, path = _new_store()
    try:
        store.upsert_system("SYS")
        store.upsert_component("SYS", "backend", "backend")
        big = "# 제목\n" + ("본문 내용 반복 " * 1000)  # >512B → gzip
        assert store.save_page("SYS", "backend", "a.md", big, "text/markdown") == "created"
        got = store.get_page("SYS", "backend", "a.md")
        assert got["content"] == big, "본문 복원 불일치"
        assert got["title"] == "제목"
        # pages.content 는 NULL, blob 은 존재
        with store.engine.connect() as conn:
            raw = conn.execute(select(m.pages.c.content, m.pages.c.checksum)
                               .where(m.pages.c.page_path == "a.md")).first()
            assert not raw.content, "content 컬럼이 비어 있지 않음(본문이 blob 로 안 옮겨짐)"
            blob_n = conn.execute(select(func.count()).select_from(m.content_blobs)
                                  .where(m.content_blobs.c.checksum == raw.checksum)).scalar_one()
            assert blob_n == 1, blob_n
        print("ok save_get_and_null_content")
    finally:
        store.engine.dispose()
        os.unlink(path)


def test_dedup():
    store, path = _new_store()
    try:
        store.upsert_system("SYS")
        store.upsert_component("SYS", "backend", "backend")
        same = "동일 본문 " * 500
        store.save_page("SYS", "backend", "x.md", same, "text/markdown")
        store.save_page("SYS", "backend", "y.md", same, "text/markdown")  # 다른 페이지, 같은 내용
        with store.engine.connect() as conn:
            n = conn.execute(select(func.count()).select_from(m.content_blobs)).scalar_one()
        assert n == 1, f"동일 본문인데 blob {n}개(1개여야 함)"
        print("ok dedup")
    finally:
        store.engine.dispose()
        os.unlink(path)


def test_versions_and_size():
    store, path = _new_store()
    try:
        store.upsert_system("SYS")
        store.upsert_component("SYS", "backend", "backend")
        v1 = "버전1 본문 " * 300
        v2 = "버전2 다른 본문 " * 300
        store.save_page("SYS", "backend", "p.md", v1, "text/markdown")
        assert store.save_page("SYS", "backend", "p.md", v2, "text/markdown") == "updated"
        assert store.get_version("SYS", "backend", "p.md", 1)["content"] == v1
        assert store.get_version("SYS", "backend", "p.md", 2)["content"] == v2
        vers = store.list_versions("SYS", "backend", "p.md")
        sizes = {v["version_no"]: v["size"] for v in vers}
        assert sizes[1] == len(v1.encode("utf-8")), sizes
        assert sizes[2] == len(v2.encode("utf-8")), sizes
        print("ok versions_and_size")
    finally:
        store.engine.dispose()
        os.unlink(path)


def test_search():
    store, path = _new_store()
    try:
        store.upsert_system("SYS")
        store.upsert_component("SYS", "backend", "backend")
        store.save_page("SYS", "backend", "doc.md", "결제 취소 로직 설명 " * 100, "text/markdown")
        store.save_page("SYS", "backend", "other.md", "무관한 내용 " * 100, "text/markdown")
        res = store.search("결제")
        assert any(r["page_path"] == "doc.md" and r["hit_count"] > 0 for r in res), res
        assert all(r["page_path"] != "other.md" for r in res), res
        print("ok search")
    finally:
        store.engine.dispose()
        os.unlink(path)


def test_migrate_legacy():
    store, path = _new_store()
    try:
        store.upsert_system("SYS")
        store.upsert_component("SYS", "backend", "backend")
        legacy = "레거시 본문 " * 400
        checksum = s.sha256_text(legacy)
        now = s.utc_now()
        # blob 없이 content 컬럼에 직접 넣은 구 데이터 시뮬레이션
        with store.engine.begin() as conn:
            conn.execute(insert(m.pages).values(
                system_key="SYS", component_key="backend", page_path="legacy.md",
                title="레거시", content=legacy, content_type="text/markdown", checksum=checksum,
                current_version=1, is_deleted=False, created_at=now, updated_at=now))
            conn.execute(insert(m.page_versions).values(
                system_key="SYS", component_key="backend", page_path="legacy.md", version_no=1,
                content=legacy, content_type="text/markdown", checksum=checksum,
                change_type="created", change_summary="", author="t", created_at=now))
        # 이관 전: get_page 는 content 컬럼 폴백으로 동작
        assert store.get_page("SYS", "backend", "legacy.md")["content"] == legacy
        stats = store.migrate_content_to_blobs(vacuum=True)
        assert stats["blobs_created"] == 1, stats
        assert stats["pages_rows"] == 1 and stats["versions_rows"] == 1, stats
        # 이관 후: content 컬럼 NULL, blob 경유 복원 동일
        with store.engine.connect() as conn:
            leftover = conn.execute(select(func.count()).select_from(m.pages)
                                    .where(m.pages.c.content.isnot(None), m.pages.c.content != "")).scalar_one()
            assert leftover == 0, f"이관 후에도 content 남음 {leftover}"
        assert store.get_page("SYS", "backend", "legacy.md")["content"] == legacy
        assert store.get_version("SYS", "backend", "legacy.md", 1)["content"] == legacy
        print("ok migrate_legacy")
    finally:
        store.engine.dispose()
        os.unlink(path)


if __name__ == "__main__":
    test_encode_roundtrip()
    test_save_get_and_null_content()
    test_dedup()
    test_versions_and_size()
    test_search()
    test_migrate_legacy()
    print("\n전체 통과")
