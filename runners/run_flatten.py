import sys
from time import perf_counter
from uuid import uuid4

from observability.logging_setup import configure_logging
from observability.notifier import alert
from runners.runtime import build_runtime


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if "--confirm" not in argv:
        print("Refusing to flatten positions without --confirm.")
        return 2
    logger = configure_logging()
    run_id = str(uuid4())
    started = perf_counter()
    logger.warning("flatten_started", extra={"run_id": run_id, "extra_payload": {"runner": "flatten"}})
    try:
        orders = build_runtime().flatten_cycle()
    except Exception as exc:
        logger.error("flatten_failed", extra={"run_id": run_id, "extra_payload": {"error": str(exc)}})
        alert(f"flatten run failed: {exc}", level="error")
        return 1
    logger.warning(
        "flatten_completed",
        extra={
            "run_id": run_id,
            "extra_payload": {
                "orders_attempted": len(orders),
                "duration_seconds": round(perf_counter() - started, 3),
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
