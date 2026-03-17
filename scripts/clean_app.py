import shutil
from pathlib import Path
import sys

def clean():
    root_dir = Path.cwd()
    targets = [
        root_dir / "dist",
        root_dir / "build",
        root_dir / ".venv",
        root_dir / "Twitch.Drops.Miner.Windows.zip",
        root_dir / "Twitch Drops Miner",
    ]
    
    for target in targets:
        if target.exists():
            print(f"Removing {target.name}...")
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            except Exception as e:
                print(f"Failed to remove {target}: {e}")

if __name__ == "__main__":
    clean()
