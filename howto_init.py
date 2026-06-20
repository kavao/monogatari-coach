import shutil
from pathlib import Path


def copy_if_missing(src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"  Skipping {src.name} (source not found)")
        return
    if dst.exists():
        print(f"  Skipping {dst.name} (already exists)")
        return
    print(f"  Copying {src.name} -> {dst.name}")
    shutil.copy2(src, dst)


def howto_init():
    src = Path("_how_to.example")
    dst = Path("_how_to")

    if not src.exists():
        print(f"Error: Source directory '{src}' does not exist.")
        return

    if not dst.exists():
        print(f"Creating destination directory '{dst}'...")
        dst.mkdir(parents=True, exist_ok=True)

    print(f"Copying template files from '{src}' to '{dst}' (without overwriting existing files)...")

    # Copy files that don't exist in destination
    for item in src.iterdir():
        if item.is_file():
            copy_if_missing(item, dst / item.name)

    print("\nPreparing environment template files...")
    copy_if_missing(Path(".env.example"), Path(".env"))

    print("\nInitialization finished.")

if __name__ == "__main__":
    howto_init()
