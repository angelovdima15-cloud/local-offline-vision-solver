"""Entry point for the portable Windows backend."""
import multiprocessing
from local_vision_solver.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
