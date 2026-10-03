from .server import main
import sys

main(open_window="--no-window" not in sys.argv)
