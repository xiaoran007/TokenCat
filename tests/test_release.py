import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import pytest


@pytest.fixture
def release():
    path = Path(__file__).resolve().parents[1] / "ci/release.py"
    spec = importlib.util.spec_from_file_location("release_checks", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata(version="0.9.0", name="tokencat"):
    return f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n\n".encode()


@pytest.fixture
def distributions(tmp_path):
    tags = ["macosx_11_0_arm64", "macosx_11_0_x86_64",
            "manylinux_2_17_x86_64.manylinux2014_x86_64",
            "manylinux_2_17_aarch64.manylinux2014_aarch64"]
    for tag in tags:
        with zipfile.ZipFile(tmp_path / f"tokencat-0.9.0-cp39-abi3-{tag}.whl", "w") as archive:
            archive.writestr("tokencat-0.9.0.dist-info/METADATA", metadata())
    source_metadata(tmp_path / "tokencat-0.9.0.tar.gz", metadata())
    return tmp_path


def source_metadata(path, content):
    with tarfile.open(path, "w:gz") as archive:
        entry = tarfile.TarInfo("tokencat-0.9.0/PKG-INFO")
        entry.size = len(content)
        archive.addfile(entry, io.BytesIO(content))


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Release version checks run on Python 3.14")
@pytest.mark.parametrize("mismatch", [None, "project", "runtime", "cargo", "lock"])
def test_release_requires_consistent_project_runtime_binding_and_lock_versions(tmp_path, release, mismatch):
    versions = {name: "0.9.0" for name in ("project", "runtime", "cargo", "lock")}
    if mismatch:
        versions[mismatch] = "0.8.0"
    (tmp_path / "bindings/python").mkdir(parents=True)
    (tmp_path / "src/tokencat").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname="tokencat"\nversion="{versions["project"]}"\n')
    (tmp_path / "src/tokencat/__init__.py").write_text(f'__version__ = "{versions["runtime"]}"\n')
    (tmp_path / "bindings/python/Cargo.toml").write_text(f'[package]\nname="tokencat-python"\nversion="{versions["cargo"]}"\n')
    (tmp_path / "bindings/python/Cargo.lock").write_text(f'[[package]]\nname="tokencat-python"\nversion="{versions["lock"]}"\n')
    if mismatch:
        with pytest.raises(ValueError, match="versions must match"):
            release.read_version(tmp_path)
    else:
        assert release.read_version(tmp_path) == "0.9.0"


def test_complete_distribution_set_is_ready_for_publish(distributions, release):
    assert len(release.verify_distributions(distributions, "0.9.0")) == 5


@pytest.mark.parametrize("problem", ["missing", "extra", "duplicate", "wrong-abi", "wrong-version"])
def test_incomplete_or_wrong_release_set_cannot_be_published(distributions, release, problem):
    path = next(distributions.glob("*aarch64.whl"))
    if problem == "missing":
        path.unlink()
    elif problem == "extra":
        (distributions / "unrelated.txt").write_text("fixture")
    elif problem == "duplicate":
        path.rename(distributions / "tokencat-0.9.0-cp39-abi3-macosx_12_0_x86_64.whl")
    elif problem == "wrong-abi":
        path.rename(distributions / "tokencat-0.9.0-cp314-cp314-manylinux2014_aarch64.whl")
    else:
        path.rename(distributions / "tokencat-0.8.0-cp39-abi3-manylinux2014_aarch64.whl")
    with pytest.raises(ValueError):
        release.verify_distributions(distributions, "0.9.0")


@pytest.mark.parametrize("kind,name,version", [
    ("wheel", "tokencat", "0.8.0"), ("wheel", "other-package", "0.9.0"),
    ("source", "tokencat", "0.8.0"), ("source", "other-package", "0.9.0"),
])
def test_filenames_cannot_hide_wrong_package_metadata(distributions, release, kind, name, version):
    if kind == "wheel":
        path = next(distributions.glob("*aarch64.whl"))
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("tokencat-0.9.0.dist-info/METADATA", metadata(version, name))
    else:
        source_metadata(distributions / "tokencat-0.9.0.tar.gz", metadata(version, name))
    with pytest.raises(ValueError, match="metadata does not match"):
        release.verify_distributions(distributions, "0.9.0")


@pytest.mark.parametrize("tags", [
    "macosx_11_0_arm64.macosx_11_0_x86_64", "macosx_11_0_arm64.macosx_11_0_i386",
    "win_amd64", "linux_aarch64",
])
def test_unsupported_or_mixed_platform_tags_fail(release, tags):
    with pytest.raises(ValueError):
        release.wheel_platform(tags)


@pytest.mark.parametrize("tag_kind", [None, "lightweight", "annotated"])
@pytest.mark.parametrize("matches", [True, False])
def test_release_tag_must_identify_the_tested_commit(tmp_path, release, tag_kind, matches):
    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Release test", "-c", "user.email=release@example.invalid", *args],
            cwd=tmp_path, text=True, stderr=subprocess.PIPE,
        ).strip()

    git("init")
    git("commit", "--allow-empty", "-m", "Previous version")
    previous = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "Tested release")
    tested = git("rev-parse", "HEAD")
    if tag_kind:
        target = tested if matches else previous
        if tag_kind == "annotated":
            git("tag", "-a", "v0.9.0", target, "-m", "Release")
        else:
            git("tag", "v0.9.0", target)
    if tag_kind and not matches:
        with pytest.raises(ValueError, match="Release tag v0.9.0 points to"):
            release.verify_release_tag(tmp_path, "0.9.0", tested)
    else:
        release.verify_release_tag(tmp_path, "0.9.0", tested)
