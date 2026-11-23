"""Unit tests for scripts/sync_skills.py security and integrity helpers."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import scripts.sync_skills as sync_mod
from scripts.sync_skills import (
    _build_git_env,
    _verify_integrity,
    load_lock,
    main,
    safe_extract_tarball,
    sync_git_repo,
)


class LocalRepo(NamedTuple):
    url: str
    shas: tuple[str, str]


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(cwd),
        },
    )
    return out.stdout.strip()


@pytest.fixture
def local_repo_two_commits(tmp_path: Path) -> LocalRepo:
    repo = tmp_path / "src_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    shas = []
    for i in (1, 2):
        (repo / "f.txt").write_text(f"v{i}\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    return LocalRepo(url=f"file://{repo}", shas=(shas[0], shas[1]))


def _make_tgz(path: Path, entries: list[tuple[str, bytes | None, int]]) -> None:
    """Create a tar.gz file with custom member names and types."""
    with tarfile.open(path, mode="w:gz") as tar:
        for name, data, mtype in entries:
            info = tarfile.TarInfo(name=name)
            info.type = mtype  # type: ignore[assignment]
            if mtype == tarfile.SYMTYPE:
                info.linkname = "/etc/passwd"
                tar.addfile(info)
            elif data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)


def test_safe_extract_tarball_strips_npm_package_prefix(tmp_path: Path) -> None:
    tgz = tmp_path / "good.tgz"
    _make_tgz(
        tgz,
        [
            ("package/guides/security/test.md", b"# Safe Guide\n", tarfile.REGTYPE),
        ],
    )
    dest = tmp_path / "out"
    safe_extract_tarball(tgz, dest)
    assert (dest / "guides/security/test.md").read_text(encoding="utf-8") == "# Safe Guide\n"


@pytest.mark.parametrize(
    ("member_name", "member_type"),
    [
        ("../escape.txt", tarfile.REGTYPE),
        ("package/../../escape.txt", tarfile.REGTYPE),
        ("/etc/evil.txt", tarfile.REGTYPE),
        ("package/evil_link", tarfile.SYMTYPE),
    ],
)
def test_safe_extract_tarball_blocks_tar_slip_and_symlinks(
    tmp_path: Path,
    member_name: str,
    member_type: int,
) -> None:
    tgz = tmp_path / "evil.tgz"
    _make_tgz(tgz, [(member_name, b"boom", member_type)])
    with pytest.raises(ValueError):
        safe_extract_tarball(tgz, tmp_path / "dest")


def test_verify_integrity_sha512() -> None:
    payload = b"compiled-guides-payload"
    digest = base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
    _verify_integrity(payload, integrity=f"sha512-{digest}", shasum=None)

    with pytest.raises(ValueError, match="SHA-512"):
        _verify_integrity(payload, integrity="sha512-invalid", shasum=None)


def test_build_git_env_passes_ephemeral_token_header() -> None:
    env = _build_git_env("ghp_example_token")
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")
    assert "ghp_example_token" not in env["GIT_CONFIG_VALUE_0"]


def test_sync_git_repo_checks_out_pinned_sha(
    tmp_path: Path, local_repo_two_commits: LocalRepo
) -> None:
    first_sha, _ = local_repo_two_commits.shas
    meta = sync_git_repo("x", local_repo_two_commits.url, tmp_path / "x", ref=first_sha)
    assert meta["commit"] == first_sha
    assert meta["ref"] == first_sha


def test_sync_git_repo_repin_existing_checkout(
    tmp_path: Path, local_repo_two_commits: LocalRepo
) -> None:
    first_sha, second_sha = local_repo_two_commits.shas
    target = tmp_path / "x"
    assert sync_git_repo("x", local_repo_two_commits.url, target)["commit"] == second_sha
    assert sync_git_repo("x", local_repo_two_commits.url, target, ref=first_sha)["commit"] == first_sha


def test_sync_git_repo_branch_ref(tmp_path: Path, local_repo_two_commits: LocalRepo) -> None:
    meta = sync_git_repo("x", local_repo_two_commits.url, tmp_path / "x", ref="main")
    assert meta["commit"] == local_repo_two_commits.shas[1]
    assert meta["ref"] == "main"


def test_sync_git_repo_unknown_sha_fails_naming_source(
    tmp_path: Path, local_repo_two_commits: LocalRepo
) -> None:
    with pytest.raises(RuntimeError, match="x"):
        sync_git_repo("x", local_repo_two_commits.url, tmp_path / "x", ref="0" * 40)


def test_load_lock_reads_and_validates(tmp_path: Path) -> None:
    path = tmp_path / "lock.json"
    path.write_text('{"superpowers": {"ref": "abc"}}', encoding="utf-8")
    assert load_lock(path) == {"superpowers": {"ref": "abc"}}
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_lock(path)


def test_update_lock_writes_resolved_refs(
    tmp_path: Path, local_repo_two_commits: LocalRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sync_mod,
        "GIT_SOURCES",
        {"superpowers": local_repo_two_commits.url, "my_skills": local_repo_two_commits.url},
    )
    first_sha, second_sha = local_repo_two_commits.shas
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "superpowers": {"ref": first_sha},
                "my_skills": {"ref": "main"},
                "modern-web-guidance": {"version": "1.0.0"},
            }
        ),
        encoding="utf-8",
    )

    def fake_npm(target_dir: Path, *, version: str = "latest") -> dict[str, str]:
        assert version == "latest"
        return {"type": "npm", "version": "9.9.9"}

    monkeypatch.setattr(sync_mod, "sync_npm_modern_web_guidance", fake_npm)
    rc = main(["--skills-dir", str(tmp_path / "store"), "--lock", str(lock_path), "--update-lock"])
    assert rc == 0
    new_lock: dict[str, Any] = json.loads(lock_path.read_text(encoding="utf-8"))
    assert new_lock["superpowers"] == {"ref": second_sha}
    assert new_lock["my_skills"] == {"ref": "main"}
    assert new_lock["modern-web-guidance"] == {"version": "9.9.9"}


def test_sync_uses_lock_pins(
    tmp_path: Path, local_repo_two_commits: LocalRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_mod, "GIT_SOURCES", {"superpowers": local_repo_two_commits.url})
    seen: list[str] = []

    def fake_npm(target_dir: Path, *, version: str = "latest") -> dict[str, str]:
        seen.append(version)
        return {"type": "npm", "version": version}

    monkeypatch.setattr(sync_mod, "sync_npm_modern_web_guidance", fake_npm)
    first_sha, _ = local_repo_two_commits.shas
    lock = {"superpowers": {"ref": first_sha}, "modern-web-guidance": {"version": "1.0.1"}}
    meta = sync_mod.sync_all(tmp_path / "store", lock=lock)
    assert meta["sources"]["superpowers"]["commit"] == first_sha
    assert seen == ["1.0.1"]
