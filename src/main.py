import machine
import utime
import uasyncio as asyncio
import gc
from lib.coresys.manager_system import SystemManager
from lib.coresys.manager_firmware import FirmwareUpdater
# from coresys.sysconfig import sys_config
from lib.coresys.manager_config import ConfigManager
from lib.coresys.manager_wifi import WiFiManager

sys_config = ConfigManager("/system-config.json")
device_model = sys_config.get("DEVICE", "MODEL", "generic")
core_system_files = sys_config.get("FIRMWARE", "CORE_SYSTEM_FILES", [])
direct_base_url = sys_config.get("FIRMWARE", "DIRECT_BASE_URL", None)
github_repo = sys_config.get("FIRMWARE", "GITHUB_REPO", None)
github_token = sys_config.get("FIRMWARE", "GITHUB_TOKEN", "")
chunk_size = sys_config.get("FIRMWARE", "CHUNK_SIZE", 2048)
max_redirects = sys_config.get("FIRMWARE", "MAX_REDIRECTS", 10)
update_on_boot = sys_config.get("FIRMWARE", "UPDATE_ON_BOOT", True)
max_failure_attempts = sys_config.get("FIRMWARE", "MAX_FAILURE_ATTEMPTS", 3)

# Onboard LED (typically GP25 for Pico, or 'LED' for Pico W)
led_pin = machine.Pin('LED', machine.Pin.OUT)


def create_firmware_updater():
    """Create and initialize firmware updater based on configuration"""
    try:
        # Use global configuration instance
        
        # Extract all firmware config values
        
        
        # Define progress callback for main process
        def main_progress_callback(stage, progress_percent, message, error):
            print(f"Main: [{stage.upper()}] {progress_percent}% - {message}")
            if error:
                print(f"Main: Error in {stage}: {error}")
        
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
            progress_callback=main_progress_callback
        )
        
        if direct_base_url:
            print(f"Main: Firmware updater initialized with direct base URL: {direct_base_url}")
        elif github_repo:
            print(f"Main: Firmware updater initialized with GitHub repo: {github_repo}")
        else:
            print("Main: Firmware updater not initialized (no configuration for update source)")
            return None
            
        return updater
        
    except ValueError as e:
        print(f"Main: Firmware updater not initialized (config error): {e}")
    
    return None

async def main():
    try:
        # Initialize the system manager as a singleton
        print("Main: Initializing system components...")
        print(f"free memory: {gc.mem_free()}")

        # Use global configuration instance
        
        # Extract config values for injection
        device_name = sys_config.get("DEVICE", "NAME", "micropython-device")
        wifi_ssid = sys_config.get("WIFI", "SSID", None)
        wifi_password = sys_config.get("WIFI", "PASS", None)
        wifi= WiFiManager(ssid=wifi_ssid, password=wifi_password,hostname=device_name)

        # Initialize the system manager with injected values
        system = SystemManager(
            device_name=device_name,
            network_manager=wifi)

        # Bring up WiFi and wait for connection
        print("Main: Starting WiFi connection...")
        await system.setup_network()

        # Wait for connection with timeout

            # Check for firmware updates if network is connected
        print("Main: Initializing firmware updater...")
        firmware_updater = create_firmware_updater()

        if firmware_updater:
            print("Main: Checking for firmware updates...")
            update_available, new_version, release_info = await firmware_updater.check_update()

            if firmware_updater.error:
                print(f"Main: Update check failed: {firmware_updater.error}")
            elif update_available:
                print(f"Main: Firmware update available: {new_version}")
            else:
                print(f"Main: Firmware is up to date (version: {new_version})")
        else:
            print("Main: Firmware updater not available - check configuration")
        
        # Main application loop
        print("Main: Entering main application loop")
        print(f"free memory: {gc.mem_free()}")
        while True:
            # No need to call system.update() anymore, WiFi is managed in background
            
            # Toggle LED as a heartbeat
            led_pin.toggle()
            
            # Wait a bit
            await asyncio.sleep(1)
    except Exception as e:
    # Handle any exceptions here
        print(f"Main: Fatal error: {e}")
        machine.reset()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Fatal error: {e}")
        machine.reset() 