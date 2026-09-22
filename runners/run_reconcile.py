from core.kill_switch import KillSwitch
from reconciliation.reconciler import Reconciler
from runners.runtime import build_runtime


def main() -> int:
    runtime = build_runtime()
    mismatches = Reconciler(runtime.broker, runtime.store,
                            KillSwitch(runtime.config.kill_switch_path)).run()
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())