"""CLI cache builder for a season's public Statcast hitter table."""
from __future__ import annotations
import argparse
from pathlib import Path
from data_fetcher import get_hitter_stats

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--season", type=int, required=True); parser.add_argument("--output", default=None); args = parser.parse_args()
    output = Path(args.output or f"work/hitter_stats_{args.season}.csv"); output.parent.mkdir(parents=True, exist_ok=True)
    get_hitter_stats(args.season).to_csv(output, index=False); print(output)
if __name__ == "__main__": main()
"""CLI cache builder for a season's public Statcast hitter table."""
from __future__ import annotations
import argparse
from pathlib import Path
from data_fetcher import get_hitter_stats

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--season", type=int, required=True); parser.add_argument("--output", default=None); args = parser.parse_args()
    output = Path(args.output or f"work/hitter_stats_{args.season}.csv"); output.parent.mkdir(parents=True, exist_ok=True)
    get_hitter_stats(args.season).to_csv(output, index=False); print(output)
if __name__ == "__main__": main()
