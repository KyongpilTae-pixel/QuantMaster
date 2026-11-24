"""
C-axis trigger scanner CLI.

Usage:
    python scripts/scan_c_triggers.py                     # scan today
    python scripts/scan_c_triggers.py --as-of 2026-11-24  # specific date
    python scripts/scan_c_triggers.py --dry-run           # print only, no HTML
    python scripts/scan_c_triggers.py --types rates,vix   # specific types
"""
import argparse
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.c_trigger_scanner import scan_triggers
from utils.letter_c_generator import save_c_event_letter

_LETTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "letterService")


def _load_update_index():
    spec = importlib.util.spec_from_file_location(
        "generate_letters",
        os.path.join(os.path.dirname(__file__), "generate_letters.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._update_index


def main():
    parser = argparse.ArgumentParser(description="Scan C-axis triggers and generate draft letters")
    parser.add_argument("--as-of",  dest="as_of", default=None, help="Date YYYY-MM-DD (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Print triggers only, don't save HTML")
    parser.add_argument("--types",  default=None, help="Comma-separated types: rates,vix,fx,taa_gate,sector,macro")
    args = parser.parse_args()

    print(f"[scan_c] scanning {args.as_of or 'today'}...")
    triggers = scan_triggers(args.as_of)

    if args.types:
        allowed = set(args.types.split(","))
        triggers = [t for t in triggers if t["type"] in allowed]

    if not triggers:
        print("[scan_c] no triggers fired.")
        return

    print(f"\n[scan_c] {len(triggers)} trigger(s) fired:")
    for t in triggers:
        print(f"  [{t['type']:10s}] {t['title']}")

    if args.dry_run:
        print("\n[scan_c] dry-run: no letters saved.")
        return

    print()
    saved = []
    for t in triggers:
        # Skip if letter already exists for this slug
        fname = f"{t['event_date']}_C_{t['slug']}.html"
        dest  = os.path.join(_LETTER_DIR, fname)
        if os.path.exists(dest):
            print(f"[scan_c] skipped (exists): {fname}")
            continue

        path = save_c_event_letter(
            slug=t["slug"],
            title=t["title"],
            event_date=t["event_date"],
            tags=t.get("tags") or [],
            highlight=t.get("highlight"),
            sections=t.get("sections") or [],
            tables=t.get("tables"),
        )
        saved.append(path)
        print(f"[scan_c] saved: {os.path.basename(path)}")

    if saved:
        try:
            _load_update_index()()
            print("[scan_c] index updated.")
        except Exception as e:
            print(f"[scan_c] index update failed: {e}")

    print(f"\n[scan_c] done. {len(saved)} new letter(s) saved.")


if __name__ == "__main__":
    main()
