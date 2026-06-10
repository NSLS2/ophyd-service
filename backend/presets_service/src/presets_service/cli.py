"""CLI entry point for the Presets Service."""

import argparse

import uvicorn

from .settings import Settings


def main() -> None:
    settings = Settings()

    parser = argparse.ArgumentParser(description="Presets Service")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()

    uvicorn.run(
        "presets_service.main:app",
        host=args.host,
        port=args.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
