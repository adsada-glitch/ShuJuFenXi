import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="MovieLens temporal rating lab")
    parser.add_argument("command", choices=["run", "download"])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.command == "download":
        from .data import load_ratings
        ratings = load_ratings(args.data_dir)
        print(f"Verified {len(ratings):,} ratings")
    else:
        from .pipeline import run
        run(args.output_dir, args.data_dir, args.bootstrap, args.seed)


if __name__ == "__main__":
    main()
