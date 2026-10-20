"""Unit tests for Content-Type detection on uploads (issue #807).

Azure serves blobs without a Content-Type as ``application/octet-stream``, so
every upload must carry an explicit type. The tests use obstore's in-memory
store, which keeps the attributes, so they hold for every backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import obstore as obs
import pytest
from obstore.store import MemoryStore

from portolan_cli.sync import push as push_mod
from portolan_cli.sync.content_type import guess_content_type, put_attributes
from portolan_cli.sync.upload import upload_directory, upload_file

if TYPE_CHECKING:
    from pathlib import Path


def _content_type(store: MemoryStore, key: str) -> str:
    return str(obs.get(store, key).attributes["Content-Type"])


def _assert_stac_content_types(store: MemoryStore) -> None:
    assert _content_type(store, "pre/catalog.json") == "application/json"
    assert _content_type(store, "pre/col/collection.json") == "application/json"
    assert _content_type(store, "pre/col/item/item.json") == "application/json"
    assert _content_type(store, "pre/col/README.md") == "text/markdown"


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("catalog.json", "application/json"),
        ("col/item/item.json", "application/json"),
        ("col/versions.json", "application/json"),
        ("col/style.JSON", "application/json"),
        ("col/data.parquet", "application/vnd.apache.parquet"),
        ("col/dem.tif", "image/tiff; application=geotiff"),
        ("col/dem.TIFF", "image/tiff; application=geotiff"),
        ("col/thumb.png", "image/png"),
        ("README.md", "text/markdown"),
        ("col/map.pmtiles", "application/vnd.pmtiles"),
        ("col/blob.unknownext", "application/octet-stream"),
        ("col/noextension", "application/octet-stream"),
    ],
)
def test_content_type_detection(key: str, expected: str) -> None:
    assert guess_content_type(key) == expected
    assert put_attributes(key) == {"Content-Type": expected}


@pytest.mark.unit
def test_upload_file_sets_content_type(
    tmp_path: Path, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "catalog.json"
    f.write_text("{}")
    monkeypatch.setattr(
        "portolan_cli.sync.upload._setup_store_and_kwargs", lambda *a, **k: (store, {})
    )

    result = upload_file(source=f, destination="s3://bucket/prefix/")

    assert result.success
    assert _content_type(store, "prefix/catalog.json") == "application/json"


@pytest.mark.unit
def test_upload_directory_sets_content_type(
    tmp_path: Path, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "b.parquet").write_bytes(b"PAR1")
    (tmp_path / "c.tif").write_bytes(b"II*\x00")
    monkeypatch.setattr(
        "portolan_cli.sync.upload._setup_store_and_kwargs", lambda *a, **k: (store, {})
    )

    result = upload_directory(source=tmp_path, destination="s3://bucket/p/")

    assert result.success
    assert _content_type(store, "p/a.json") == "application/json"
    assert _content_type(store, "p/b.parquet") == "application/vnd.apache.parquet"
    assert _content_type(store, "p/c.tif") == "image/tiff; application=geotiff"


# --- push paths -------------------------------------------------------------


@pytest.mark.unit
def test_put_bytes_sets_content_type(store: MemoryStore) -> None:
    push_mod._put_bytes(store, "x/catalog.json", b"{}")
    assert _content_type(store, "x/catalog.json") == "application/json"


@pytest.mark.unit
def test_upload_root_files_sets_content_type(tmp_path: Path, store: MemoryStore) -> None:
    (tmp_path / "README.md").write_text("# hi")
    (tmp_path / "catalog.json").write_text("{}")
    (tmp_path / "versions.json").write_text("{}")
    (tmp_path / "style.json").write_text("{}")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "catalog.json").write_text("{}")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    stats: dict[str, Any] = {"total_files": 0}

    push_mod._upload_root_files(
        store,
        "pre",
        tmp_path,
        [tmp_path / "style.json", tmp_path / "logo.png"],
        [sub / "catalog.json"],
        stats,
    )

    assert _content_type(store, "pre/README.md") == "text/markdown"
    assert _content_type(store, "pre/catalog.json") == "application/json"
    assert _content_type(store, "pre/versions.json") == "application/json"
    assert _content_type(store, "pre/style.json") == "application/json"
    assert _content_type(store, "pre/logo.png") == "image/png"
    assert _content_type(store, "pre/sub/catalog.json") == "application/json"


@pytest.fixture
def stac_catalog(tmp_path: Path) -> tuple[Path, dict[str, list[Path]]]:
    item_dir = tmp_path / "col" / "item"
    item_dir.mkdir(parents=True)
    files = {
        "catalog": [tmp_path / "catalog.json"],
        "collection": [tmp_path / "col" / "collection.json"],
        "items": [item_dir / "item.json"],
        "readmes": [tmp_path / "col" / "README.md"],
    }
    for paths in files.values():
        for p in paths:
            p.write_text("{}")
    return tmp_path, files


@pytest.mark.unit
def test_upload_stac_files_and_readmes_sync(
    stac_catalog: tuple[Path, dict[str, list[Path]]], store: MemoryStore
) -> None:
    root, files = stac_catalog

    push_mod._upload_stac_files(store, root, "pre", files)
    push_mod._upload_readmes(store, root, "pre", files)

    _assert_stac_content_types(store)


@pytest.mark.unit
async def test_upload_stac_files_and_readmes_async(
    stac_catalog: tuple[Path, dict[str, list[Path]]], store: MemoryStore
) -> None:
    root, files = stac_catalog

    await push_mod._upload_stac_files_async(store, root, "pre", files, json_mode=True)
    await push_mod._upload_readmes_async(store, root, "pre", files)

    _assert_stac_content_types(store)


@pytest.mark.unit
async def test_upload_metadata_files_async(tmp_path: Path, store: MemoryStore) -> None:
    coll = tmp_path / "col"
    coll.mkdir()
    (coll / "style.json").write_text("{}")
    (coll / "thumbnail.png").write_bytes(b"\x89PNG")

    count, errors = await push_mod._upload_metadata_files_async(store, tmp_path, "pre", "col")

    assert errors == []
    assert count >= 2
    assert _content_type(store, "pre/col/style.json") == "application/json"
    assert _content_type(store, "pre/col/thumbnail.png") == "image/png"


@pytest.mark.unit
@pytest.mark.parametrize("use_etag", [False, True])
def test_upload_versions_json_sync(store: MemoryStore, use_etag: bool) -> None:
    etag = obs.put(store, "pre/col/versions.json", b"{}")["e_tag"] if use_etag else None

    push_mod._upload_versions_json(store, "pre", "col", {"versions": []}, etag, force=False)

    assert _content_type(store, "pre/col/versions.json") == "application/json"


@pytest.mark.unit
@pytest.mark.parametrize("use_etag", [False, True])
async def test_upload_versions_json_async(store: MemoryStore, use_etag: bool) -> None:
    etag = obs.put(store, "pre/col/versions.json", b"{}")["e_tag"] if use_etag else None

    await push_mod._upload_versions_json_async(
        store, "pre", "col", {"versions": []}, etag, force=False
    )

    assert _content_type(store, "pre/col/versions.json") == "application/json"


@pytest.mark.unit
async def test_upload_assets_async_small_and_large(
    tmp_path: Path, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Small files go through put_async, files over the threshold through multipart put."""
    monkeypatch.setattr(push_mod, "MULTIPART_THRESHOLD", 16)
    coll = tmp_path / "col" / "item"
    coll.mkdir(parents=True)
    small = coll / "small.parquet"
    small.write_bytes(b"PAR1")
    large = coll / "large.tif"
    large.write_bytes(b"x" * 64)

    _, failed, uploaded, _ = await push_mod._upload_assets_async(
        store, tmp_path, "pre", [small, large], json_mode=True, suppress_progress=True
    )

    assert failed == []
    assert sorted(uploaded) == ["pre/col/item/large.tif", "pre/col/item/small.parquet"]
    assert _content_type(store, "pre/col/item/small.parquet") == "application/vnd.apache.parquet"
    assert _content_type(store, "pre/col/item/large.tif") == "image/tiff; application=geotiff"
