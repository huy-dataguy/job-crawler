"""CLI: python -m job_crawler [itviec|topcv|topdev|all]"""
from __future__ import annotations

import sys

from . import pipeline


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target in pipeline.SOURCES:
        print(pipeline.run_source(target))
    else:
        for r in pipeline.run_all():
            print(r)


if __name__ == "__main__":
    main()
