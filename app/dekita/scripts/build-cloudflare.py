"""Build only public game assets; never upload the repository directory."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist"


def build():
    if OUTPUT.is_symlink():
        raise RuntimeError("dist must not be a symbolic link")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    for name in ("index.html", "style.css", "favicon.svg", "migration.html", "migration.js", "_headers"):
        source = ROOT / name
        if source.is_symlink():
            raise RuntimeError(f"symbolic link is not a public asset: {name}")
        shutil.copyfile(source, OUTPUT / name)
    for folder, suffix in (("audio", ".mp3"), ("src/modules", ".js")):
        for source in sorted((ROOT / folder).rglob(f"*{suffix}")):
            if source.is_symlink():
                raise RuntimeError(f"symbolic link is not a public asset: {source}")
            target = OUTPUT / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    (OUTPUT / "src").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "src/main.js", OUTPUT / "src/main.js")
    print(f"Built {sum(p.is_file() for p in OUTPUT.rglob('*'))} public assets in {OUTPUT}")


if __name__ == "__main__":
    build()
