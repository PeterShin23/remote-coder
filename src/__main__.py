"""Allow `python -m src` execution."""

from .main import cli


if __name__ == "__main__":
    raise SystemExit(cli())
