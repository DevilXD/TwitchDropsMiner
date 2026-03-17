import shutil
import os
from pathlib import Path
import sys

def pack():
    # Define paths
    root_dir = Path.cwd()
    dist_dir = root_dir / "dist"
    pack_dir = root_dir / "Twitch Drops Miner"
    zip_name = "Twitch.Drops.Miner.Windows"
    
    if not dist_dir.exists():
        print(f"Error: {dist_dir} does not exist. Run 'just build' first.")
        sys.exit(1)

    # Prepare packaging directory
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir()
    
    # Copy executable(s)
    exe_found = False
    for exe in dist_dir.glob("*.exe"):
        print(f"Copying {exe.name}...")
        shutil.copy2(exe, pack_dir / exe.name)
        exe_found = True
    
    if not exe_found:
        print("Error: No .exe files found in dist folder.")
        sys.exit(1)
    
    # Copy manual
    manual = root_dir / "manual.txt"
    if manual.exists():
        print(f"Copying {manual.name}...")
        shutil.copy2(manual, pack_dir / manual.name)
    else:
        print("Warning: manual.txt not found, skipping.")
        
    # Create ZIP archive
    print(f"Creating {zip_name}.zip archive...")
    # shutil.make_archive creates the zip and appends .zip automatically
    shutil.make_archive(str(root_dir / zip_name), 'zip', root_dir=str(root_dir), base_dir=pack_dir.name)
    
    # Cleanup
    print("Cleaning up temporary packaging folder...")
    shutil.rmtree(pack_dir)
    
    print(f"Successfully packed into {zip_name}.zip")

if __name__ == "__main__":
    pack()
