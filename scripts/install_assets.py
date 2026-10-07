"""CLI wrapper for the product asset installer; no floating revisions."""
import argparse
from pathlib import Path
from local_vision_solver.app_paths import AppPaths
from local_vision_solver.asset_installer import AssetInstaller


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--runtime-only',action='store_true')
    group.add_argument('--models-only',action='store_true')
    args=parser.parse_args()
    paths=AppPaths.for_user(args.data_dir)
    installer=AssetInstaller(paths,progress=lambda p:print(f"{p['stage']}: {p['asset_id']} {p['bytes']}/{p['total']}",flush=True))
    installer.install(runtime_only=args.runtime_only,models_only=args.models_only)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
