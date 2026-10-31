"""Entry point: `python -m nodra.cli` and the `nodra` command both end up here."""
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["statusline"]:                     # Claude Code runs this on every status line redraw: skip the full CLI start
        from .statusline import bridge
        return bridge()
    from .main import main as full
    return full(argv)


if __name__ == "__main__":
    sys.exit(main())
