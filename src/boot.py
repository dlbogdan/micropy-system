import uasyncio as asyncio
import machine
import uos

from lib.coresys.manager_system import SystemManager
from lib.coresys.manager_firmware import FirmwareUpdater
from lib.coresys.manager_config import ConfigManager
import lib.coresys.logger as logger
from lib.coresys.manager_wifi import NetworkManager,WiFiManager

logger.initialize(debug_level=3)
sys_config = ConfigManager("/system-config.json")
device_model = sys_config.get("DEVICE", "MODEL", "generic")
device_name = sys_config.get("DEVICE", "NAME", "micropython-device")
wifi_ssid = sys_config.get("WIFI", "SSID", None)
wifi_password = sys_config.get("WIFI", "PASS", None)
network_timeout_ms = sys_config.get("FIRMWARE", "NETWORK_TIMEOUT_MS", 60000)
wifi= WiFiManager(ssid=wifi_ssid, password=wifi_password,hostname=device_name)
system = SystemManager(
    device_name=device_name,
    network_manager=wifi)


def create_firmware_updater():
    """Create and initialize firmware updater based on configuration"""
    try:
        # Extract all firmware config values
        core_system_files = sys_config.get("FIRMWARE", "CORE_SYSTEM_FILES", [])
        direct_base_url = sys_config.get("FIRMWARE", "DIRECT_BASE_URL", None)
        github_repo = sys_config.get("FIRMWARE", "GITHUB_REPO", None)
        github_token = sys_config.get("FIRMWARE", "GITHUB_TOKEN", "")
        chunk_size = sys_config.get("FIRMWARE", "CHUNK_SIZE", 2048)
        max_redirects = sys_config.get("FIRMWARE", "MAX_REDIRECTS", 10)
        update_on_boot = sys_config.get("FIRMWARE", "UPDATE_ON_BOOT", True)
        max_failure_attempts = sys_config.get("FIRMWARE", "MAX_FAILURE_ATTEMPTS", 3)


        # Define the boot progress callback function for the boot process
        def boot_progress_callback(stage, progress_percent, message, error):
            logger.info(f"Progress_CB: [{stage.upper()}] {progress_percent}% - {message}", log_to_file=True)
            if error:
                logger.error(f"Progress_CB: Error in {stage}: {error}", log_to_file=True)
        
        # Create updater with all injected values (singleton handles existing instance automatically)
        updater = FirmwareUpdater(
            device_model=device_model,
            github_repo=github_repo,
            github_token=github_token,
            chunk_size=chunk_size,
            max_redirects=max_redirects,
            direct_base_url=direct_base_url,
            core_system_files=core_system_files,
            update_on_boot=update_on_boot,
            max_failure_attempts=max_failure_attempts,
            progress_callback=boot_progress_callback
        )
        
        if direct_base_url:
            logger.info(f"Boot: Firmware updater initialized with direct base URL: {direct_base_url}")
        elif github_repo:
            logger.info(f"Boot: Firmware updater initialized with GitHub repo: {github_repo}")
        else:
            logger.info("Boot: Firmware updater not initialized (no configuration for update source)")
            return None
            
        return updater
        
    except ValueError as ve:
        logger.info(f"Boot: Firmware updater not initialized (config error): {ve}")
    
    return None

async def perform_firmware_update():
    """
    Main update check routine - simplified pseudocode-like flow
    All flag management is handled automatically by FirmwareUpdater
    """
    logger.info("Boot: Firmware Update Check.", log_to_file=True)

    logger.info("Boot: Starting firmware updater...", log_to_file=True)
    updater = create_firmware_updater()
    if not updater:
        logger.error("Boot: Firmware updater not available.", log_to_file=True)
        return

    logger.info("Boot: Checking for previously interrupted update...", log_to_file=True)
    if updater.was_interrupted_during_applying():
        success = await updater.restore_from_backup()
        if not success:
            logger.error(f"Boot: Failed to restore from backup: {updater.error}", log_to_file=True)
        return

    logger.info("Boot: Checking if update should be attempted...", log_to_file=True)
    should_attempt, message = updater.should_attempt_update()
    if not should_attempt:
        logger.info(f"Boot: {message}", log_to_file=True)
        return

    logger.info("Boot: Setting up WiFi connection", log_to_file=True)
    await system.setup_network()
    logger.info("Boot: Checking for updates...", log_to_file=True)
    is_available, version_str, release_info = await updater.check_update()
    if updater.error and not version_str:
        return  # Check failed completely

    update_applied = False

    if is_available:
        logger.info("Boot: Downloading and applying update...", log_to_file=True)
        update_downloaded = await updater.download_update(release_info)
        if not update_downloaded:
            logger.error(f"Boot: Download failed: {updater.error}", log_to_file=True)
            return

        update_applied = await updater.apply_update()
        if not update_applied:
            logger.error(f"Boot: Apply failed: {updater.error}", log_to_file=True)
            return

    else:
        logger.info(f"Boot: Firmware is up-to-date (version: {version_str})", log_to_file=True)

    if update_applied:
        logger.info("Boot: Rebooting after successful update...", log_to_file=True)
        await asyncio.sleep_ms(250)
        machine.reset()

# Run the update check on boot (main execution part)
if __name__ == "__main__":
    try:
        asyncio.run(perform_firmware_update())
    except KeyboardInterrupt:
        logger.info("Boot: Process interrupted by user.", log_to_file=True)
    except Exception as e:
        logger.error(f"Boot: Unhandled exception in boot sequence: {e}", log_to_file=True)
    finally:
        logger.info("Boot: Main execution of boot.py finished.", log_to_file=True)
        asyncio.run(system.shutdown())