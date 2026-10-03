"""Validate CLI release versions and the exact distribution set uploaded by Actions."""
import argparse
import ast
from email.parser import BytesParser
import re
from pathlib import Path
import tarfile
import zipfile


PLATFORMS = {"macos-arm64", "macos-x86_64", "linux-arm64", "linux-x86_64"}


def read_version(root):
    # Release jobs use Python 3.14; this helper is not part of the CLI runtime.
    import tomllib
    root = Path(root)
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    cargo = tomllib.loads((root / "bindings/python/Cargo.toml").read_text())["package"]
    lock = tomllib.loads((root / "bindings/python/Cargo.lock").read_text())["package"]
    assignments = [node for node in ast.parse((root / "src/tokencat/__init__.py").read_text()).body
                   if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__version__"
                                                         for target in node.targets)]
    if len(assignments) != 1:
        raise ValueError("Expected one CLI __version__ assignment")
    runtime = ast.literal_eval(assignments[0].value)
    locked = [package["version"] for package in lock if package["name"] == "tokencat-python"]
    version = project["version"]
    if project["name"] != "tokencat" or cargo["name"] != "tokencat-python":
        raise ValueError("Unexpected release package name")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("CLI releases require an X.Y.Z version")
    if runtime != version or cargo["version"] != version or locked != [version]:
        raise ValueError("CLI, project, binding and lockfile versions must match")
    return version


def check_metadata(content, version):
    metadata = BytesParser().parsebytes(content)
    if metadata.get_all("Name") != ["tokencat"] or metadata.get_all("Version") != [version]:
        raise ValueError("Distribution metadata does not match this release")


def wheel_platform(tags):
    platforms = set()
    for tag in tags.split("."):
        if tag.startswith("macosx_") and tag.endswith("_arm64"):
            platforms.add("macos-arm64")
        elif tag.startswith("macosx_") and tag.endswith("_x86_64"):
            platforms.add("macos-x86_64")
        elif tag.startswith("manylinux") and tag.endswith("_aarch64"):
            platforms.add("linux-arm64")
        elif tag.startswith("manylinux") and tag.endswith("_x86_64"):
            platforms.add("linux-x86_64")
        else:
            raise ValueError(f"Unexpected wheel platform tag: {tag}")
    if len(platforms) != 1:
        raise ValueError(f"Unexpected wheel platform tags: {tags}")
    return platforms.pop()


def verify_distributions(directory, version):
    directory = Path(directory)
    files = sorted(directory.iterdir())
    wheels = [path for path in files if path.suffix == ".whl"]
    sources = [path for path in files if path.name.endswith(".tar.gz")]
    if len(files) != 5 or len(wheels) != 4 or len(sources) != 1:
        raise ValueError("Expected exactly four platform wheels and one source archive")
    platforms = []
    for path in wheels:
        parts = path.name[:-4].rsplit("-", 3)
        if len(parts) != 4 or parts[:3] != [f"tokencat-{version}", "cp39", "abi3"]:
            raise ValueError(f"Unexpected wheel filename: {path.name}")
        platforms.append(wheel_platform(parts[3]))
        with zipfile.ZipFile(path) as archive:
            check_metadata(archive.read(f"tokencat-{version}.dist-info/METADATA"), version)
    if set(platforms) != PLATFORMS:
        raise ValueError("Missing or duplicated release platform")
    if sources[0].name != f"tokencat-{version}.tar.gz":
        raise ValueError("Unexpected source archive filename")
    with tarfile.open(sources[0], "r:gz") as archive:
        metadata = archive.extractfile(f"tokencat-{version}/PKG-INFO")
        if metadata is None:
            raise ValueError("Source archive is missing PKG-INFO")
        with metadata:
            check_metadata(metadata.read(), version)
    return files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    version = read_version(args.root)
    if args.dist:
        for file in verify_distributions(args.dist, version):
            print(file.name)
    else:
        print(version)
