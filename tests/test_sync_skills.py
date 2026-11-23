"""Unit tests for scripts/sync_skills.py security and integrity helpers."""

from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

import pytest
from scripts.sync_skills import _build_git_env, _verify_integrity, safe_extract_tarball


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
