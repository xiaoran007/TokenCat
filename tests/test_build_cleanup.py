import subprocess
from pathlib import Path


def test_python_cleanup_preserves_app_and_candidate_artifacts(tmp_path):
    files = ["build/TokenCat.app/Contents/Info.plist", "candidate/dist/candidate.whl",
             "build/lib/tokencat/cli.py", "build/bdist.test/temporary", "dist/stable.whl",
             "src/tokencat.egg-info/PKG-INFO"]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    makefile = Path(__file__).resolve().parents[1] / "Makefile"
    subprocess.run(["make", "-f", str(makefile), "-C", str(tmp_path), "clean"], check=True, capture_output=True)
    assert (tmp_path / files[0]).exists()
    assert (tmp_path / files[1]).exists()
    assert all(not (tmp_path / name).exists() for name in files[2:])
