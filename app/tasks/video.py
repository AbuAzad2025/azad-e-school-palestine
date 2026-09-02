"""Video transcoding — Celery tasks for HLS generation with encryption.

P5-05: FFmpeg pipeline generating 720p/1080p variant HLS playlists.
P5-06: AES-128 encrypted 4-second .ts segments.
P5-07: Output stored in non-public protected_media directory.
P5-08: Full cleanup on failure (no orphaned files).
"""

from __future__ import annotations

from app.tasks import _HAS_CELERY

if not _HAS_CELERY:
    raise ImportError("Celery is required for app.tasks.video")

import os
import shutil
import subprocess
import tempfile
from typing import Any

from app.core.logging import get_logger
from app.tasks import ContextTask, celery_app

logger = get_logger(__name__)


@celery_app.task(base=ContextTask, bind=True, max_retries=2, time_limit=1800)
def transcode_video_to_hls(
    self,
    lesson_id: int,
    source_file_path: str,
    school_id: int,
) -> dict:
    """Transcode a video file to HLS with multi-quality variants and encryption.

    Pipeline:
        1. Probe source for duration/resolution
        2. Generate AES-128 encryption key
        3. Transcode to 720p and 1080p variants
        4. Create master playlist referencing both variants
        5. Encrypt all .ts segments
        6. Store everything in protected_media/{school_id}/{lesson_id}/

    Args:
        lesson_id: Target lesson ID (for storage path).
        source_file_path: Absolute path to source video file.
        school_id: School ID (for tenancy-scoped storage).

    Returns:
        {"status": "completed" | "failed", "output_dir": str, "error": str | None}
    """
    from app.core.db import tx
    from app.models.content import LessonAttachment

    output_dir = _get_output_dir(school_id, lesson_id)
    temp_dir = None

    try:
        # Validate source file exists
        if not os.path.exists(source_file_path):
            return {
                "status": "failed",
                "output_dir": "",
                "error": f"Source file not found: {source_file_path}",
            }

        # Create temp working directory
        temp_dir = tempfile.mkdtemp(prefix="azad_hls_")

        # Step 1: Probe source video
        probe = _probe_video(source_file_path)
        if probe is None:
            return {
                "status": "failed",
                "output_dir": "",
                "error": "Failed to probe source video",
            }

        # Step 2: Generate encryption key
        key_path = os.path.join(temp_dir, "encryption.key")
        key_id_path = os.path.join(temp_dir, "key_info.txt")
        _generate_encryption_key(key_path, key_id_path)

        # Step 3: Transcode variants
        variants = [
            {"name": "720p", "height": 720, "bitrate": "2800k", "maxrate": "2996k", "bufsize": "4200k"},
            {"name": "1080p", "height": 1080, "bitrate": "5000k", "maxrate": "5350k", "bufsize": "7500k"},
        ]

        variant_playlists = []
        for variant in variants:
            if probe.get("height", 0) >= variant["height"]:
                playlist = _transcode_variant(source_file_path, temp_dir, variant, key_id_path)
                if playlist:
                    variant_playlists.append({"name": variant["name"], "playlist": playlist})

        # Fallback: if source is lower than 720p, just use source resolution
        if not variant_playlists:
            playlist = _transcode_variant(
                source_file_path,
                temp_dir,
                {"name": "source", "height": 0, "bitrate": "2000k", "maxrate": "2140k", "bufsize": "3000k"},
                key_id_path,
            )
            if playlist:
                variant_playlists.append({"name": "source", "playlist": playlist})

        if not variant_playlists:
            return {
                "status": "failed",
                "output_dir": "",
                "error": "No variants could be generated",
            }

        # Step 4: Create master playlist
        _create_master_playlist(temp_dir, variant_playlists)

        # Step 5: Move all outputs to protected storage
        os.makedirs(output_dir, exist_ok=True)
        shutil.copytree(temp_dir, output_dir, dirs_exist_ok=True)

        # Step 6: Update lesson attachment record
        def _update_attachment():
            att = LessonAttachment.query.filter_by(lesson_id=lesson_id).first()
            if att:
                att.kind = "video"
                att.stored_name = f"protected_media/{school_id}/{lesson_id}/master.m3u8"

        tx(_update_attachment)

        logger.info(
            "hls_transcode_completed",
            lesson_id=lesson_id,
            school_id=school_id,
            variants=len(variant_playlists),
            output_dir=output_dir,
        )

        return {
            "status": "completed",
            "output_dir": output_dir,
            "error": None,
        }

    except Exception as exc:
        logger.exception(
            "hls_transcode_failed",
            lesson_id=lesson_id,
            school_id=school_id,
        )
        # Cleanup on failure
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        if output_dir and os.path.exists(output_dir):
            shutil.rmtree(output_dir, ignore_errors=True)
        return {
            "status": "failed",
            "output_dir": "",
            "error": str(exc),
        }

    finally:
        # Cleanup temp directory on success too
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def _get_output_dir(school_id: int, lesson_id: int) -> str:
    """Get protected media output directory."""
    from flask import current_app

    base = current_app.config.get(
        "PROTECTED_MEDIA_FOLDER",
        os.path.join(
            str(current_app.config.get("UPLOAD_FOLDER", "instance/uploads")),
            "protected_media",
        ),
    )
    return os.path.join(str(base), str(school_id), str(lesson_id))


