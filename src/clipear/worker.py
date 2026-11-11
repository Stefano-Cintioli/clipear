"""Detached worker entry point; its logs never enter MCP protocol stdout."""
import argparse

from .config import Settings
from .service import Service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("job_id")
    args = parser.parse_args()
    Service(Settings.from_env(args.home), start_workers=False).run_job(args.job_id)


if __name__ == "__main__":
    main()
