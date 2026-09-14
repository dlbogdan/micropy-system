import machine
import utime
import uasyncio as asyncio
import gc
from lib.coresys.manager_system import SystemManager
# from coresys.sysconfig import sys_config
from lib.coresys.manager_config import ConfigManager
from lib.coresys.manager_wifi import WiFiManager

sys_config = ConfigManager("/system-config.json")

# Onboard LED (typically GP25 for Pico, or 'LED' for Pico W)
led_pin = machine.Pin('LED', machine.Pin.OUT)


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
