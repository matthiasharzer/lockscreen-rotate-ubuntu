#!/usr/bin/env python3
import argparse
import subprocess
import random
import sys
from pathlib import Path

# --- CONFIGURATION ---
# Supported video formats
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".avi", ".mov"}
# ---------------------


class VideoManager:
    def __init__(self, videos_dir: Path, symlink_path: Path) -> None:
        self.videos_dir = videos_dir
        self.symlink_path = symlink_path

    def change_video(self) -> None:
        """Finds a random video and performs an atomic symlink update."""
        videos = [
            p
            for p in self.videos_dir.rglob("*")
            if p.suffix.lower() in VIDEO_EXTENSIONS
        ]

        if not videos:
            print(f"No videos found in {self.videos_dir}!", file=sys.stderr)
            return

        selected_video = random.choice(videos)

        # Create a temporary symlink first
        temp_symlink = self.symlink_path.with_suffix(".tmp")

        try:
            if temp_symlink.exists() or temp_symlink.is_symlink():
                temp_symlink.unlink()

            temp_symlink.symlink_to(selected_video)

            # Atomically replace the old symlink with the new one
            temp_symlink.rename(self.symlink_path)
            print(f"Updated lockscreen video to: {selected_video.name}", flush=True)
        except Exception as e:
            print(f"Failed to update symlink: {e}", file=sys.stderr)

    def listen_for_unlock(self) -> None:
        """Listens to KDE's DBus signals for screen unlock events."""
        cmd = [
            "dbus-monitor",
            "--session",
            "type='signal',interface='org.freedesktop.ScreenSaver',member='ActiveChanged'",
        ]

        print("Starting lockscreen monitor...", flush=True)
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True)

        if process.stdout is None:
            raise ValueError("process has no stdout")

        for line in process.stdout:
            # 'boolean false' means the screensaver/lockscreen just deactivated
            # (unlocked)
            if "boolean false" in line:
                self.change_video()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Apple Wallpaper Lockscreen Rotate Daemon"
    )
    parser.add_argument(
        "--symlink", required=True, help="Path where the symlink should be created"
    )
    parser.add_argument(
        "--directory", required=True, help="The base path to discover video files"
    )
    args = parser.parse_args()

    symlinkPath = Path(args.symlink)
    directory = Path(args.directory)

    videoManager = VideoManager(directory, symlinkPath)
    videoManager.change_video()
    videoManager.listen_for_unlock()
