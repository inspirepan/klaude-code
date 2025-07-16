import asyncio
import signal
import threading
from typing import List, Optional

from ..message import AIMessage, BasicMessage
from ..tool import Tool
from .llm_client import LLMClient


class LLMManager:
    """Thread-safe LLM connection pool manager"""

    def __init__(self):
        self.client_pool = {}  # {thread_id: LLMClient}
        self.config_cache = None  # Current configuration
        self._lock = threading.Lock()
        self._interrupt_flag = threading.Event()  # Global interrupt flag
        self._active_tasks = set()  # Track active LLM tasks

    def initialize_from_config(self, config):
        """Initialize LLM manager from ConfigModel"""
        with self._lock:
            self.config_cache = {
                'model_name': config.model_name.value,
                'base_url': config.base_url.value,
                'api_key': config.api_key.value,
                'model_azure': config.model_azure.value,
                'max_tokens': config.max_tokens.value,
                'extra_header': config.extra_header.value,
                'extra_body': config.extra_body.value,
                'enable_thinking': config.enable_thinking.value,
                'api_version': config.api_version.value,
            }

    def get_client(self) -> LLMClient:
        """Get LLM client for current thread"""
        thread_id = threading.get_ident()

        if thread_id not in self.client_pool:
            if not self.config_cache:
                raise RuntimeError('LLMManager not initialized. Call initialize_from_config() first.')

            # Create new client for this thread
            self.client_pool[thread_id] = LLMClient(
                model_name=self.config_cache['model_name'],
                base_url=self.config_cache['base_url'],
                api_key=self.config_cache['api_key'],
                model_azure=self.config_cache['model_azure'],
                max_tokens=self.config_cache['max_tokens'],
                extra_header=self.config_cache['extra_header'],
                extra_body=self.config_cache['extra_body'],
                enable_thinking=self.config_cache['enable_thinking'],
                api_version=self.config_cache['api_version'],
            )

        return self.client_pool[thread_id]

    async def call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        show_status: bool = True,
        status_text: Optional[str] = None,
        timeout: float = 20.0,
        show_result: bool = True,
    ) -> AIMessage:
        """Unified LLM call interface with interrupt handling"""
        client = self.get_client()
        call_task = None

        # Set up interrupt handler first
        interrupt_handler_added = False
        original_handler = None

        def signal_handler(signum, frame):
            self._interrupt_flag.set()
            # Cancel the current LLM request at the proxy level
            client.cancel()
            if call_task and not call_task.done():
                call_task.cancel()

        try:
            # Try to add signal handler
            try:
                original_handler = signal.signal(signal.SIGINT, signal_handler)
                interrupt_handler_added = True
            except (ValueError, OSError):
                # Signal handling not available in this thread
                pass

            # Check if interrupt flag is already set
            if self._interrupt_flag.is_set():
                self._interrupt_flag.clear()
                raise asyncio.CancelledError('LLM call interrupted by SIGINT')

            # Create a task for the LLM call after setting up interrupt handling
            call_task = asyncio.create_task(
                client.call(
                    msgs,
                    tools,
                    show_status=show_status,
                    status_text=status_text,
                    timeout=timeout,
                    show_result=show_result,
                )
            )

            # Track the active task
            self._active_tasks.add(call_task)

            # Wait for the task to complete or be interrupted
            try:
                result = await call_task
                return result
            except asyncio.CancelledError:
                # Check if it was our interrupt
                if self._interrupt_flag.is_set():
                    self._interrupt_flag.clear()
                    raise asyncio.CancelledError('LLM call interrupted by SIGINT')
                raise

        finally:
            # Cleanup
            if call_task:
                self._active_tasks.discard(call_task)
            if interrupt_handler_added and original_handler is not None:
                signal.signal(signal.SIGINT, original_handler)

    async def cleanup_thread(self, thread_id: Optional[int] = None):
        """Clean up client for specific thread (or current thread)"""
        if thread_id is None:
            thread_id = threading.get_ident()

        if thread_id in self.client_pool:
            client = self.client_pool[thread_id]
            # Proactively close HTTP client connections
            try:
                if hasattr(client.client, 'client'):
                    http_client = client.client.client
                    if hasattr(http_client, 'aclose'):
                        await http_client.aclose()
            except Exception:
                # Ignore cleanup errors
                pass
            del self.client_pool[thread_id]

    def reset(self):
        """Reset all clients and configuration"""
        with self._lock:
            # Cancel all active tasks
            for task in self._active_tasks:
                if not task.done():
                    task.cancel()
            self._active_tasks.clear()

            self.client_pool.clear()
            self.config_cache = None
            self._interrupt_flag.clear()

    def interrupt_all(self):
        """Interrupt all active LLM calls"""
        self._interrupt_flag.set()
        for task in self._active_tasks:
            if not task.done():
                task.cancel()
