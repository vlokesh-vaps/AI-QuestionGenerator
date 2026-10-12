import os
import time
from pathlib import Path

from app.core.config import settings
from app.services.maintenance import cleanup_expired_storage_files


def test_cleanup_expired_storage_files(tmp_path, monkeypatch):
    test_marker_dir = tmp_path / "marker_cache"
    test_uploads_dir = tmp_path / "uploads"
    test_exports_dir = tmp_path / "exports"

    test_marker_dir.mkdir(parents=True)
    test_uploads_dir.mkdir(parents=True)
    test_exports_dir.mkdir(parents=True)

    monkeypatch.setattr(settings, "MARKER_CACHE_DIR", test_marker_dir)
    monkeypatch.setattr(settings, "UPLOADS_DIR", test_uploads_dir)
    monkeypatch.setattr(settings, "EXPORTS_DIR", test_exports_dir)

    now = time.time()

    # 1. Create expired marker cache file (older than 25h)
    old_marker = test_marker_dir / "pdf_old.json"
    old_marker.write_text('{"cached": true}', encoding="utf-8")
    os.utime(old_marker, (now - 25 * 3600, now - 25 * 3600))

    # 2. Create fresh marker cache file (1h old)
    fresh_marker = test_marker_dir / "pdf_fresh.json"
    fresh_marker.write_text('{"cached": true}', encoding="utf-8")
    os.utime(fresh_marker, (now - 3600, now - 3600))

    # 3. Create expired upload (older than 49h)
    old_upload = test_uploads_dir / "old_doc.pdf"
    old_upload.write_bytes(b"%PDF-old")
    os.utime(old_upload, (now - 50 * 3600, now - 50 * 3600))

    # 4. Create fresh upload (2h old)
    fresh_upload = test_uploads_dir / "fresh_doc.pdf"
    fresh_upload.write_bytes(b"%PDF-fresh")
    os.utime(fresh_upload, (now - 2 * 3600, now - 2 * 3600))

    # 5. Create expired export (older than 49h)
    old_export = test_exports_dir / "exam_old.docx"
    old_export.write_bytes(b"PK-old")
    os.utime(old_export, (now - 50 * 3600, now - 50 * 3600))

    # Execute cleanup
    summary = cleanup_expired_storage_files(
        marker_cache_max_age_hours=24.0,
        uploads_max_age_hours=48.0,
        exports_max_age_hours=48.0,
    )

    assert summary["marker_cache"] == 1
    assert summary["uploads"] == 1
    assert summary["exports"] == 1

    # Check preserved vs deleted files
    assert not old_marker.exists()
    assert fresh_marker.exists()

    assert not old_upload.exists()
    assert fresh_upload.exists()

    assert not old_export.exists()
