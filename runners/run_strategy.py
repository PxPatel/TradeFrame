from runners.runtime import build_runtime


def main() -> int:
    build_runtime().strategy_cycle()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())