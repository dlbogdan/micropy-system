import uasyncio as asyncio
import time
import lib.coresys.logger as logger

class TaskEvent:
    """Event data for task lifecycle notifications."""
    
    # Event types
    TASK_STARTED = 0
    TASK_STOPPED = 1
    TASK_FAILED = 2
    TASK_COMPLETED = 3
    
    def __init__(self, task_id, event_type, task_type, error=None):
        self.task_id = task_id        # Unique identifier for the task
        self.event_type = event_type  # Type of event (started, stopped, etc.)
        self.task_type = task_type    # Type of task (one-shot or periodic)
        self.error = error            # Error if a task failed
        self.timestamp = time.time()  # When the event occurred

class TaskManager:
    """Manages async tasks with lifecycle events and periodic updates."""
    
    # Task types
    TASK_ONESHOT = 0    # Run once and complete
    TASK_PERIODIC = 1   # Run in a loop with periodic updates
    
    def __init__(self):
        self._tasks = {}                # task_id -> task object
        self._task_info = {}            # task_id -> task metadata
        self._listeners = []            # Event listeners
        self._next_task_id = 1          # For generating unique task IDs
        self.add_listener(self._on_task_event)

    def create_task(self, coro, task_id=None, description=""):
        """Create a one-shot task for a self-sustained coroutine.
        
        Args:
            coro: The coroutine to run
            task_id: Optional explicit task ID, or auto-generated if None
            description: Optional description of the task
            
        Returns:
            task_id: The ID of the created task
        """
        if task_id is None:
            task_id = f"oneshot_{self._next_task_id}"
            self._next_task_id += 1
            
        # Create a task wrapper that handles completion and errors
        async def task_wrapper():
            try:
                # Notify task started
                self._notify_event(TaskEvent(
                    task_id, 
                    TaskEvent.TASK_STARTED, 
                    TaskManager.TASK_ONESHOT
                ))
                
                # Run the actual coroutine
                result = await coro
                
                # Notify a task completed
                self._notify_event(TaskEvent(
                    task_id, 
                    TaskEvent.TASK_COMPLETED, 
                    TaskManager.TASK_ONESHOT
                ))
                
                # Clean up
                if task_id in self._tasks:
                    del self._tasks[task_id]
                if task_id in self._task_info:
                    del self._task_info[task_id]
                    
                return result
                
            except asyncio.CancelledError:
                # Task was cancelled - notify stopped
                self._notify_event(TaskEvent(
                    task_id, 
                    TaskEvent.TASK_STOPPED, 
                    TaskManager.TASK_ONESHOT
                ))
                raise
                
            except Exception as e:
                # Task failed with error
                self._notify_event(TaskEvent(
                    task_id, 
                    TaskEvent.TASK_FAILED, 
                    TaskManager.TASK_ONESHOT,
                    error=e
                ))
                
                # Clean up
                if task_id in self._tasks:
                    del self._tasks[task_id]
                if task_id in self._task_info:
                    del self._task_info[task_id]
                    
                raise  # Re-raise the exception
        
        # Create the actual task
        task = asyncio.create_task(task_wrapper())
        
        # Store task and metadata
        self._tasks[task_id] = task
        self._task_info[task_id] = {
            'type': TaskManager.TASK_ONESHOT,
            'description': description,
            'start_time': time.time(),
            'running': True
        }
        
        return task_id

    @staticmethod
    def func_is_coroutine(func):
        """Check if a function is a coroutine.

        Args:
            func: The function to check

        Returns:
            bool: True if the function is a coroutine, False otherwise
        """
        # Check if it has __await__ attribute (works in most Pythons)
       
            # CO_ITERABLE_COROUTINE = 0x0080, but we check for async def functions
        if hasattr(func, '__code__'):
            return bool(func.__code__.co_flags & (0x0080 | 0x0200))
        return False
    

    def create_periodic_task(self, update_func, interval_ms=500, task_id=None, description="", is_coroutine=None):
        """Create a task that calls an update function periodically.
        
        Args:
            update_func: Function to call periodically (can be async or not)
            interval_ms: Milliseconds between calls
            task_id: Optional explicit task ID, or auto-generated if None
            description: Optional description of the task
            is_coroutine: Explicitly specify if the function is a coroutine, 
                         or None to try to detect (may not work in all MicroPython versions)
            
        Returns:
            task_id: The ID of the created task
        """
        if task_id is None:
            task_id = f"periodic_{self._next_task_id}"
            self._next_task_id += 1
            
        # Is the update function a coroutine?
        # First try the explicit parameter, then use basic detection if None
        if is_coroutine is None:
            is_coroutine = self.func_is_coroutine(update_func)
        if is_coroutine:
            logger.debug(f"SystemManager: Task {task_id} is a coroutine")

        # if is_coroutine is None:
        #     # Simple detection - better compatibility with MicroPython
        #     try:
        #         # Check if it has __await__ attribute (works in most Pythons)
        #         is_coroutine = hasattr(update_func, "__await__")
        #     except Exception:
        #         # If that fails, assume it's not a coroutine
        #         is_coroutine = False
            
        # Create a periodic task wrapper
        async def periodic_wrapper():
            try:
                # Notify task started
                self._notify_event(TaskEvent(
                    task_id, 
                    TaskEvent.TASK_STARTED, 
                    TaskManager.TASK_PERIODIC
                ))
                
                # Store a flag for checking if we should continue running
                task_info = self._task_info[task_id]
                
                # Run the update function periodically
                while task_info['running']:
                    try:
                        logger.trace(f"SystemManager: Task {task_id} update")
                        # Call the update function based on its type
                        if is_coroutine:
                            await update_func()
                        else:
                            update_func()
                            
                    except Exception as e:
                        # Update function failed but we continue the loop
                        self._notify_event(TaskEvent(
                            task_id, 
                            TaskEvent.TASK_FAILED, 
                            TaskManager.TASK_PERIODIC,
                            error=e
                        ))
                        
                    # Wait for the next interval
                    await asyncio.sleep_ms(interval_ms)
                    
                # Notify task was stopped (clean exit from loop)
                self._notify_event(TaskEvent(
                    task_id, 
                    TaskEvent.TASK_STOPPED, 
                    TaskManager.TASK_PERIODIC
                ))
                
            except asyncio.CancelledError:
                # Task was cancelled - notify stopped
                self._notify_event(TaskEvent(
                    task_id, 
                    TaskEvent.TASK_STOPPED, 
                    TaskManager.TASK_PERIODIC
                ))
                raise
                
            except Exception as e:
                # Unexpected error in the task itself
                self._notify_event(TaskEvent(
                    task_id, 
                    TaskEvent.TASK_FAILED, 
                    TaskManager.TASK_PERIODIC,
                    error=e
                ))
                
                # Clean up
                if task_id in self._tasks:
                    del self._tasks[task_id]
                if task_id in self._task_info:
                    del self._task_info[task_id]
                    
                raise  # Re-raise the exception
        
        # Create the actual task
        task = asyncio.create_task(periodic_wrapper())
        
        # Store task and metadata
        self._tasks[task_id] = task
        self._task_info[task_id] = {
            'type': TaskManager.TASK_PERIODIC,
            'description': description,
            'start_time': time.time(),
            'interval_ms': interval_ms,
            'running': True
        }
        
        return task_id
        
    def ensure_periodic_task(self, task_id, update_func, interval_ms=500, description="", is_coroutine=None):
        """Ensure a periodic task is running - create it if it doesn't exist or restart it if stopped.
        
        Args:
            task_id: The task ID to check and ensure is running
            update_func: Function to call periodically (only used if creating a new task)
            interval_ms: Milliseconds between calls (only used if creating a new task)
            description: Optional description of the task (only used if creating a new task)
            is_coroutine: Whether the update_func is a coroutine (only used if creating a new task)
            
        Returns:
            task_id: The ID of the ensured task
        """
        # Check if the task exists and is running
        if task_id in self._task_info and task_id in self._tasks:
            task_info = self._task_info[task_id]
            
            # If the task exists but isn't running, restart it
            if not task_info['running'] and task_info['type'] == TaskManager.TASK_PERIODIC:
                task_info['running'] = True
                return task_id
                
            # If the task is already running, so we simply return the ID
            if task_info['running']:
                return task_id
                
        # If a task doesn't exist or isn't a periodic task, create a new one
        return self.create_periodic_task(
            update_func, 
            interval_ms=interval_ms, 
            task_id=task_id,
            description=description,
            is_coroutine=is_coroutine
        )
        
    async def stop_task(self, task_id):
        """Stop a task by its ID.
        
        For periodic tasks, this stops the loop elegantly.
        For one-shot tasks, this cancels the task.
        
        Returns:
            bool: True if a task was found and stopped, False otherwise
        """
        if task_id not in self._tasks or task_id not in self._task_info:
            return False
            
        task_info = self._task_info[task_id]
        
        if task_info['type'] == TaskManager.TASK_PERIODIC:
            # For periodic tasks, set a running flag as False to stop the loop
            task_info['running'] = False
            return True
        else:
            # For one-shot tasks, cancel the task
            task = self._tasks[task_id]
            task.cancel()
            return True
            
    def restart_task(self, task_id):
        """Restart a stopped periodic task.
        
        Returns:
            bool: True if the task was found and restarted, False otherwise
        """
        if task_id not in self._task_info:
            return False
            
        task_info = self._task_info[task_id]
        
        if task_info['type'] != TaskManager.TASK_PERIODIC:
            return False  # Can only restart periodic tasks
            
        if task_id in self._tasks and not task_info['running']:
            # Set the running flag to True to restart the loop
            task_info['running'] = True
            return True
            
        return False
        
    async def cancel_all_tasks(self):
        """Cancel all running tasks."""
        for task_id in list(self._tasks.keys()):
            await self.stop_task(task_id)
            
    def is_task_running(self, task_id):
        """Check if a task is currently running.
        
        Returns:
            bool: True if the task exists and is running, False otherwise
        """
        return (task_id in self._task_info and 
                task_id in self._tasks and 
                self._task_info[task_id]['running'])
                
    def get_task_info(self, task_id):
        """Get information about a task.
        
        Returns:
            dict: Task metadata or None if the task was not found
        """
        return self._task_info.get(task_id)
        
    def get_all_tasks(self):
        """Get a list of all task IDs.
        
        Returns:
            list: List of all task IDs
        """
        return list(self._tasks.keys())
        
    def add_listener(self, listener_func):
        """Add a listener for task events.
        
        Args:
            listener_func: Function that takes a TaskEvent parameter
            
        Returns:
            None
        """
        if listener_func not in self._listeners:
            self._listeners.append(listener_func)
            
    def remove_listener(self, listener_func):
        """Remove a task event listener.
        
        Args:
            listener_func: Previously added listener function
            
        Returns:
            bool: True if found and removed, False otherwise
        """
        if listener_func in self._listeners:
            self._listeners.remove(listener_func)
            return True
        return False
        
    def _notify_event(self, event):
        """Notify all listeners of a task event.
        
        Args:
            event: TaskEvent instance
            
        Returns:
            None
        """
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                # Don't let listener errors affect task management, just log it
                logger.error(f"SystemManager: Error notifying listener: {listener}")

    @staticmethod
    def _on_task_event(event):
        """Handle task lifecycle events."""
        if event.event_type == TaskEvent.TASK_FAILED:
            logger.error(f"SystemManager: Task {event.task_id} failed with error: {event.error}")
        elif event.event_type == TaskEvent.TASK_COMPLETED:
            logger.debug(f"SystemManager: Task {event.task_id} completed")
        elif event.event_type == TaskEvent.TASK_STARTED:
            logger.debug(f"SystemManager: Task {event.task_id} started")
        elif event.event_type == TaskEvent.TASK_STOPPED:
            logger.debug(f"SystemManager: Task {event.task_id} stopped")