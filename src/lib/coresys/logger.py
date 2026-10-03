"""
Logging module for embedded systems with minimal flash writes.
This module provides global logging functionality.
"""

import json
import time
from machine import reset

# Module-level configuration and state
_debug_level = 0
_last_error = None
_error_history = []
_error_timestamps = []
_max_error_history = 10
_error_rate_limit = 3
_error_rate_limiter_reached = False
_message_server = None

# Constants
ERROR_FILE = "lasterror.json"
LOG_FILE = "log.txt"

def initialize(debug_level=0):
    """Initialize the logger with a specific debug level."""
    global _debug_level
    _debug_level = debug_level
    print(f"Logger initialized with debug level {_debug_level}")

def set_message_server(server_instance):
    """Set the MessageServer instance for network logging."""
    global _message_server
    _message_server = server_instance
    if _message_server:
        print("Logger: MessageServer instance linked.")

def get_level():
    """Get the current debug level."""
    return _debug_level

def fatal(error_type, message, reset_machine=True):
    """Log a fatal error to flash. Only writes if different from last error."""
    global _last_error
    
    # Network send first (if configured)
    if _message_server:
        _message_server.send(f"FATAL: {error_type} - {message}")
    
    new_error = {
        "timestamp": time.time(),
        "type": error_type,
        "message": message,
    }

    # Only write if error is different from last one
    if _last_error != new_error:
        try:
            with open(ERROR_FILE, 'w') as f:
                json.dump(new_error, f)
            _last_error = new_error
        except Exception as e:
            _log_to_file("ERROR", f"Failed to write error log: {e}")

    # Log to log.txt
    _log_to_file("ERROR", f"FATAL: {error_type} - {message}")
    if reset_machine:
        reset()

def error(message, log_to_file=True):
    """Log a non-fatal error to log.txt and track it for rate limiting."""
    print(f"ERROR: {message}")
    if _message_server:
        _message_server.send(f"ERROR: {message}")
    if log_to_file:
        _log_to_file("ERROR", message)
    _track_error_rate()
    _add_to_history("ERROR", message)

def warning(message, log_to_file=False):
    """Log a warning message to the history."""
    if _debug_level >= 1:
        print(f"WARNING: {message}")
        if _message_server:
            _message_server.send(f"WARNING: {message}")
    if log_to_file:
        _log_to_file("WARNING", message)
    _add_to_history("WARNING", message)

def info(message, log_to_file=False):
    """Log an informational message."""
    if _debug_level >= 2:
        print(f"INFO: {message}")
        if _message_server:
            _message_server.send(f"INFO: {message}")
    if log_to_file:
        _log_to_file("INFO", message)

def debug(message, log_to_file=False):
    """Log a debug message."""
    if _debug_level >= 3:
        print(f"DEBUG: {message}")
        if _message_server:
            _message_server.send(f"DEBUG: {message}")
    if log_to_file:
        _log_to_file("DEBUG", message)

def trace(message, log_to_file=False):
    """Log a trace message."""
    if _debug_level >= 4:
        print(f"TRACE: {message}")
        if _message_server:
            _message_server.send(f"TRACE: {message}")
    if log_to_file:
        _log_to_file("TRACE", message)

def get_last_error():
    """Return the last fatal error if it exists."""
    try:
        with open(ERROR_FILE, 'r') as f:
            return json.load(f)
    except:
        return None

def get_current_log():
    """Return the current log as a string."""
    try:
        with open(LOG_FILE, 'r') as f:
            return f.read()
    except:
        return ""

def get_error_warning_history():
    """Return the last error and warning history."""
    return _error_history

def clear_error_log():
    """Clear the error log file."""
    global _last_error
    try:
        with open(ERROR_FILE, 'w') as f:
            f.write("")
        _last_error = None
    except Exception as e:
        _log_to_file("ERROR", f"Failed to clear error log: {e}")

def reset_error_rate_limiter():
    """Reset the error rate limiter flag."""
    global _error_rate_limiter_reached, _error_timestamps
    _error_rate_limiter_reached = False
    _error_timestamps = []

def is_error_rate_limited():
    """Check if error rate limiter is active."""
    return _error_rate_limiter_reached

# Private helper functions
def _log_to_file(level, message):
    """Log a message to the log file."""
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(f"{time.time()} - {level}: {message}\n")
    except Exception as e:
        print(f"Failed to write to log file: {e}")

def _track_error_rate():
    """Track the rate of errors and set the rate limiter flag if exceeded."""
    global _error_rate_limiter_reached
    current_time = time.time()
    _error_timestamps.append(current_time)

    # Remove timestamps older than 1 minute
    _error_timestamps[:] = [t for t in _error_timestamps if current_time - t <= 60]

    # Check if rate limit is exceeded
    if len(_error_timestamps) > _error_rate_limit:
        _error_rate_limiter_reached = True
        _log_to_file("ERROR", f"Error rate limiter triggered: {len(_error_timestamps)} errors in the last minute")

def _add_to_history(level, message):
    """Add an error or warning to the history, keeping only the last entries."""
    _error_history.append({"level": level, "message": message, "timestamp": time.time()})
    if len(_error_history) > _max_error_history:
        _error_history.pop(0)

