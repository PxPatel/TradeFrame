from time import perf_counter
from uuid import uuid4

from core.kill_switch import KillSwitch
from observability.logging_setup import configure_logging
from observability.notifier import alert
from reconciliation.reconciler import Reconciler
from runners.runtime import build_runtime


def main() -> int:
    logger = configure_logging()
    run_id = str(uuid4())
    started = perf_counter()
    logger.info("run_started", extra={"run_id": run_id, "extra_payload": {"runner": "reconcile"}})
    runtime = build_runtime()
    mismatches = Reconciler(runtime.broker, runtime.store,
                            KillSwitch(runtime.config.kill_switch_path)).run()
    if mismatches:
        logger.error("reconcile_mismatches", extra={"run_id": run_id, "extra_payload": {"count": len(mismatches)}})
        alert(f"reconciliation found {len(mismatches)} mismatch(es)", level="error")
    logger.info(
        "run_completed",
        extra={
            "run_id": run_id,
            "extra_payload": {
                "runner": "reconcile",
                "mismatch_count": len(mismatches),
                "duration_seconds": round(perf_counter() - started, 3),
            },
        },
    )
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())