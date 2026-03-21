"""Backtest service entry point (stub)."""
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Backtest service started (stub — not yet implemented)")
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
