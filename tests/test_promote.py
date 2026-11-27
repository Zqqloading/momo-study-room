from __future__ import annotations

from pathlib import Path

from core.db import connect, init_schema
from core.promote import main
from core.store import Store


def make_store(db: Path) -> Store:
    conn = connect(db)
    init_schema(conn)
    return Store(conn)


def test_promote_writes_inbox_file_and_marks_promoted(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    store = make_store(db)
    try:
        hot_id = store.capture_hot_item(
            source_kind="session",
            text="光合作用把光能转成化学能",
            text_origin="user",
            source_url="https://example.com/photo",
        )
    finally:
        store.close()

    inbox = tmp_path / "inbox"
    assert main([str(hot_id), "--db", str(db), "--inbox", str(inbox)]) == 0

    files = list(inbox.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "promoted_from:" in content
    assert "https://example.com/photo" in content
    assert "光合作用把光能转成化学能" in content

    store = make_store(db)
    try:
        item = store.hot_item(hot_id)
        assert item is not None
        assert item.status == "promoted"
        assert item.material_id == files[0].stem
    finally:
        store.close()


def test_promote_write_failure_leaves_hot(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    store = make_store(db)
    try:
        hot_id = store.capture_hot_item(
            source_kind="session", text="光合作用把光能转成化学能", text_origin="user"
        )
    finally:
        store.close()

    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")

    assert main([str(hot_id), "--db", str(db), "--inbox", str(blocked)]) == 1

    store = make_store(db)
    try:
        item = store.hot_item(hot_id)
        assert item is not None
        assert item.status == "hot"
    finally:
        store.close()


def test_promote_does_not_overwrite_conflicting_slug(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    inbox = tmp_path / "inbox"
    store = make_store(db)
    try:
        first = store.capture_hot_item(
            source_kind="session", text="光合作用把光能转成化学能", text_origin="user"
        )
        second = store.capture_hot_item(
            source_kind="session", text="呼吸作用把有机物分解成二氧化碳", text_origin="user"
        )
    finally:
        store.close()

    assert main([str(first), "--db", str(db), "--inbox", str(inbox), "--slug", "note"]) == 0
    assert main([str(second), "--db", str(db), "--inbox", str(inbox), "--slug", "note"]) == 0

    names = sorted(path.name for path in inbox.glob("*.md"))
    assert len(names) == 2
    assert "note.md" in names
    assert any(name.startswith("note-") for name in names)


def test_promote_rejects_non_hot_item(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    store = make_store(db)
    try:
        hot_id = store.capture_hot_item(
            source_kind="session", text="光合作用把光能转成化学能", text_origin="user"
        )
        store.discard_hot_item(hot_id)
    finally:
        store.close()

    assert (
        main([str(hot_id), "--db", str(db), "--inbox", str(tmp_path / "inbox")]) == 1
    )
