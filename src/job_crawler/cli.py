"""CLI: python -m job_crawler [itviec|topcv|all]"""
from __future__ import annotations

import sys

from . import pipeline


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target == "itviec":
        print(pipeline.run_source("itviec"))
    elif target == "topcv":
        print(pipeline.run_source("topcv"))
    else:
        for r in pipeline.run_all():
            print(r)


if __name__ == "__main__":
    main()
