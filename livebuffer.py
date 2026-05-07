#!/usr/bin/env python3
import argparse
import logging
import os
import time
import requests
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

# --- Configuration Constants ---
# These define the behavior when the script decides to download a new video.
DEFAULT_MAX_MOD_TIME_AFTER_UNLOCK = 60 * 30         # 30 minutes (in seconds)
DEFAULT_MAX_MOD_TIME_ON_TICK = 60 * 60 * 2          # 2 hours (in seconds)
CHECK_TICK_RATE_SECONDS = 60                        # Periodic timer check every 60 seconds

class VideoManager:
    def __init__(self, url: str, symlink_path: str, max_mod_time_on_tick: int, max_mod_time_after_unlock: int, initial_unlock_state: bool):
        self.url = url
        self.symlink_path = os.path.abspath(symlink_path)
        self.max_mod_time_on_tick = max_mod_time_on_tick
        self.max_mod_time_after_unlock = max_mod_time_after_unlock
        # Use a persistent cache directory in the user's local share folder
        self.storage_dir = os.path.expanduser('~/.local/share/video_updater_cache')
        os.makedirs(self.storage_dir, exist_ok=True)
        
        self.is_downloading = False
        self.is_screen_locked = initial_unlock_state

        logging.info(f"URL: {url} | symlink: {symlink_path} | max_mod_time_on_tick: {self.max_mod_time_on_tick} | max_mod_time_after_unlock: {self.max_mod_time_after_unlock}")

        

    def get_last_download_time(self):
        """
        Derives the last download time directly from the symlink's target.
        This makes the state persistent across PC reboots without needing a database.
        """
        try:
            # os.path.realpath resolves the symlink to the actual file
            real_path = os.path.realpath(self.symlink_path)
            if os.path.exists(real_path):
                return os.path.getmtime(real_path)
        except OSError:
            pass
        return 0.0

    def download_and_update(self, reason):
        """
        Handles the robust download, atomic symlinking, and cleanup operations.
        """
        if self.is_downloading:
            logging.info("Download already in progress. Skipping.")
            return

        self.is_downloading = True
        logging.info(f"Starting download. Triggered by: {reason}")
        
        timestamp = int(time.time())
        final_filename = os.path.join(self.storage_dir, f"video_{timestamp}.mp4")
        temp_filename = final_filename + ".part"

        try:
            # 1. Download to a temporary file
            # Timeout ensures the script doesn't hang indefinitely on network drops
            response = requests.get(self.url, stream=True, timeout=30)
            response.raise_for_status()

            with open(temp_filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 2. Rename temp file to final video file
            os.rename(temp_filename, final_filename)
            logging.info(f"Download complete: {final_filename}")

            # 3. Create/Update symlink atomically
            temp_symlink = self.symlink_path + ".tmp"
            if os.path.lexists(temp_symlink):
                os.remove(temp_symlink)
                
            os.symlink(final_filename, temp_symlink)
            # os.replace is atomic on POSIX. If a player is reading the old symlink,
            # it won't break. Next time it opens the link, it points to the new file.
            os.replace(temp_symlink, self.symlink_path)
            logging.info(f"Symlink updated: {self.symlink_path} -> {final_filename}")

            # 4. Clean up old files to keep disk footprint low
            self.cleanup_old_videos(keep_file=final_filename)

        except (requests.RequestException, OSError) as e:
            logging.error(f"Download or file operation failed: {e}")
            # Clean up the partial file if it exists
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
            logging.info("Symlink remains unchanged, pointing to the last valid video.")
        finally:
            self.is_downloading = False

    def cleanup_old_videos(self, keep_file):
        """
        Removes all files in the storage directory except the newly downloaded one.
        """
        for filename in os.listdir(self.storage_dir):
            file_path = os.path.join(self.storage_dir, filename)
            if file_path != keep_file and os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                    logging.info(f"Cleaned up old file: {filename}")
                except OSError as e:
                    logging.warning(f"Could not remove old file {filename}: {e}")

    def on_timer_tick(self):
        """
        Triggered periodically to check if self.max_mod_time_on_tick has been exceeded.
        """
        now = time.time()
        last = self.get_last_download_time()
        
        if (now - last) >= self.max_mod_time_on_tick:
            if self.is_screen_locked:
                logging.debug("self.max_mod_time_on_tick reached but screen is locked. waiting for unlock...")
            else:
                self.download_and_update("self.max_mod_time_on_tick reached")
            
        return True  # Returning True keeps the GLib timeout active

    def on_screen_state_changed(self, active):
        """
        Callback for D-Bus ScreenSaver signal. 'active' is False when unlocked.
        """
        self.is_screen_locked = bool(active)

        if self.is_screen_locked:
            return

        # We only care when the screen transitions to unlocked (active == False)
        now = time.time()
        last = self.get_last_download_time()
        
        if (now - last) >= self.max_mod_time_after_unlock:
            self.download_and_update("Screen unlocked and self.max_mod_time_after_unlock passed")
        else:
            logging.debug("Screen unlocked, but self.max_mod_time_after_unlock has not passed yet.")


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def get_initial_unlock_state(bus: dbus.SessionBus):
    try:
        proxy = bus.get_object('org.freedesktop.ScreenSaver', '/ScreenSaver')
        iface = dbus.Interface(proxy, 'org.freedesktop.ScreenSaver')
        return bool(iface.GetActive())
    except dbus.exceptions.DBusException as e:
        logging.warning(f"Could not query initial lock state, assuming unlocked: {e}")
        return False

def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="Robust Video Downloader Daemon")
    parser.add_argument('--url', required=True, help="URL of the MP4 video to download")
    parser.add_argument('--symlink', required=True, help="Path where the symlink should be created")
    parser.add_argument('--max-mod-time-after-unlock-seconds', required=False, help="The maximum modifcation time after a screen unlock" , type=int)
    parser.add_argument('--max-mod-time-on-tick-seconds', required=False, help="The maximum modifcation time of the video file", type=int)
    args = parser.parse_args()

    max_mod_time_after_unlock_seconds = args.max_mod_time_after_unlock_seconds
    max_mod_time_on_tick_seconds = args.max_mod_time_on_tick_seconds
    if max_mod_time_after_unlock_seconds is not None and max_mod_time_after_unlock_seconds <= 0:
        raise ValueError("--max-mod-time-after-unlock-seconds must be a positiv integer")
    if max_mod_time_on_tick_seconds is not None and max_mod_time_on_tick_seconds <= 0:
        raise ValueError("--max-mod-time-on-tick-seconds must be a positiv integer")


    # Initialize the D-Bus main loop integration
    DBusGMainLoop(set_as_default=True)
    session_bus = dbus.SessionBus()

    initial_unlock_state = get_initial_unlock_state(session_bus)
    
    manager = VideoManager(args.url, args.symlink,  max_mod_time_on_tick_seconds or DEFAULT_MAX_MOD_TIME_ON_TICK, max_mod_time_after_unlock_seconds or DEFAULT_MAX_MOD_TIME_AFTER_UNLOCK, initial_unlock_state)

    try:
        # KDE (and most Linux desktops) use the freedesktop ScreenSaver interface
        session_bus.add_signal_receiver(
            manager.on_screen_state_changed,
            dbus_interface="org.freedesktop.ScreenSaver",
            signal_name="ActiveChanged"
        )
        logging.info("Successfully connected to D-Bus ScreenSaver signals.")
    except dbus.exceptions.DBusException as e:
        logging.error(f"Failed to connect to D-Bus: {e}")
        logging.warning("Unlock detection will not work. Falling back to timer-only mode.")

    # Set up the periodic check timer
    GLib.timeout_add_seconds(CHECK_TICK_RATE_SECONDS, manager.on_timer_tick)

    # Run the main event loop
    loop = GLib.MainLoop()
    logging.info(f"Starting daemon. Monitoring {args.url}")
    logging.info(f"Target symlink: {args.symlink}")
    
    try:
        # Perform an initial check on startup
        manager.on_timer_tick()
        loop.run()
    except KeyboardInterrupt:
        logging.info("Shutting down gracefully by user request.")
        loop.quit()


if __name__ == "__main__":
    main()