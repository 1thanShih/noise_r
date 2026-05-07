"""
SD card prep script
===================
Copy 30loop/ white noise files to sd_card_test/mp3/ with DFPlayer Mini naming.

  0001.mp3 <- 30min_camp_fire.mp3   (camp fire)
  0002.mp3 <- 30min_dark_noise.mp3  (dark noise)
  0003.mp3 <- 30min_ocean.mp3       (ocean)
  0004.mp3 <- 30min_rainy.mp3       (rainy)
  0005.mp3 <- 30min_coffee_shop.mp3 (coffee shop)
"""

import shutil
from pathlib import Path

BASE    = Path(__file__).parent
SRC_DIR = BASE / "30loop"
DST_DIR = BASE / "sd_card_test" / "mp3"

MAPPING = {
    "0001.mp3": "30min_camp_fire.mp3",
    "0002.mp3": "30min_dark_noise.mp3",
    "0003.mp3": "30min_ocean.mp3",
    "0004.mp3": "30min_rainy.mp3",
    "0005.mp3": "30min_coffee_shop.mp3",
}

def main():
    DST_DIR.mkdir(parents=True, exist_ok=True)

    for old in DST_DIR.glob("*.mp3"):
        old.unlink()
        print(f"  deleted: {old.name}")

    for dst_name, src_name in MAPPING.items():
        src_path = SRC_DIR / src_name
        dst_path = DST_DIR / dst_name

        if not src_path.exists():
            print(f"  [WARN] source not found: {src_path}")
            continue

        size_mb = src_path.stat().st_size / (1024 * 1024)
        print(f"  {src_name}  ->  {dst_name}  ({size_mb:.1f} MB)  ...", end="", flush=True)
        shutil.copy2(src_path, dst_path)
        print(" OK")

    print(f"\nDone! /mp3/ contents:")
    for f in sorted(DST_DIR.glob("*.mp3")):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name}  ({size_mb:.1f} MB)")

if __name__ == "__main__":
    main()
