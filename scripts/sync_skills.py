"""Idempotent synchronization script for DevTeam Skills MCP sources.

Sources synced into ``skills_store/``:
1. ``superpowers`` (git): https://github.com/obra/superpowers
2. ``my_skills`` (git): https://github.com/leoneljfernandes/my_skills
3. ``modern-web-guidance`` (npm tarball): compiled guides + search index in pure Python
   (no Node.js / npx required, no unexpanded transclusion macros).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess  # noqa: S404
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("sync_skills")

GIT_SOURCES: dict[str, str] = {
    "superpowers": "https://github.com/obra/superpowers.git",
    "my_skills": "https://github.com/leoneljfernandes/my_skills.git",
}

NPM_PACKAGE_NAME = "modern-web-guidance"
NPM_REGISTRY_HOST = "registry.npmjs.org"
HTTP_TIMEOUT_SECONDS = 30
GIT_TIMEOUT_SECONDS = 120
MAX_TAR_BYTES = 50 * 1024 * 1024  # 50 MiB safety cap


def _build_git_env(github_token: str | None) -> dict[str, str]:
    """Build subprocess environment passing GITHUB_TOKEN ephemerally without touching .git/config."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if github_token:
        encoded = base64.b64encode(f"x-access-token:{github_token}".encode()).decode("ascii")
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {encoded}"
    return env


