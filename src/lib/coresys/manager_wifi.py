import asyncio
import time
import network
import lib.coresys.logger as logger

# logger = Logger()
class NetworkManager:
    """Handles non-blocking network connection and status monitoring."""
    STATE_DISCONNECTED = 0
    STATE_CONNECTING = 1
    STATE_CONNECTED = 2
    STATE_FAILED = 3
    
    def __init__(self, hostname,retry_interval_ms=10000):
        self.hostname = hostname
        self.retry_interval_ms = retry_interval_ms
        self._wlan = None
        self._connection_state = self.STATE_DISCONNECTED
        self._last_error = None
        self._ip_address = None


    def get_state(self):
        """Returns a string representation of the current status."""
        if self._connection_state == self.STATE_CONNECTED: return "Connected"
        if self._connection_state == self.STATE_CONNECTING: return "Connecting"
        if self._connection_state == self.STATE_DISCONNECTED: return "Disconnected"
        if self._connection_state == self.STATE_FAILED: return "Error"
        return "Unknown"

    def get_error(self):
        """Returns the last error message if there was one."""
        return self._last_error

    def up(self):
        """Connect to the network."""
        """implementation varies"""
        logger.fatal("NOTIMPL",f"NetworkManager: EMPTY up() function, please implement your own up() function. ")
        raise NotImplementedError("Subclasses must implement up()")

    def down(self):
        """Disconnect from the network."""
        """implementation varies"""
        logger.fatal("NOTIMPL",f"NetworkManager: EMPTY down() function, please implement your own down() function. ")
        raise NotImplementedError("Subclasses must implement down()")

    def get_ip(self):
        """Returns the current IP address if connected, otherwise None."""
        return self._ip_address if self.is_up() else None

    def is_up(self)-> bool:
        """Check if the network is up  """
        return self._connection_state == self.STATE_CONNECTED

    def is_down(self)-> bool:
        """Check if the network is down  """
        return self._connection_state != self.STATE_CONNECTED

    async def refresh(self):
        """Should be called periodically in the main loop to manage connection."""
        """implementation varies"""
        logger.fatal("NOTIMPL",f"NetworkManager: EMPTY refresh() function, please implement your own refresh() function. ")
        raise NotImplementedError("Subclasses must implement down()")


    async def wait_until_up(self, timeout_ms=60000):
        """Wait for the network to come up with timeout."""
        start_time = time.ticks_ms()
        if not self.up():
            logger.error("NetworkManager: Connection failed")
            return False
        while self.is_down():
            await self.refresh()
            if time.ticks_diff(time.ticks_ms(), start_time) > timeout_ms:
                logger.warning("NetworkManager: Connection timed out")
                self._connection_state = self.STATE_FAILED
                self._last_error = "Connection timeout"
                return False
            await asyncio.sleep_ms(250)
        self._connection_state = self.STATE_CONNECTED
        self._last_error = None
        return True

# --- WiFi Management ---
# class WiFiManager: ... (NO CHANGES NEEDED, connection check is non-blocking) ...
class WiFiManager( NetworkManager):
    """Handles non-blocking Wi-Fi connection and status monitoring."""

    def __init__(self, ssid, password, hostname, retry_interval_ms=10000):
        super().__init__(hostname, retry_interval_ms)
        self.ssid = ssid
        self.password = password
        self.retry_interval_ms = retry_interval_ms
        self._last_attempt_time = 0

        try:
            self._wlan = network.WLAN(network.STA_IF)
            self._wlan.active(False) # Start inactive
            network.hostname(self.hostname)
            logger.info("WiFiManager: WLAN interface initialized.")
            # Set an initial status based on whether credentials are provided
            if self.ssid:
                 self._connection_state = self.STATE_DISCONNECTED
                 logger.info("WiFiManager: Ready to connect.")
            else:
                 self._connection_state = self.STATE_DISCONNECTED # Or maybe a dedicated NO_CREDS status?
                 logger.error("WiFiManager: No SSID configured, will remain disconnected.")

        except Exception as e:
            logger.fatal("WiFiManager Error: Failed to initialize WLAN interface", e, reset_machine=True)
            self._connection_state = self.STATE_FAILED

    def up(self):
        """Connect to the Wi-Fi network."""
        if self._connection_state == self.STATE_FAILED or not self.ssid:
            logger.error("WiFiManager: WLAN interface not initialized.")
            return False
        if self._connection_state != self.STATE_CONNECTED:
                try:
                    self._wlan.active(True)
                    self._wlan.connect(self.ssid, self.password)
                    self._connection_state = self.STATE_CONNECTING
                    return True
                except Exception as e:
                    logger.error(f"WiFiManager Error: Exception during connect initiation: {e}")
                    self._connection_state = self.STATE_DISCONNECTED  # Stay disconnected, retry later
                    self._wlan.active(False)  # Ensure it's off if connect failed badly
                    return False
        else:
            return True # Already connected, no need to check again

    def _can_attempt_connect(self):
        """Checks if enough time has passed since the last connection attempt."""
        return time.ticks_diff(time.ticks_ms(), self._last_attempt_time) > self.retry_interval_ms

    async def refresh(self):
        """Should be called periodically in the main loop to manage connection."""
        if self._connection_state == self.STATE_FAILED or not self.ssid:
            return # Cannot proceed if WLAN failed or no SSID

        # Check the current physical connection status
        is_connected = self._wlan.isconnected()

        if self._connection_state == self.STATE_CONNECTED:
            if not is_connected:
                logger.error("WiFiManager: Connection lost.")
                self._connection_state = self.STATE_DISCONNECTED
                self._ip_address = None
                self._wlan.active(False) # Deactivate to ensure clean reconnect
                self._last_attempt_time = time.ticks_ms() # Start retry timer
            # else: still connected, no need to log

        elif self._connection_state == self.STATE_CONNECTING:
            if is_connected:
                self._ip_address = self._wlan.ifconfig()[0]
                logger.info(f"WiFiManager: Connected to {self.ssid} ({self._ip_address})")
                self._connection_state = self.STATE_CONNECTED
            elif self._wlan.status() < 0 or self._wlan.status() >= 3: # Error codes like WRONG_PASSWORD, NO_AP_FOUND, CONN_FAIL
                logger.error(f"WiFiManager: Connection failed. Status code: {self._wlan.status()}.")
                self._connection_state = self.STATE_DISCONNECTED
                self._wlan.active(False) # Deactivate
                self._last_attempt_time = time.ticks_ms() # Start retry timer
            # else: still connecting, no need to log

        elif self._connection_state == self.STATE_DISCONNECTED:
            if self._can_attempt_connect():
                self._last_attempt_time = time.ticks_ms()
                self.up()


    def down(self):
        """Disconnects the Wi-Fi connection."""
        if self._wlan:
            self._wlan.disconnect()
            self._wlan.active(False)

    def get_signal_strength(self):
        """Get the current signal strength (RSSI) if connected.

        Returns:
            int: Signal strength in dBm or None if not available
        """
        if not self.is_up() or not self._wlan:
            return None

        try:
            # Try the standard MicroPython approach first
            rssi = self._wlan.status('rssi')
            return rssi
        except (ValueError, TypeError):
            pass

        return None

    def get_ssid(self):
        """Get the current connected SSID.

        Returns:
            str: The SSID of the connected network or None if not connected
        """
        if self.is_up():
            return self.ssid
        return None
