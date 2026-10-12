import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, Tuple

from app.core.config import settings

logger = logging.getLogger("ai_question_generator.maintenance")


def cleanup_expired_storage_files(
    marker_cache_max_age_hours: float = 24.0,
    uploads_max_age_hours: float = 48.0,
    exports_max_age_hours: float = 48.0,
) -> Dict[str, int]:
    """Scans runtime storage directories and deletes files exceeding their max age threshold.

    Args:
        marker_cache_max_age_hours: Max lifetime for marker index JSON files (default 24h).
        uploads_max_age_hours: Max lifetime for uploaded PDF/DOCX files (default 48h).
        exports_max_age_hours: Max lifetime for generated export files (default 48h).

    Returns:
        Dict reporting the number of deleted files per category.
    """
    now = time.time()
    targets: Tuple[Tuple[str, Path, float, str], ...] = (
        ("marker_cache", settings.MARKER_CACHE_DIR, marker_cache_max_age_hours * 3600, "*.json"),
        ("uploads", settings.UPLOADS_DIR, uploads_max_age_hours * 3600, "*"),
        ("exports", settings.EXPORTS_DIR, exports_max_age_hours * 3600, "*"),
    )

    results: Dict[str, int] = {
        "marker_cache": 0,
        "uploads": 0,
        "exports": 0,
    }

    for key, directory, max_age_seconds, pattern in targets:
        if not directory.exists() or not directory.is_dir():
            continue

        try:
            for item in directory.glob(pattern):
                if not item.is_file():
                    continue
                try:
                    file_age = now - item.stat().st_mtime
                    if file_age >= max_age_seconds:
                        item.unlink(missing_ok=True)
                        results[key] += 1
                except (OSError, FileNotFoundError) as err:
                    logger.debug("Failed to delete expired file %s: %s", item, err)
        except OSError as err:
            logger.warning("Error scanning directory %s: %s", directory, err)

    total_deleted = sum(results.values())
    if total_deleted > 0:
        logger.info(
            "Scheduled storage cleanup finished. Deleted %d file(s): %s",
            total_deleted,
            results,
        )

    return results


async def run_periodic_maintenance(
    interval_seconds: float = 24 * 3600,
    initial_delay_seconds: float = 60,
    marker_cache_max_age_hours: float = 24.0,
    uploads_max_age_hours: float = 48.0,
    exports_max_age_hours: float = 48.0,
) -> None:
    """Async background task that runs periodic storage maintenance at regular intervals.

    Args:
        interval_seconds: Frequency between cleanup passes (defaults to 24 hours).
        initial_delay_seconds: Brief initial delay before the first run after startup.
        marker_cache_max_age_hours: Threshold for cached chapter markers.
        uploads_max_age_hours: Threshold for uploaded files.
        exports_max_age_hours: Threshold for generated exports.
    """
    try:
        if initial_delay_seconds > 0:
            await asyncio.sleep(initial_delay_seconds)

        while True:
            try:
                cleanup_expired_storage_files(
                    marker_cache_max_age_hours=marker_cache_max_age_hours,
                    uploads_max_age_hours=uploads_max_age_hours,
                    exports_max_age_hours=exports_max_age_hours,
                )
            except Exception as err:
                logger.error("Unexpected error during periodic storage cleanup: %s", err, exc_info=True)

            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Periodic maintenance scheduler stopped.")
        raise
