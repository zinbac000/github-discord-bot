import sys

from .config import ConfigError, load_settings


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2

    from .bot import run

    run(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