def _probe_video(source_path: str) -> dict[str, Any] | None:
    """Probe video file for metadata using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                source_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        import json

        return json.loads(result.stdout)
    except Exception:
        return None


def _generate_encryption_key(key_path: str, key_info_path: str) -> None:
    """Generate AES-128 encryption key and key info file."""
    import secrets

    key = secrets.token_bytes(16)  # 128-bit key
    with open(key_path, "wb") as f:
        f.write(key)

    # Key info format: URI;key_path;IV (IV auto-generated by ffmpeg)
    with open(key_info_path, "w") as f:
        f.write(f"encryption.key\n{key_path}\n")


def _transcode_variant(
    source_path: str,
    output_dir: str,
    variant: dict,
    key_id_path: str,
) -> str | None:
    """Transcode a single variant with HLS + AES-128 encryption."""
    name = variant["name"]
    bitrate = variant["bitrate"]
    maxrate = variant["maxrate"]
    bufsize = variant["bufsize"]
    height = variant["height"]

    playlist_name = f"{name}.m3u8"
    playlist_path = os.path.join(output_dir, playlist_name)
    segment_pattern = os.path.join(output_dir, f"{name}_%03d.ts")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        source_path,
    ]

    # Add scale filter for height-based variants
    if height > 0:
        cmd.extend(["-vf", f"scale=-2:{height}"])

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-b:v",
            bitrate,
            "-maxrate",
            maxrate,
            "-bufsize",
            bufsize,
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-hls_time",
            "4",
            "-hls_playlist_type",
            "vod",
            "-hls_segment_filename",
            segment_pattern,
            "-hls_key_info_file",
            key_id_path,
            playlist_path,
        ]
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            logger.error("ffmpeg_transcode_error", variant=name, stderr=result.stderr[:500])
            return None
        return playlist_name
    except Exception:
        return None


def _create_master_playlist(temp_dir: str, variants: list[dict]) -> str:
    """Create master HLS playlist referencing all variants."""
    master_path = os.path.join(temp_dir, "master.m3u8")

    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for variant in variants:
        name = variant["name"]
        # Map variant names to bandwidths
        bandwidths = {
            "720p": 3000000,
            "1080p": 5500000,
            "source": 2200000,
        }
        bw = bandwidths.get(name, 2200000)
        lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={bw},RESOLUTION={name}")
        lines.append(variant["playlist"])

    with open(master_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return master_path
