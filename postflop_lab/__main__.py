"""Convert stored Pio build commands to a local solver config."""

import argparse
import json
from pathlib import Path

from .client import import_pio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    converter = subcommands.add_parser("import-pio", help="print a JSON config to stdout")
    converter.add_argument("preset", type=Path)
    converter.add_argument("--rake-source", choices=("commands", "fields"), default="commands")
    args = parser.parse_args()
    try:
        config = import_pio(args.preset, rake_source=args.rake_source)
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(config, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
