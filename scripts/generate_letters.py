"""
QuantLetter generator — saves A/B-axis letters to letterService/.

Usage:
  python scripts/generate_letters.py           # current month + current week
  python scripts/generate_letters.py --month 2026-10
  python scripts/generate_letters.py --week 2026-W47 --as-of 2026-11-21
  python scripts/generate_letters.py --all-oct-nov   # backfill Oct + Nov 2026
"""
import argparse
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.letter_a_generator import save_a_monthly_letter, _download_prices
from utils.letter_b_generator import save_b_weekly_letter


def _week_label(dt: datetime) -> str:
    return dt.strftime("%G-W%V")


def _prev_week_friday(as_of: datetime) -> str:
    # Friday = weekday 4
    days_back = (as_of.weekday() + 3) % 7 + 1   # days to last Friday
    return (as_of - timedelta(days=days_back)).strftime("%Y-%m-%d")


_LETTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "letterService")
_INDEX_HTML  = os.path.join(_LETTER_DIR, "index.html")
_INDEX_JSON  = os.path.join(_LETTER_DIR, "letterIndex.json")


def _update_index():
    """Regenerate letterIndex.json and patch KNOWN_FILES in index.html."""
    import json, re

    files = sorted(
        [f for f in os.listdir(_LETTER_DIR)
         if f.endswith(".html") and f != "index.html"],
        reverse=True,
    )
    # Write JSON index
    with open(_INDEX_JSON, "w", encoding="utf-8") as f:
        json.dump(files, f, ensure_ascii=False, indent=2)
    print(f"[index] letterIndex.json updated ({len(files)} letters)")

    # Patch KNOWN_FILES array inside index.html
    if not os.path.exists(_INDEX_HTML):
        return
    with open(_INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    new_array = "[\n" + ",\n".join(f'  "{fn}"' for fn in files) + ",\n]"
    html = re.sub(r"const KNOWN_FILES = \[[\s\S]*?\];",
                  f"const KNOWN_FILES = {new_array};", html)
    with open(_INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[index] index.html KNOWN_FILES updated")


def run(args):
    today = datetime.today()

    if args.all_oct_nov:
        # Backfill Oct + Nov 2026
        print("=== Backfill: Oct + Nov 2026 ===\n")
        prices = _download_prices()

        for month, prev in [("2026-10", "2026-09"), ("2026-11", "2026-10")]:
            path = save_a_monthly_letter(month, prev_month=prev, prices=prices)
            print(f"[A] {month} -> {path}")

        weekly_runs = [
            ("2026-W41", "2026-10-09", "2026-10-03"),
            ("2026-W42", "2026-10-16", "2026-10-09"),
            ("2026-W43", "2026-10-24", "2026-10-16"),
            ("2026-W44", "2026-10-31", "2026-10-24"),
            ("2026-W45", "2026-11-07", "2026-10-31"),
            ("2026-W46", "2026-11-14", "2026-11-07"),
            ("2026-W47", "2026-11-21", "2026-11-14"),
        ]
        for week, as_of, prev in weekly_runs:
            path = save_b_weekly_letter(week, as_of_date=as_of, prev_as_of_date=prev)
            print(f"[B] {week} -> {path}")
        return

    if args.month:
        prices = _download_prices()
        path = save_a_monthly_letter(args.month, prices=prices)
        print(f"[A] {args.month} -> {path}")

    if args.week:
        if not args.as_of:
            print("--week requires --as-of YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
        path = save_b_weekly_letter(args.week, as_of_date=args.as_of,
                                     prev_as_of_date=args.prev_as_of)
        print(f"[B] {args.week} -> {path}")

    if not args.month and not args.week and not args.all_oct_nov:
        # Default: generate current month A + current week B
        cur_month = today.strftime("%Y-%m")
        prev_month_dt = (today.replace(day=1) - timedelta(days=1))
        prev_month = prev_month_dt.strftime("%Y-%m")

        # Last Friday as end-of-week
        days_since_fri = (today.weekday() - 4) % 7
        last_fri = today - timedelta(days=days_since_fri)
        prev_fri = last_fri - timedelta(days=7)

        print(f"=== Generating current letters ({today.date()}) ===\n")
        prices = _download_prices()

        path = save_a_monthly_letter(cur_month, prev_month=prev_month, prices=prices)
        print(f"[A] {cur_month} -> {path}")

        week = _week_label(last_fri)
        path = save_b_weekly_letter(week,
                                     as_of_date=last_fri.strftime("%Y-%m-%d"),
                                     prev_as_of_date=prev_fri.strftime("%Y-%m-%d"))
        print(f"[B] {week} -> {path}")

    _update_index()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate QuantLetters locally")
    parser.add_argument("--month",   help="A-axis month e.g. 2026-10")
    parser.add_argument("--week",    help="B-axis week label e.g. 2026-W47")
    parser.add_argument("--as-of",  dest="as_of", help="End-of-week date YYYY-MM-DD")
    parser.add_argument("--prev-as-of", dest="prev_as_of", help="Prior week end date")
    parser.add_argument("--all-oct-nov", action="store_true", help="Backfill Oct+Nov 2026")
    run(parser.parse_args())
