import uos
import time
import json
import lib.coresys.logger as logger
# Import Any for type hinting
from typing import Any, Callable, Dict, List

# logger = Logger()

# --- Configuration Management ---
class ConfigManager:
    """Handles reading/writing config using JSON format."""
    
    def __init__(self, filename_config: str):
        logger.debug(f"Initializing ConfigManager for file: {filename_config}")
        self.filename_config = filename_config
        self.config = {}  # Holds the parsed config (dict of dicts with types)
        # Observer pattern: Store listeners keyed by "section.key"
        self._listeners: Dict[str, List[Callable[[Any], None]]] = {}
        self._load_config()

    def _load_config(self):
        """Loads config from JSON file."""
        try:
            with open(self.filename_config, 'r') as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    self.config = loaded_data
                    logger.info(f"Loaded config from {self.filename_config}")
                else:
                    logger.error(f"Invalid config format in {self.filename_config} (not a dictionary). Using empty config.")
                    self.config = {}
        except (OSError, ValueError) as e:
            # OSError -> File not found or read error
            # ValueError -> Invalid JSON
            logger.warning(f"Could not load config from {self.filename_config} ({e}). Using empty config. Defaults will be created.")
            self.config = {}
        except Exception as e:
             logger.error(f"Unexpected error loading config {self.filename_config}: {e}")
             self.config = {}

    def save_config(self):
        """Save the current configuration to the JSON config file."""
        try:
            with open(self.filename_config, 'w') as f:
                # Use positional arguments only for MicroPython compatibility
                json.dump(self.config, f) # No keyword args
            logger.info(f"Config successfully saved to {self.filename_config}") 
            return True
        except Exception as e:
            logger.error(f"Error saving config to {self.filename_config}: {e}")
            return False

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Gets value, setting default (and saving) if missing. Preserves type from load/default."""    
        section_dict = self.config.get(section)
        
        if isinstance(section_dict, dict) and key in section_dict:
            return section_dict[key] # Return existing value (already typed)
        else:
            if default is not None:
                # Section or key missing, use default
                logger.info(f"Config key '{section}.{key}' not found. Setting default: {repr(default)}")
                # Set the default value (with its original type) and save
                self.set(section, key, default) # set_value handles save and notification
                return default
            else:
                logger.error(f"Config key '{section}.{key}' not found and no default provided.")
                raise ValueError(f"Config key '{section}.{key}' not found and no default provided. Impossible to proceed.")

    def set(self, section: str, key: str, value: Any):
        """Sets the value (preserving type), saves config, and notifies listeners if changed."""
        # Ensure section exists
        if section not in self.config or not isinstance(self.config[section], dict):
            self.config[section] = {}
            
        # Check if value actually changed
        current_value = self.config.get(section, {}).get(key, None)
        value_changed = (key not in self.config.get(section, {})) or (current_value != value)

        if value_changed:
            self.config[section][key] = value # Assign value directly (preserves type)
            logger.debug(f"Config set: {section}.{key} = {value}")
            
            # Attempt to save the configuration
            if not self.save_config():
                 logger.error(f"Failed to save config after setting {section}.{key}")
                 # Decide if you want to proceed with notification even if save failed
                 # For now, we proceed.
            
            # Notify listeners
            self._notify_listeners(section, key, value)

        # else: logger.debug(f"set_value: Value for {section}.{key} unchanged.")

    def _notify_listeners(self, section: str, key: str, new_value: Any):
        """Notifies registered listeners about a configuration change."""
        key_path = f"{section}.{key}"
        if key_path in self._listeners:
            # logger.debug(f"Notifying listeners for {key_path}")
            for callback in self._listeners[key_path]:
                try:
                    callback(new_value)
                except Exception as e:
                    logger.error(f"Error calling listener for {key_path}: {e}")

    def subscribe(self, key_path: str, callback: Callable[[Any], None]):
        """Registers a callback function to be notified of changes to a specific config key.

        Args:
            key_path (str): The configuration key path (e.g., "SECTION.KEY").
            callback (Callable[[Any], None]): The function to call when the value changes.
                                                It will receive the new value as an argument.
        """
        if key_path not in self._listeners:
            self._listeners[key_path] = []
        if callback not in self._listeners[key_path]:
            self._listeners[key_path].append(callback)
            # logger.debug(f"Subscribed listener to {key_path}")
        # else: logger.debug(f"Listener already subscribed to {key_path}")

    def unsubscribe(self, key_path: str, callback: Callable[[Any], None]):
        """Unregisters a callback function for a specific config key.

        Args:
            key_path (str): The configuration key path (e.g., "SECTION.KEY").
            callback (Callable[[Any], None]): The callback function to remove.
        """
        if key_path in self._listeners and callback in self._listeners[key_path]:
            self._listeners[key_path].remove(callback)
            # If no listeners remain for this key, remove the key entry
            if not self._listeners[key_path]:
                del self._listeners[key_path]
            # logger.debug(f"Unsubscribed listener from {key_path}")
        # else: logger.debug(f"Listener not found for unsubscribe on {key_path}")
