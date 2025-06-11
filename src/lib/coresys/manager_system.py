import time
import gc

import lib.coresys.logger as logger
from lib.coresys.manager_wifi import WiFiManager, NetworkManager
from lib.coresys.manager_tasks import TaskManager
import uasyncio as asyncio



class SystemManager:
    """Master system manager that coordinates all subsystems (Singleton)."""
    _instance = None
    _initialized = False


    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, device_name="Unnamed Device",network_manager =None):
        self._device_name = device_name
        self._task_manager = TaskManager()
        self._initialized = True
        self._network_manager = network_manager

    async def shutdown(self):
        """Destruct everything"""
        await self.cleanup()
        # asyncio.new_event_loop()

    async def setup_network(self):
        """Create WiFi service instance.

        Returns:
            WiFiManager: Instance or None if credentials missing
        """
        try:
            # self._network_manager = WiFiManager(ssid, password, self._device_name)
            logger.info(f"SystemManager: Network Up")
            self._network_manager.up()
            logger.info(f"SystemManager: Waiting for network")
            await self._network_manager.wait_until_up()
            logger.info(f"SystemManager: Network is up, IP Addr:{self._network_manager.get_ip()}")
            logger.info(f"SystemManager: Network keepalive task starting")
            self._task_manager.create_periodic_task(self._network_manager.refresh,interval_ms=500)
            return True
        except Exception:
            return False


    def init(self):
        """Initialize the system.

        Returns:
            SystemManager: Self for chaining
        """
        if self._initialized:
            return self

        logger.info(f"SystemManager: Initializing '{self._device_name}'")

        # Validate configuration
        self._validate_config()

        # Mark as initialized
        self._initialized = True
        # logger.info(f"SystemManager: Initialized with services: {', '.join(self._services.keys())}")
        return self

    # TODO: make this more useful
    def _validate_config(self):
        """Validate the required configuration early."""
        issues = []
        # if not self._device_name:
        #     issues.append("Device name not set")
        # if self._wifi_ssid and not self._wifi_password:
        #     issues.append("WiFi SSID set but password missing")
        # if issues:
        #     logger.warning(f"SystemManager: Configuration issues: {', '.join(issues)}")
        return len(issues) == 0


    def get_system_status(self):
        """Get comprehensive system status including all subsystems.

        Returns:
            dict: Dictionary containing system status information
        """
        # Collect memory information
        gc.collect()
        mem_free = gc.mem_free()
        mem_alloc = gc.mem_alloc() if hasattr(gc, 'mem_alloc') else None

        status = {
            'device': {
                'name': self._device_name,
                'initialized': self._initialized,
                'uptime': time.time() - self._init_time if hasattr(self, '_init_time') else None,
            },
            'memory': {
                'free': mem_free,
                'allocated': mem_alloc,
                'total': (mem_free + mem_alloc) if mem_alloc is not None else None
            },
            # 'services': self.get_service_status(),
            'tasks': {
                'count': len(self._task_manager.get_all_tasks()) if self._task_manager else 0
            }
        }

        return status

    def get_tasks_info(self):
        """Get detailed information about all tasks.
        Returns:
            list: List of dictionaries with task information
        """
        result = []
        for task_id in self._task_manager.get_all_tasks():
            task_info = self._task_manager.get_task_info(task_id)
            if task_info:
                # Copy the task info and add the ID
                task_data = dict(task_info)
                task_data['id'] = task_id
                result.append(task_data)
        return result

    async def cleanup(self):
        """Clean up all services and prepare for shutdown."""
        logger.info("SystemManager: Cleaning up all services")

        # First, stop all tasks
        await self._task_manager.cancel_all_tasks()
        self.network.down()
        self._initialized = False
        # self._connection_state = self.CONN_DISCONNECTED

        return True

    def generate_status_report(self):
        """Generate a comprehensive status report suitable for diagnostics.

        Returns:
            dict: Status report with system info, services, tasks, and network status
        """
        report = {
            'timestamp': time.time(),
            'system': self.get_system_status(),
            'tasks': self.get_tasks_info()
        }

        # Add the version if available
        try:
            with open('/version.txt', 'r') as f:
                report['version'] = f.read().strip()
        except OSError:
            report['version'] = int('nan')

        return report
        
    # @property
    # def wifi(self):
    #     """Get the WiFi manager instance."""
    #     return self._services.get('wifi')

    @property
    def device_name(self):
        """Access the device name."""
        return self._device_name

    @property
    def task_manager(self):
        """Access the task manager instance."""
        return self._task_manager

    @property
    def network(self):
        """Access the network manager instance."""
        return self._network_manager