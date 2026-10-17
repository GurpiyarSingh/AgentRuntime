from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_runtime.api.app import create_app
from agent_runtime.config import Settings


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "ws"


@pytest.fixture
def client(root: Path) -> TestClient:
    settings = Settings(_env_file=None, workspace_dir=root, max_file_bytes=4096)  # type: ignore[call-arg]
    return TestClient(create_app(settings=settings))


def test_upload_list_download_delete(client: TestClient, root: Path) -> None:
    uploaded = client.post("/v1/files", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert uploaded.status_code == 201
    assert uploaded.json()["path"] == "notes.txt"
    assert uploaded.json()["size"] == 5

    listing = client.get("/v1/files").json()["files"]
    assert [f["path"] for f in listing] == ["notes.txt"]

    download = client.get("/v1/files/notes.txt")
    assert download.status_code == 200
    assert download.content == b"hello"
    assert "notes.txt" in download.headers["content-disposition"]

    assert client.delete("/v1/files/notes.txt").status_code == 204
    assert not (root / "notes.txt").exists()
    assert client.get("/v1/files/notes.txt").status_code == 404


def test_upload_into_folder_or_to_explicit_path(client: TestClient, root: Path) -> None:
    files = {"file": ("photo.png", b"\x89PNG", "image/png")}
    assert client.post("/v1/files", files=files, data={"path": "inbox/"}).json()["path"] == (
        "inbox/photo.png"
    )
    assert (
        client.post("/v1/files", files=files, data={"path": "a/b/renamed.png"}).json()["path"]
        == "a/b/renamed.png"
    )
    assert (root / "a" / "b" / "renamed.png").read_bytes() == b"\x89PNG"
    # An existing directory keeps the upload's own name.
    assert client.post("/v1/files", files=files, data={"path": "a"}).json()["path"] == (
        "a/photo.png"
    )


def test_upload_strips_directories_from_the_client_filename(client: TestClient, root: Path) -> None:
    response = client.post("/v1/files", files={"file": ("../../evil.txt", b"x", "text/plain")})
    assert response.status_code == 201
    assert response.json()["path"] == "evil.txt"
    assert (root / "evil.txt").exists()


def test_upload_conflict_and_overwrite(client: TestClient, root: Path) -> None:
    client.post("/v1/files", files={"file": ("a.txt", b"one", "text/plain")})
    conflict = client.post("/v1/files", files={"file": ("a.txt", b"two", "text/plain")})
    assert conflict.status_code == 409

    replaced = client.post(
        "/v1/files", files={"file": ("a.txt", b"two", "text/plain")}, data={"overwrite": "true"}
    )
    assert replaced.status_code == 201
    assert (root / "a.txt").read_bytes() == b"two"


def test_upload_size_limit_leaves_nothing_behind(client: TestClient, root: Path) -> None:
    response = client.post("/v1/files", files={"file": ("big.bin", b"x" * 5000, "text/plain")})
    assert response.status_code == 413
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    ("method", "url", "kwargs"),
    [
        ("get", "/v1/files", {"params": {"path": "../"}}),
        ("post", "/v1/files", {"data": {"path": "../escape.txt"}}),
        ("delete", "/v1/files/..%2Foutside.txt", {}),
    ],
)
def test_paths_outside_the_workspace_are_refused(
    client: TestClient, method: str, url: str, kwargs: dict[str, object]
) -> None:
    if method == "post":
        kwargs = {**kwargs, "files": {"file": ("x.txt", b"x", "text/plain")}}
    response = getattr(client, method)(url, **kwargs)
    assert response.status_code in (400, 404)
    assert response.status_code != 200


def test_listing_a_missing_directory_is_404(client: TestClient) -> None:
    assert client.get("/v1/files", params={"path": "nope"}).status_code == 404


def test_files_api_uses_the_chosen_workspace(
    client: TestClient, root: Path, tmp_path: Path
) -> None:
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    params = {"workspace": str(chosen)}

    uploaded = client.post(
        "/v1/files", params=params, files={"file": ("a.txt", b"hey", "text/plain")}
    )

    assert uploaded.status_code == 201
    assert (chosen / "a.txt").read_bytes() == b"hey"
    assert not (root / "a.txt").exists()
    assert client.get("/v1/files/a.txt", params=params).content == b"hey"
    assert client.get("/v1/files/a.txt").status_code == 404
