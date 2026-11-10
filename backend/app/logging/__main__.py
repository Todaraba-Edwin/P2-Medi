"""`python -m app.logging cleanup` : 14일 지난 개발 trace(logs/dev/)를 지운다(RFP-34-03 A)."""

import sys

from app.logging.spans import DEV_RETENTION_DAYS, cleanup_dev_logs


def main(argv: list[str]) -> int:
    if argv != ["cleanup"]:
        print(__doc__)
        return 2
    removed = cleanup_dev_logs(DEV_RETENTION_DAYS)
    print(f"삭제 {len(removed)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