def _run_git(args: list[str], *, cwd: Path | None, env: dict[str, str]) -> str:
    """Execute a git command with shell=False and return stdout."""
    git_bin = shutil.which("git")
    if git_bin is None:
        raise RuntimeError("git binary not found in PATH")
    result = subprocess.run(  # noqa: S603
        [git_bin, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        # Never expose credentials; git stderr is safe when auth goes via env header
        stderr = result.stderr.strip()
        raise RuntimeError(f"git {' '.join(args[:2])} failed (exit {result.returncode}): {stderr}")
    return result.stdout.strip()


_SHA_RE = re.compile(r"[0-9a-f]{40}")
DEFAULT_LOCK_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.lock.json"
ALL_SOURCES = ("superpowers", "my_skills", "modern-web-guidance")


def load_lock(path: Path) -> dict[str, dict[str, str]]:
    """Load and validate ``sources.lock.json`` (source name -> {ref|version: value})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Lock file {path} must contain a JSON object")
    lock: dict[str, dict[str, str]] = {}
    for name, entry in data.items():
        if not isinstance(entry, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in entry.items()
        ):
            raise ValueError(f"Lock entry {name!r} in {path} must be an object of strings")
        lock[str(name)] = dict(entry)
    return lock


def sync_git_repo(
    name: str,
    url: str,
    target_dir: Path,
    *,
    github_token: str | None = None,
    ref: str | None = None,
) -> dict[str, str]:
    """Fetch (--depth 1) a read-only git repository at ``ref`` (default: remote HEAD) idempotently."""
    env = _build_git_env(github_token if "github.com" in url else None)
    git_dir = target_dir / ".git"

    if git_dir.is_dir():
        LOGGER.info("Updating git source '%s' in %s", name, target_dir)
        _run_git(["remote", "set-url", "origin", url], cwd=target_dir, env=env)
    else:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True)
        LOGGER.info("Initializing git source '%s' in %s", name, target_dir)
        _run_git(["init", "-q"], cwd=target_dir, env=env)
        _run_git(["remote", "add", "origin", url], cwd=target_dir, env=env)

    try:
        _run_git(["fetch", "--depth", "1", "origin", ref or "HEAD"], cwd=target_dir, env=env)
        _run_git(["reset", "--hard", "FETCH_HEAD"], cwd=target_dir, env=env)
        _run_git(["clean", "-fd"], cwd=target_dir, env=env)
        commit = _run_git(["rev-parse", "HEAD"], cwd=target_dir, env=env)
    except RuntimeError as exc:
        raise RuntimeError(f"Source '{name}' could not be synced at ref {ref or 'HEAD'!r}: {exc}") from exc
    if ref and _SHA_RE.fullmatch(ref) and commit != ref:
        raise RuntimeError(f"Source '{name}' resolved to {commit}, expected pinned {ref}")
    meta = {"type": "git", "url": url, "commit": commit}
    if ref:
        meta["ref"] = ref
    return meta


def _validate_https_url(url: str, *, allowed_host: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != allowed_host:
        raise ValueError(f"Unexpected URL host or scheme: {url!r} (expected https://{allowed_host})")


def _verify_integrity(data: bytes, integrity: str | None, shasum: str | None) -> None:
    """Verify npm tarball integrity (SRI sha512 or legacy sha1 shasum)."""
    if integrity and integrity.startswith("sha512-"):
        expected = integrity.removeprefix("sha512-")
        actual = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
        if actual != expected:
            raise ValueError("Tarball SHA-512 integrity check failed")
        return
    if shasum:
        actual_sha1 = hashlib.sha1(data, usedforsecurity=False).hexdigest()
        if actual_sha1 != shasum:
            raise ValueError("Tarball SHA-1 checksum verification failed")


def safe_extract_tarball(tarball_path: Path, destination: Path) -> None:
    """Extract a .tgz archive safely, blocking tar-slip traversal, links, and special files."""
    dest_resolved = destination.resolve()
    dest_resolved.mkdir(parents=True, exist_ok=True)
    total_extracted = 0

    with tarfile.open(tarball_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            # Reject symlinks, hardlinks, FIFOs, devices
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"Refusing unsafe tar member type: {member.name!r}")

            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Tar-slip path traversal detected: {member.name!r}")

            # Strip leading npm 'package/' directory when present
            parts = member_path.parts
            rel_parts = parts[1:] if parts and parts[0] == "package" else parts
            if not rel_parts:
                continue

            target_path = (dest_resolved / Path(*rel_parts)).resolve()
            if not target_path.is_relative_to(dest_resolved):
                raise ValueError(f"Tar member escapes destination: {member.name!r}")

            if member.isdir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            total_extracted += member.size
            if total_extracted > MAX_TAR_BYTES:
                raise ValueError(f"Tarball exceeds maximum allowed size ({MAX_TAR_BYTES} bytes)")

            target_path.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            with extracted, target_path.open("wb") as out_file:
                shutil.copyfileobj(extracted, out_file)


def sync_npm_modern_web_guidance(
    target_dir: Path,
    *,
    version: str = "latest",
) -> dict[str, str]:
    """Download and safely extract the compiled `modern-web-guidance` npm package."""
    metadata_url = f"https://{NPM_REGISTRY_HOST}/{NPM_PACKAGE_NAME}/{urllib.parse.quote(version)}"
    _validate_https_url(metadata_url, allowed_host=NPM_REGISTRY_HOST)
    LOGGER.info("Fetching npm metadata for %s@%s", NPM_PACKAGE_NAME, version)

    req = urllib.request.Request(metadata_url, headers={"Accept": "application/json"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        metadata: dict[str, Any] = json.loads(resp.read().decode("utf-8"))

    resolved_version = str(metadata.get("version", version))
    dist = metadata.get("dist", {})
    tarball_url = str(dist.get("tarball", ""))
    if not tarball_url:
        raise RuntimeError(f"npm metadata for {NPM_PACKAGE_NAME}@{version} missing dist.tarball")
    _validate_https_url(tarball_url, allowed_host=NPM_REGISTRY_HOST)

    LOGGER.info("Downloading %s@%s tarball", NPM_PACKAGE_NAME, resolved_version)
    with urllib.request.urlopen(tarball_url, timeout=HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        tarball_bytes = resp.read()

    if len(tarball_bytes) > MAX_TAR_BYTES:
        raise ValueError(f"Downloaded tarball exceeds {MAX_TAR_BYTES} bytes")

    _verify_integrity(
        tarball_bytes,
        integrity=dist.get("integrity"),
        shasum=dist.get("shasum"),
    )
    sha256_hex = hashlib.sha256(tarball_bytes).hexdigest()

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target_dir.parent) as tmp_str:
        tmp_path = Path(tmp_str)
        tgz_path = tmp_path / "package.tgz"
        tgz_path.write_bytes(tarball_bytes)

        staging_dir = tmp_path / "extracted"
        safe_extract_tarball(tgz_path, staging_dir)

        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(staging_dir), str(target_dir))

    return {
        "type": "npm",
        "package": NPM_PACKAGE_NAME,
        "version": resolved_version,
        "tarball_sha256": sha256_hex,
    }


def sync_all(
    skills_dir: Path,
    *,
    github_token: str | None = None,
    sources: list[str] | None = None,
    lock: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Synchronize all configured sources and write ``.sync_meta.json``.

    With ``lock`` each source is pinned to its locked ref/version; without it the
    latest upstream state is fetched.
    """
    lock = lock or {}
    skills_dir = skills_dir.resolve()
    skills_dir.mkdir(parents=True, exist_ok=True)

    meta_path = skills_dir / ".sync_meta.json"
    existing_sources: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            existing_sources = json.loads(meta_path.read_text(encoding="utf-8")).get("sources", {})
        except (OSError, json.JSONDecodeError):
            existing_sources = {}

    selected = set(sources) if sources else set(ALL_SOURCES)
    updated_sources: dict[str, Any] = dict(existing_sources)

    for name, url in GIT_SOURCES.items():
        if name not in selected:
            continue
        updated_sources[name] = sync_git_repo(
            name,
            url,
            skills_dir / name,
            github_token=github_token,
            ref=lock.get(name, {}).get("ref"),
        )

    if "modern-web-guidance" in selected:
        updated_sources["modern-web-guidance"] = sync_npm_modern_web_guidance(
            skills_dir / "modern-web-guidance",
            version=lock.get(NPM_PACKAGE_NAME, {}).get("version", "latest"),
        )

    meta: dict[str, Any] = {
        "synced_at": datetime.now(tz=UTC).isoformat(),
        "sources": updated_sources,
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    LOGGER.info("Sync completed successfully. Metadata written to %s", meta_path)
    return meta


def _write_lock(
    path: Path,
    old: dict[str, dict[str, str]],
    meta: dict[str, Any],
    sources: list[str] | None,
) -> None:
    """Rewrite the lock with refs resolved by a latest-sync (branch-tracking sources keep their ref)."""
    selected = set(sources) if sources else set(ALL_SOURCES)
    new = {name: dict(entry) for name, entry in old.items()}
    resolved = meta["sources"]
    if "superpowers" in selected:
        new["superpowers"] = {"ref": str(resolved["superpowers"]["commit"])}
    if "my_skills" in selected:
        new["my_skills"] = dict(old.get("my_skills", {"ref": "main"}))
    if "modern-web-guidance" in selected:
        new["modern-web-guidance"] = {"version": str(resolved["modern-web-guidance"]["version"])}
    path.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("Lock file %s updated", path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync skills sources for DevTeam Skills MCP")
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=Path(os.environ.get("SKILLS_DIR", "./skills_store")),
        help="Target directory for synced skills (default: $SKILLS_DIR or ./skills_store)",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=["superpowers", "my_skills", "modern-web-guidance"],
        help="Sync only specific source(s); repeatable",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=DEFAULT_LOCK_PATH,
        help="Lock file pinning source versions (default: config/sources.lock.json)",
    )
    parser.add_argument(
        "--update-lock",
        action="store_true",
        help="Sync to the latest upstream state and rewrite the lock file with resolved refs",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    try:
        lock = load_lock(args.lock)
        token = os.environ.get("GITHUB_TOKEN") or None
        if args.update_lock:
            meta = sync_all(args.skills_dir, github_token=token, sources=args.source, lock=None)
            _write_lock(args.lock, lock, meta, args.source)
        else:
            sync_all(args.skills_dir, github_token=token, sources=args.source, lock=lock)
    except (RuntimeError, ValueError, OSError, urllib.error.URLError) as exc:
        LOGGER.error("Skill sync failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
