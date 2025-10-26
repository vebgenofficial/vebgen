# backend/src/ui/main_window.py
import time
import tkinter as tk
import tempfile
import logging

import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageFilter
import threading
import queue
import math
import asyncio
import os # Import the os module
import re
import platform
import sys # For command execution output redirection (optional)
import difflib # NEW: Import for calculating line-by-line diffs
import ast # For parsing action parameters
from datetime import datetime # For structured logging
import subprocess # For command execution
import shlex
from tkinter import scrolledtext, messagebox, filedialog, simpledialog, Menu, StringVar, BooleanVar, END, WORD, BOTH, X, LEFT, RIGHT, BOTTOM, SUNKEN, NORMAL, DISABLED, W, E, ttk
from pathlib import Path # Keep Path import
from typing import List, Dict, Any, Optional, Tuple, Callable, Awaitable, Union

# --- NEW: Imports for Syntax Highlighting ---
from pygments import highlight, lex
from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
from pygments.formatters import HtmlFormatter
from html.parser import HTMLParser
# --- END NEW ---
from functools import partial # For creating button commands with arguments
import json # Import json

# Import core components
# Assuming they are in the 'core' directory relative to 'src'
try:
    from ..core.workflow_manager import WorkflowManager, RequestCommandExecutionCallable # Import the specific callback type
    from ..core.agent_manager import AgentManager # Use relative import
    from ..core.memory_manager import MemoryManager
    from ..core.config_manager import ConfigManager
    from ..core.file_system_manager import FileSystemManager, PatchApplyError
    from ..core.command_executor import CommandExecutor
    from ..core.secure_storage import check_keyring_backend, store_credential
    # Import specific exceptions for handling workflow interruptions
    from ..core.llm_client import RateLimitError, AuthenticationError
    from ..core.workflow_manager import InterruptedError
    from ..core.project_models import FeatureStatusEnum
except ImportError as e:
    # Handle potential import errors if the structure is different or files are missing
    logging.error(f"Failed to import core components: {e}. Ensure core modules are in the correct path.")
    # Optionally re-raise or exit if core components are essential
    raise

# Import UI utilities
# Assuming they are in the same directory or configured in PYTHONPATH
try:
    from .tooltip import ToolTip
    from .user_action_dialog import UserActionDialog
except ImportError as e:
    logging.error(f"Failed to import UI utilities: {e}. Ensure tooltip.py and user_action_dialog.py are present.")
    # Define dummy classes if utilities are missing but not critical for basic function
    class ToolTip:
        def __init__(self, widget, text, delay_ms=500): pass # Added delay_ms default
    class UserActionDialog:
        def __init__(self, parent: tk.Misc, title: str, instructions: str, command_string: str):
            self.result = False # Dummy result
            # Simulate waiting behavior if needed for testing, though not ideal
            # messagebox.showinfo(title, f"{instructions}\n\nCommand:\n{command_string}\n\n(Dummy Dialog - Assuming Cancel)", parent=parent)


logger = logging.getLogger(__name__)

# --- Constants for UI and Queue ---
# These constants define the types of messages passed between the background workflow thread and the main UI thread.
QUEUE_MSG_UPDATE_UI = 1           # Message type for general UI updates (progress, status, messages)
QUEUE_MSG_SHOW_DIALOG = 2         # Message type to request showing a modal dialog
QUEUE_MSG_DISPLAY_COMMAND = 3     # Message type to display a command execution task in the UI
QUEUE_MSG_COMMAND_RESULT_INTERNAL = 4 # Internal message type (not used directly by queue put)
QUEUE_MSG_REQUEST_API_KEY_UPDATE = 5 # New: For API key update dialog
QUEUE_MSG_REQUEST_NETWORK_RETRY = 6  # New: For network retry dialog

# Keys for storing UI preferences in project state placeholders
# These keys are used to save and load the user's last selected provider and model for a project.
UI_PREF_PROVIDER = "ui_pref_provider_id"
UI_PREF_MODEL = "ui_pref_model_id"

# --- Model Data Store ---
# This will be populated from ConfigManager
MODEL_DATA: List[Dict[str, str]] = []

# --- UI Theme Constants ---
# Defines colors for different status indicators in the UI.
STATUS_COLORS = {
    "pending": "#3B82F6",      # Blue
    "running": "#F7630C",      # Orange
    "remediating": "#F7630C",  # Orange
    "success": "#2ECC71",      # Green
    "error": "#E81123",        # Red
}

# --- NEW: Status Colors for Command Cards ---
STATUS_COLORS = {
    "pending": "#3B82F6",      # Blue
    "running": "#F97316",      # Orange
    "success": "#10B981",      # Green
    "error": "#EF4444",        # Red
}
# --- End Constants ---

# --- NEW: Color mapping for log levels ---
level_colors = {
    "INFO": "#8BE9FD",    # Cyan
    "WARNING": "#F9E2AF", # Yellow
    "ERROR": "#EF4444",   # Red
    "DEBUG": "#A0A0A0",   # Gray
}

# --- NEW: Status Badges for Command Cards ---
STATUS_BADGES = {
    "pending": ("⏳", "#3B82F6"),
    "running": ("⚡", "#F97316"),
    "success": ("✅", "#10B981"),
    "error": ("❌", "#EF4444"),
    "skipped": ("⏭️", "#9CA3AF"),
}

# --- NEW: Icons for Action Cards ---
ACTION_ICONS = {
    # File Operations
    "GET_FULL_FILE_CONTENT": "📄",
    "WRITE_FILE": "✨",
    "PATCH_FILE": "✏️",
    "DELETE_FILE": "🗑️",
    # Execution
    "RUN_COMMAND": "⚡",
    "CREATE_DIRECTORY": "📁",
    # Agent/User Interaction
    "REQUEST_USER_INPUT": "👤",
    "TARS_CHECKPOINT": "🤔",
    "ROLLBACK": "⏪",
    "FINISH_FEATURE": "🏁",
    "ABORT": "🛑",
}

FILE_ICONS = {
    'py': '🐍',
    'js': '📜',
    'html': '🌐',
    'css': '🎨',
    'json': '📋',
    'md': '📝',
    'txt': '📄',
    'sh': '❯',
    'yml': '⚙️',
    'yaml': '⚙️',
    'toml': '⚙️',
}


class MainWindow:
    """Main GUI window for VebGen"""

    # ✅ Add these class-level dictionaries
    ACTION_ICONS = {
        "GET_FULL_FILE_CONTENT": "📄",
        "WRITE_FILE": "✨",
        "PATCH_FILE": "✏️",
        "UPDATE_FILE": "✏️",
        "DELETE_FILE": "🗑️",
        "READ_FILE": "👀",
        "RUN_COMMAND": "⚡",
        "CREATE_DIRECTORY": "📁",
        "INSTALL_PACKAGE": "📦",
        "APPLY_PATCH": "🔧",
        "ANALYZE_CODE": "🔍",
        "RUN_TESTS": "🧪",
        "LINT_CODE": "🔬",
        "GIT_COMMIT": "💾",
        "GIT_PUSH": "☁️",
        "GIT_PULL": "⬇️",
        "RUN_MIGRATIONS": "🗄️",
        "CREATE_MODEL": "📊",
    }

    FILE_ICONS = {
        'py': '🐍',
        'js': '📜',
        'ts': '📘',
        'jsx': '⚛️',
        'tsx': '⚛️',
        'html': '🌐',
        'css': '🎨',
        'scss': '🎨',
        'json': '📋',
        'yaml': '📋',
        'yml': '📋',
        'md': '📝',
        'txt': '📄',
        'sql': '🗄️',
        'sh': '🔧',
        'env': '🔐',
    }
    """
    Main application window for the AI Agent Development tool.

    Handles UI setup, user interactions (project selection, prompt input, model selection),
    and orchestrates the background workflow execution via WorkflowManager. Manages
    thread-safe communication between the background workflow and the Tkinter UI thread.
    """
    def __init__(self, master: tk.Tk):
        """
        Initializes the main application window.

        Args:
            master: The root Tkinter window instance.
        """
        self.master = master
        self.logger = logging.getLogger(__name__)
        self.master.title("Vebgen")
        self.master.geometry("1280x768") # Wider to accommodate sidebar
        self.master.minsize(1024, 700) # BUG FIX #3: Set default cursor
        self.default_cursor_spec = "arrow" # Default fallback cursor
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        # Load custom cursor
        cursor_path = Path(__file__).parent / "assets" / "vebgen_cursor.cur"
        if cursor_path.exists():
            try:
                cursor_spec = f"@{cursor_path.as_posix()}"
                if platform.system() == "Windows" and ' ' in str(cursor_path):
                    # On Windows, paths with spaces are problematic for Tcl/Tk.
                    # The most robust solution is to get the "short name" (8.3 filename).
                    import ctypes
                    from ctypes import wintypes

                    _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
                    _GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
                    _GetShortPathNameW.restype = wintypes.DWORD

                    buffer = ctypes.create_unicode_buffer(len(str(cursor_path)) + 1)
                    if _GetShortPathNameW(str(cursor_path), buffer, len(buffer)):
                        short_path = buffer.value
                        cursor_spec = f"@{Path(short_path).as_posix()}"
                        logger.info(f"Using Windows short path for cursor to avoid spaces: {short_path}")
                self.default_cursor_spec = cursor_spec
                self.master.config(cursor=self.default_cursor_spec)
            except Exception as e:
                logger.error(f"Failed to set custom cursor, falling back to arrow. Error: {e}")
                self.master.config(cursor="arrow")
        else:
            self.master.config(cursor=self.default_cursor_spec)
        logger.info(f"Custom cursor: {cursor_path.exists()}")

        # Set the application icon, handling different OS requirements.
        # --- Set Window Icon (Platform-Specific) ---
        try:
            assets_dir = Path(__file__).parent / "assets"
            logo_ico_path = assets_dir / "vebgen_logo.ico"
            logo_png_path = assets_dir / "vebgen_logo.png"

            if platform.system() == "Windows":
                if logo_ico_path.exists():
                    self.master.iconbitmap(logo_ico_path)
                    logger.info(f"Window icon set from: {logo_ico_path}")
                elif logo_png_path.exists():
                    # Use 'with' to ensure the image file handle is closed
                    with Image.open(logo_png_path) as pil_image:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".ico") as tmp_ico:
                            pil_image.save(tmp_ico.name, format="ICO", sizes=[(32, 32)])
                            self.master.iconbitmap(tmp_ico.name)
                    logger.info(f"Window icon set from temporary .ico created from {logo_png_path}")
                else:
                    logger.warning("Window icon 'vebgen_logo.ico' or '.png' not found.")
            else:
                # For macOS/Linux, use PhotoImage
                if logo_png_path.exists():
                    with Image.open(logo_png_path) as pil_image:
                        self.logo_photo_image = ImageTk.PhotoImage(pil_image)
                    self.master.iconphoto(True, self.logo_photo_image)
                    logger.info(f"Window icon set from: {logo_png_path}")
                else:
                    logger.warning("Window icon 'vebgen_logo.png' not found.")
        except Exception as e:
            logger.error(f"Failed to set window icon: {e}")

        # --- Modern Styling (CustomTkinter) ---
        self._configure_style() # Apply custom styles

        # --- Core Component Instances ---
        # --- Core Component Instances ---
        # These are initialized after a project directory is selected.
        self.project_root: Optional[str] = None
        self.memory_manager: Optional[MemoryManager] = None
        self.config_manager: Optional[ConfigManager] = None
        self.file_system_manager: Optional[FileSystemManager] = None
        self.command_executor: Optional[CommandExecutor] = None
        self.agent_manager: Optional[AgentManager] = None
        self.workflow_manager_instance: Optional[WorkflowManager] = None
        self.last_selected_framework: Optional[str] = None
        self.core_components_initialized = False # Tracks if core backend is ready
        self.is_new_project_at_selection: bool = True # New flag to latch the project state
        self.is_continuing_run = False # New flag to track if we are resuming a stopped job
        self.is_running = False # Tracks if a background workflow is active
        self.is_browsing_files = False # New flag for file browser mode
        self.available_frameworks: List[str] = [] # Populated by ConfigManager
        self.stop_event_thread = threading.Event() # For command executor
        self.needs_initialization = True # Flag for WorkflowManager initialization
        self.ui_communicator = self

        # --- UI Variables ---
        # --- UI Variables ---
        # These connect UI widgets to underlying data.
        self.framework_var = StringVar(self.master)
        self.project_path_var = StringVar(self.master, value="No Project Selected")
        self.is_new_project = BooleanVar(self.master, value=True) # Default to assuming new project
        self.provider_var = StringVar(self.master)
        self.model_var = StringVar(self.master)
        self.status_var = StringVar(self.master) # For the status bar text
        self.progress_var = tk.DoubleVar(self.master) # For the progress bar value
        self.tars_temp_var = tk.DoubleVar(value=0.2) # Default Tars temperature
        self.case_temp_var = tk.DoubleVar(value=0.1) # Default Case temperature

        # --- UI Element References ---
        # --- UI Element References ---
        # Keep references to widgets for enabling/disabling, updating text, etc.
        self.sidebar_frame: Optional[ctk.CTkFrame] = None
        self.main_content_frame: Optional[ctk.CTkFrame] = None
        self.select_project_button: Optional[ctk.CTkButton] = None
        self.project_path_label: Optional[ctk.CTkLabel] = None
        self.framework_label: Optional[ctk.CTkLabel] = None
        self.framework_dropdown: Optional[ctk.CTkComboBox] = None
        self.new_project_check: Optional[ctk.CTkCheckBox] = None
        self.help_label: Optional[ctk.CTkLabel] = None
        self.prompt_entry: Optional[ctk.CTkEntry] = None
        self.send_button: Optional[ctk.CTkButton] = None
        self.provider_dropdown: Optional[ctk.CTkComboBox] = None
        self.model_dropdown: Optional[ctk.CTkComboBox] = None
        self.tars_temp_label: Optional[ctk.CTkLabel] = None
        self.tars_temp_scale: Optional[ctk.CTkSlider] = None
        self.case_temp_label: Optional[ctk.CTkLabel] = None # Keep this reference
        self.case_temp_scale: Optional[ctk.CTkSlider] = None
        self.notebook: Optional[ctk.CTkTabview] = None
        self.change_api_key_button: Optional[ctk.CTkButton] = None
        self.updates_display: Optional[tk.Text] = None
        self.conversation_display: Optional[ctk.CTkTextbox] = None
        self.status_frame: Optional[ctk.CTkFrame] = None
        self.status_label: Optional[ctk.CTkLabel] = None
        self.updates_status_frame: Optional[ctk.CTkFrame] = None
        self.updates_status_label: Optional[ctk.CTkLabel] = None # This will be removed
        self.conversation_status_frame: Optional[ctk.CTkFrame] = None
        self.code_output_tab: Optional[tk.Frame] = None
        self.conversation_status_label: Optional[ctk.CTkLabel] = None
        self.progress_bar: Optional[ctk.CTkProgressBar] = None # This will be removed
        self.logo_image: Optional[ctk.CTkImage] = None
        self.exec_settings_icon: Optional[ctk.CTkImage] = None
        self.wash_effect_image: Optional[ctk.CTkImage] = None
        self.wash_effect_label: Optional[ctk.CTkLabel] = None
        self.animation_label: Optional[ctk.CTkLabel] = None # For loading animation
        self.logo_photo_image: Optional[ImageTk.PhotoImage] = None # Store PhotoImage for icons
        # --- NEW: Attributes for modern log display ---
        # --- NEW: Attributes for modern IDE features ---
        self.left_diff_text: Optional[ctk.CTkTextbox] = None
        self.right_diff_text: Optional[ctk.CTkTextbox] = None
        self.command_card_frame: Optional[ctk.CTkScrollableFrame] = None
        # --- NEW: Attributes for enhanced status bar ---
        self.status_icon: Optional[ctk.CTkLabel] = None
        self.status_text: Optional[ctk.CTkLabel] = None
        self.model_badge_label: Optional[ctk.CTkLabel] = None
        self.step_label: Optional[ctk.CTkLabel] = None
        self.time_label: Optional[ctk.CTkLabel] = None
        self.start_time: Optional[float] = None
        self.timer_job: Optional[str] = None
        # --- END NEW ---
        self.animation_job: Optional[str] = None # To hold the .after() job ID

        # --- Threading and Queue for UI Updates ---
        # --- Threading and Queue for UI Updates ---
        # Queue for thread-safe communication from background threads to the UI thread.
        self.ui_queue: queue.Queue[Tuple[int, Dict[str, Any]]] = queue.Queue()
        # Used to store results from modal dialogs requested by background threads.
        self.dialog_result: Any = None
        # Used to manage command execution requested by WorkflowManager.
        self.command_exec_results: Dict[str, Tuple[bool, str]] = {} # task_id -> (success, output)
        self.command_exec_events: Dict[str, threading.Event] = {} # task_id -> event (for synchronization)

        # --- Create UI Layout ---
        # --- Create UI Layout ---
        # Create a main container frame to act as a bezel
        bezel_frame = ctk.CTkFrame(self.master, fg_color="#000000", corner_radius=0)
        bezel_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # Main layout frames are now parented to the bezel_frame
        self.sidebar_frame = ctk.CTkFrame(bezel_frame, width=320, corner_radius=0, fg_color="#252526", border_width=1, border_color="#4A4A4A")
        self.sidebar_frame.pack(side=LEFT, fill=tk.Y, expand=False)
        self.sidebar_frame.pack_propagate(False) # Prevent frame from shrinking to fit content

        self.main_content_frame = ctk.CTkFrame(bezel_frame, corner_radius=0, fg_color="#1E1E1E")
        self.main_content_frame.pack(side=RIGHT, fill=BOTH, expand=True)

        self._create_ui_layout()
        # --- Start UI Queue Processing Loop ---
        # --- Start UI Queue Processing Loop ---
        # Periodically check the queue for messages from background threads.
        self.master.after(100, self._process_ui_queue)

        # --- NEW: Setup keyboard shortcuts ---
        self.setup_keyboard_shortcuts()

        # --- NEW: Bind Command Palette shortcut ---
        self.master.bind("<Control-Shift-P>", lambda e: self.create_command_palette())

        logger.info("MainWindow initialized. Waiting for project directory selection.")
        self.status_var.set("Please select a project directory via File menu.")
        # Initially disable controls that require a project context.
        self._set_ui_initial_state()

    def _create_ui_layout(self):
        """Creates the main UI layout by populating the sidebar and main content frames."""
        self._create_sidebar(self.sidebar_frame) # type: ignore
        self._create_main_content(self.main_content_frame) # type: ignore

    def _configure_style(self):
        """Configures text tags for styling different types of messages in the UI."""
        """Configures the ttk styles for a modern application appearance."""
        ctk.set_appearance_mode("Dark")  # Modes: "System" (default), "Dark", "Light"
        ctk.set_default_color_theme("blue")  # Themes: "blue" (default), "green", "dark-blue"

        # --- Text Area Tags for Formatting Messages ---
        # These will be applied to CTkTextbox widgets
        self.text_tags = {
            "user": {"font": ("Calibri", 16, 'bold'), "foreground": "#FFFFFF"},
            "system": {"foreground": "#B0B0B0", "font": ("Calibri", 14, 'italic')},
            "error": {"foreground": "#FF5555", "font": ("Calibri", 14, 'bold')},
            "warning": {"foreground": "#FFB86C", "font": ("Calibri", 14)},
            "agent_name": {"foreground": "#50FA7B", "font": ("Calibri", 16, 'bold')},
            "action": {"foreground": "#8BE9FD", "font": ("Calibri", 14, 'bold')},
            "success": {"foreground": "#50FA7B", "font": ("Calibri", 14, 'bold')},
            # Code tag for command entry widgets and code blocks - darker background
            "code": {"font": ("Consolas", 11), "background": "#252526", "foreground": "#DCE4EE", "wrap": "none",
                     "lmargin1": 10, "lmargin2": 10, "spacing1": 5, "spacing3": 5, "relief": tk.GROOVE, "borderwidth": 1},
            # Command output: monospaced, darker background
            "command_output": {"font": ("Consolas", 11), "foreground": "#CCCCCC", "background": "#252526", "wrap": "none",
                               "lmargin1": 10, "lmargin2": 10, "spacing1": 2, "spacing3": 2},
            # Default tag for regular messages
            "default": {"font": ("Calibri", 16), "foreground": "#FFFFFF"}
        }
        # BUG FIX #4: Add new text tags for better styling
        self.text_tags.update({
            "header": {
                "font": ("Segoe UI", 14, "bold"),
                "foreground": "#3B82F6"
            },
            "code_label": {
                "font": ("Consolas", 10, "bold"),
                "foreground": "#6366F1"
            },
            "code_block": {
                "font": ("Consolas", 9),
                "foreground": "#F8F8F2",
                "background": "#1E1E2E"
            },
            "error": {
                "font": ("Segoe UI", 12, "bold"),
                "foreground": "#EF4444"
            }
        })

    def _configure_text_widget_tags(self, text_widget: ctk.CTkTextbox):
        """Applies all configured text tags to a given CTkTextbox widget."""
        if not text_widget or not text_widget.winfo_exists():
            return
        
        # --- NEW: Improved Tag Styling ---
        # CASE agent (primary)
        text_widget.tag_config(
            "case_tag",
            foreground="#3b82f6",  # Blue
            font=("Segoe UI", 10, "normal")
        )
        # TARS agent (secondary)
        text_widget.tag_config(
            "tars_tag",
            foreground="#8b5cf6",  # Purple
            font=("Segoe UI", 10, "normal")
        )
        # System messages (neutral)
        text_widget.tag_config(
            "system_tag",
            foreground="#6b7280",  # Gray
            font=("Segoe UI", 10, "normal")
        )
        # User messages (highlight)
        text_widget.tag_config(
            "user_tag",
            foreground="#10b981",  # Green
            font=("Segoe UI", 10, "bold")
        )
        # Error messages (danger)
        text_widget.tag_config(
            "error_tag",
            foreground="#ef4444",  # Red
            font=("Segoe UI", 10, "bold")
        )
        # Success messages (positive)
        text_widget.tag_config(
            "success_tag",
            foreground="#10b981",  # Green
            font=("Segoe UI", 10, "normal")
        )

        # --- NEW: Add tags for diff highlighting ---
        # --- VS Code Dark+ Diff Colors ---
        self.text_tags['diff_add'] = {"background": "#1e3a1e", "foreground": "#d4d4d4"}
        self.text_tags['diff_delete'] = {"background": "#3f1d1d", "foreground": "#d4d4d4"}
        self.text_tags['diff_modified'] = {"background": "#1e3d5c", "foreground": "#d4d4d4"}
        # --- NEW: Add tags for syntax highlighting (Monokai theme colors) ---
        # --- VS Code Dark+ Theme Colors ---
        self.text_tags["syntax_keyword"] = {"foreground": "#569cd6"}      # Blue (if, class, def, import)
        self.text_tags["syntax_string"] = {"foreground": "#ce9178"}       # Orange-brown (strings)
        self.text_tags["syntax_comment"] = {"foreground": "#6a9955"}      # Green (comments)
        self.text_tags["syntax_number"] = {"foreground": "#b5cea8"}       # Light green (numbers)
        self.text_tags["syntax_function"] = {"foreground": "#dcdcaa"}     # Yellow (function names)
        self.text_tags["syntax_class"] = {"foreground": "#4ec9b0"}        # Cyan (class names)
        self.text_tags["syntax_operator"] = {"foreground": "#d4d4d4"}     # Light gray (operators)
        self.text_tags["syntax_builtin"] = {"foreground": "#4ec9b0"}      # Cyan (built-ins like print, len)
        self.text_tags["syntax_variable"] = {"foreground": "#9cdcfe"}     # Light blue (variables)
        self.text_tags["syntax_decorator"] = {"foreground": "#dcdcaa"}    # Yellow (decorators @app.route)
        # --- END NEW ---

        # Iterate through the configurations and apply them correctly.
        for tag_name, config in self.text_tags.items():
            # Create a copy of the config to modify it safely, removing the 'font' key.
            tag_specific_config = config.copy()
            
            # --- FIX: Remove the 'font' key to prevent the crash ---
            # We will rely on the default font of the CTkTextbox for now.
            # This resolves the AttributeError and allows the app to run.
            if "font" in tag_specific_config:
                del tag_specific_config["font"]
            
            # Apply the (now corrected) configuration to the tag.
            # The ** operator unpacks the dictionary into keyword arguments.
            text_widget.tag_config(tag_name, **tag_specific_config)

    def update_task_in_ui(self, task_id: str, updates: Dict[str, Any]):
        """
        Public method for external components like WorkflowManager to send UI updates
        for a specific task widget. This is a simplified entry point that queues
        a generic update for now.
        """
        """
        Public method for external components like WorkflowManager to send UI updates.
        This method is thread-safe as it queues the update for the main UI thread.
        """
        if self.notebook:
            # The internal _update_widget_map_and_ui method is already designed
            # to handle being called from other threads via the queue.
            self._update_widget_map_and_ui(task_id, updates)
        else:
            logger.warning(f"Attempted to update UI for task {task_id} before UI is fully initialized.")

    def _update_widget_map_and_ui(self, task_id: str, updates: Dict[str, Any]):
        """
        Internal helper to queue a direct widget update for the UI thread.
        This is intended to be called by methods that need to update a specific
        task's UI elements from a background thread.
        """
        """
        Internal helper to queue a direct widget update for the UI thread.
        This is intended to be called by methods that need to update a specific
        task's UI elements (e.g., a button's state) from a background thread.
        """
        # This method is a placeholder for a more complex widget mapping system.
        # For now, it will find the relevant UI frame for a task and queue an update.
        # This is a simplified implementation for the sake of fixing the immediate bug.
        
        # We find the button associated with the task and queue an update for it.
        # This is a simplified approach. A real implementation might use a dictionary
        # to map task_id to widgets.
        
        # Since we don't have a direct widget map, we'll log a warning and queue a generic update.
        logger.debug(f"Queuing UI update for task {task_id} with updates: {updates}")
        
        # For the purpose of this fix, we will just log that the update was requested.
        # In a more complete implementation, you would find the specific widget
        # associated with the task_id and update it.
        # For now, we will just send a generic system message.
        
        summary = updates.get("summary", "Task status updated.")
        status = updates.get("status", "IN_PROGRESS")
        
        message = f"Task {task_id}: Status changed to {status}. Summary: {summary}"
        self.update_progress_safe({'system_message': message})

    def _create_sidebar(self, parent_frame: ctk.CTkFrame):
        """Creates and populates the left sidebar with project and agent settings."""
        """Creates the left sidebar for configuration and settings."""
        # Sidebar Header - make it a bit taller to show the effect
        header_frame = ctk.CTkFrame(parent_frame, fg_color="transparent", height=80)
        header_frame.pack(pady=(0, 20), padx=0, fill=X)
        header_frame.pack_propagate(False) # Prevent it from shrinking

        # --- Content on top of the effect ---
        content_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        content_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=20)

        # Configure grid layout to place logo and text adjacent with no space
        content_frame.grid_columnconfigure(0, weight=0)
        content_frame.grid_columnconfigure(1, weight=0)

        # Add logo before the brand name
        logo_path = Path(__file__).parent / "assets" / "vebgen_logo.png"
        if logo_path.exists():
            img = Image.open(logo_path)
            self.logo_image = ctk.CTkImage(img, size=(64, 64))
            logo_label = ctk.CTkLabel(content_frame, image=self.logo_image, text="") # type: ignore
            logo_label.grid(row=0, column=0, padx=0, pady=(10, 0), sticky="w")


        # Frame to hold the two-colored brand name
        brand_text_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        # Place text immediately in the next column with no padding to bring it closer
        brand_text_frame.grid(row=0, column=1, padx=0, pady=(10,0), sticky="w")

        veb_label = ctk.CTkLabel(brand_text_frame, text="Veb", font=ctk.CTkFont(size=32, weight="bold"), text_color="#FFFFFF")
        veb_label.pack(side=LEFT)

        gen_label = ctk.CTkLabel(brand_text_frame, text="Gen", font=ctk.CTkFont(size=30, weight="bold"), text_color="#0078D4")
        gen_label.pack(side=LEFT)

        # Project Selection
        project_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        project_frame.pack(pady=(0, 25), padx=0, fill=X)
        self.project_path_label = ctk.CTkLabel(project_frame, textvariable=self.project_path_var, fg_color="#3C3C3C", corner_radius=5, height=30, font=ctk.CTkFont(family="Consolas", size=13), anchor="w", padx=10)
        self.project_path_label.pack(fill=X, pady=(0, 10))
        ToolTip(self.project_path_label, text="Current project directory.")

        self.select_project_button = ctk.CTkButton(
            project_frame,
            text="📂  Select Project Directory...",
            command=self.select_project_directory,
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        )
        self.select_project_button.pack(fill=X, ipady=8, pady=6)

        # Execution Settings
        exec_settings_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        exec_settings_frame.pack(pady=(0, 25), padx=0, fill=X)

        exec_title_frame = ctk.CTkFrame(exec_settings_frame, fg_color="transparent")
        exec_title_frame.pack(anchor="w", pady=(0, 15), fill=X)

        # Load and display the icon for Execution Settings
        # For black_square.svg, a simple character might work well and avoids new dependencies.
        # Using a geometric shape character as a placeholder for the SVG.
        exec_icon_label = ctk.CTkLabel(exec_title_frame, text="⚙️", font=ctk.CTkFont(size=16))
        exec_icon_label.pack(side=LEFT, padx=(0, 8))
        exec_title = ctk.CTkLabel(exec_title_frame, text="Execution Settings", font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"))
        exec_title.pack(side=LEFT, anchor="w")

        fw_label = ctk.CTkLabel(exec_settings_frame, text="Framework", anchor="w", font=ctk.CTkFont(family="Segoe UI", size=13))
        fw_label.pack(fill=X, pady=(0, 5))
        self.framework_dropdown = ctk.CTkComboBox(exec_settings_frame, variable=self.framework_var, state=DISABLED, command=self.on_framework_selected)
        self.framework_dropdown.pack(fill=X, pady=(0, 15))

        checkbox_frame = ctk.CTkFrame(exec_settings_frame, fg_color="transparent")
        checkbox_frame.pack(fill=X)
        self.new_project_check = ctk.CTkCheckBox(checkbox_frame, text="New Project", variable=self.is_new_project, onvalue=True, offvalue=False, state=DISABLED)
        self.new_project_check.pack(side=LEFT)
        self.help_label = ctk.CTkLabel(checkbox_frame, text="?", width=20, height=20, fg_color="#3C3C3C", text_color="#0098FF", corner_radius=10, font=ctk.CTkFont(weight="bold"), cursor="question_arrow")
        self.help_label.pack(side=LEFT, padx=8)


        ToolTip(self.help_label, text="Check if starting in an empty directory (runs initial setup).\nUncheck for existing projects.")

        # AI Model Settings
        ai_settings_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        ai_settings_frame.pack(pady=(0, 25), padx=0, fill=X)

        ai_title_frame = ctk.CTkFrame(ai_settings_frame, fg_color="transparent")
        ai_title_frame.pack(anchor="w", pady=(0, 15), fill=X)
        ai_title_frame.grid_columnconfigure(1, weight=1) # Allow label to expand

        ai_icon_label = ctk.CTkLabel(ai_title_frame, text="🧠", font=ctk.CTkFont(size=20))
        ai_icon_label.grid(row=0, column=0, sticky="w", pady=2)
        ai_title = ctk.CTkLabel(ai_title_frame, text="AI Model Settings", font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"))
        ai_title.grid(row=0, column=1, sticky="w", padx=8)

        provider_label = ctk.CTkLabel(ai_settings_frame, text="API Provider", anchor="w", font=ctk.CTkFont(family="Segoe UI", size=13))
        provider_label.pack(fill=X, pady=(0, 5))
        self.provider_dropdown = ctk.CTkComboBox(ai_settings_frame, variable=self.provider_var, state=DISABLED, command=self.on_provider_selected)
        self.provider_dropdown.pack(fill=X, pady=(0, 15))
        ToolTip(self.provider_dropdown, text="Select the AI service provider.")

        model_frame = ctk.CTkFrame(ai_settings_frame, fg_color="transparent")
        model_frame.pack(fill=X, pady=(0, 15))
        model_frame.grid_columnconfigure(0, weight=1)
        
        model_label = ctk.CTkLabel(ai_settings_frame, text="LLM Model", anchor="w", font=ctk.CTkFont(family="Segoe UI", size=13))
        model_label.pack(fill=X, pady=(0, 5))
        self.model_dropdown = ctk.CTkComboBox(model_frame, variable=self.model_var, state=DISABLED, command=self.on_model_selected)
        self.model_dropdown.grid(row=0, column=0, sticky="ew")

        manage_models_button = ctk.CTkButton(model_frame, text="Manage", width=70, command=self._open_manage_models_dialog, state=DISABLED)
        manage_models_button.grid(row=0, column=1, padx=(10, 0))
        self.manage_models_button = manage_models_button

        ToolTip(self.model_dropdown, text="Select the specific LLM to use for all tasks.")

        # Temperature Sliders
        tars_slider_frame = ctk.CTkFrame(ai_settings_frame, fg_color="transparent")
        tars_slider_frame.pack(fill=X, pady=(5,0))
        self.tars_temp_label = ctk.CTkLabel(tars_slider_frame, text="Tars Temp", width=70, anchor="w", font=ctk.CTkFont(family="Segoe UI", size=13))
        self.tars_temp_label.pack(side=LEFT)
        self.tars_temp_scale = ctk.CTkSlider(tars_slider_frame, from_=0.0, to=1.0, variable=self.tars_temp_var, number_of_steps=10)
        self.tars_temp_scale.pack(side=LEFT, expand=True, fill=X, padx=10)
        ToolTip(self.tars_temp_scale, text="Adjust Tars (Planner/Analyzer) temperature (0.0-1.0).")

        case_slider_frame = ctk.CTkFrame(ai_settings_frame, fg_color="transparent")
        case_slider_frame.pack(fill=X, pady=(5,0))
        self.case_temp_label = ctk.CTkLabel(case_slider_frame, text="Case Temp", width=70, anchor="w", font=ctk.CTkFont(family="Segoe UI", size=13))
        self.case_temp_label.pack(side=LEFT)
        self.case_temp_scale = ctk.CTkSlider(case_slider_frame, from_=0.0, to=1.0, variable=self.case_temp_var, number_of_steps=10)
        self.case_temp_scale.pack(side=LEFT, expand=True, fill=X, padx=10)
        ToolTip(self.case_temp_scale, text="Adjust Case (Coder) temperature (0.0-1.0).")

        # --- NEW: Change API Key Button ---
        self.change_api_key_button = ctk.CTkButton(
            ai_settings_frame, text="🔑 Change API Key...", command=self._change_api_key_manual, font=ctk.CTkFont(family="Segoe UI", size=13),
            state=DISABLED
        )
        self.change_api_key_button.pack(fill=X, pady=(20, 0))
        ToolTip(self.change_api_key_button, text="Manually update the API key for a selected provider.")

    def _create_main_content(self, parent_frame: ctk.CTkFrame):
        """Creates the main content area, including the prompt entry, notebook, and status bar."""
        """Creates the main content area (prompt, notebook, status bar)."""
        # Prompt Area
        prompt_area = ctk.CTkFrame(parent_frame, fg_color="transparent", border_width=0)
        prompt_area.pack(fill=X, padx=20, pady=20)

        prompt_wrapper = ctk.CTkFrame(prompt_area, fg_color="#252526", border_width=1, border_color="#4A4A4A", corner_radius=8)
        prompt_wrapper.pack(fill=X, expand=True)

        prompt_icon = ctk.CTkLabel(prompt_wrapper, text=">", font=ctk.CTkFont(family="Consolas", size=16), text_color="#808080")
        prompt_icon.pack(side=LEFT, padx=(15, 10))

        self.prompt_entry = ctk.CTkEntry(prompt_wrapper, placeholder_text="Describe your project goal...", font=ctk.CTkFont(family="Segoe UI", size=16), border_width=0, height=40)
        self.prompt_entry.pack(side=LEFT, fill=X, expand=True, pady=5)
        self.prompt_entry.bind("<Return>", self.handle_start_workflow)
        ToolTip(self.prompt_entry, "Enter your main project goal here and press Start or Enter.")

        # Add an animation label that will be shown when busy
        self.animation_label = ctk.CTkLabel(prompt_wrapper, text="", font=ctk.CTkFont(family="Consolas", size=16), text_color="#0078D4")
        self.animation_label.pack(side=LEFT, padx=10)

        # --- MODIFIED: The send_button now handles Start, Stop, and Continue ---
        self.send_button = ctk.CTkButton(
            prompt_wrapper, text="▶️ Start", command=self.handle_start_stop_continue,
            state=DISABLED, width=110, height=40,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"), corner_radius=6
        )
        self.send_button.pack(side=RIGHT, padx=5, pady=5)
        ToolTip(self.send_button, "Start, Stop, or Continue the agent's workflow (F5).")

        # Notebook
        self._create_notebook(parent_frame)

        # Status Bar
        # self._create_status_bar(parent_frame)

        self.create_enhanced_status_bar(parent_frame)

    def create_enhanced_status_bar(self, parent):
        """Create a comprehensive status bar like VS Code"""
        
        status_bar = ctk.CTkFrame(
            parent,
            height=28,
            fg_color="#1E1E1E",
            border_width=1,
            border_color="#3E3E42"
        )
        status_bar.pack(side="bottom", fill="x")
        status_bar.pack_propagate(False)
        
        # Left side - Main status
        left_frame = ctk.CTkFrame(status_bar, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True, padx=5)
        
        self.status_icon = ctk.CTkLabel(
            left_frame,
            text="●",
            text_color="#10B981",  # Green = ready
            font=("Segoe UI", 14)
        )
        self.status_icon.pack(side="left", padx=5)
        
        self.status_text = ctk.CTkLabel(
            left_frame,
            textvariable=self.status_var, # Use the existing status variable
            font=("Segoe UI", 12),
            anchor="w"
        )
        self.status_text.pack(side="left", fill="x", expand=True)
        
        # Right side - Info badges
        right_frame = ctk.CTkFrame(status_bar, fg_color="transparent")
        right_frame.pack(side="right", padx=5)
        
        # Time elapsed
        self.time_label = ctk.CTkLabel(
            right_frame,
            text="⏱️ 00:00", font=("Segoe UI", 11),
            text_color="#9CA3AF"
        )
        self.time_label.pack(side="right", padx=5)

        # Model indicator (will be updated dynamically)
        self.model_badge_label = ctk.CTkLabel(
            right_frame, text="🤖 No Model", font=("Segoe UI", 11),
            fg_color="#6366F1", corner_radius=4, padx=8
        )
        self.model_badge_label.pack(side="right", padx=2)
        
        return status_bar



    def _create_status_bar(self, parent_frame: ctk.CTkFrame):
        """Creates the status bar at the bottom of the window."""
        self.status_frame = ctk.CTkFrame(parent_frame, height=30, corner_radius=0, border_width=1, border_color="#4A4A4A", fg_color="#252526")
        self.status_frame.pack(side=BOTTOM, fill=X, padx=0, pady=0)

        # Status label takes most of the space
        self.status_label = ctk.CTkLabel(self.status_frame, textvariable=self.status_var, fg_color="transparent", font=ctk.CTkFont(size=12), text_color="#A0A0A0")
        self.status_label.pack(side=LEFT, fill=X, expand=True, padx=(10, 0))

        # Progress bar on the right
        self.progress_bar = ctk.CTkProgressBar(self.status_frame, variable=self.progress_var, width=200, progress_color="#0078D4")
        self.progress_bar.pack(side=RIGHT, padx=10, pady=5)
        self.progress_bar.set(0) # Initialize to 0
        self.status_var.set("Select a project directory to begin.") # Initial status message

    def _create_updates_tab(self, tab: ctk.CTkFrame):
        """Creates the content for the 'Updates / Logs' tab."""
        # Use a CTkScrollableFrame to allow embedding both text labels and command card widgets
        self.updates_display = ctk.CTkScrollableFrame(
            tab,
            fg_color="#252526",
            label_text="Updates / Logs"
        )
        self.updates_display.pack(fill="both", expand=True)

    def _create_code_output_tab(self, tab: ctk.CTkFrame):
        """Creates the content for the 'Code Output' tab."""
        self.code_output_tab = tab

        # --- NEW: Header frame for buttons ---
        header_frame = ctk.CTkFrame(tab, fg_color="transparent")
        header_frame.pack(fill=X, padx=10, pady=(10, 0))

        self.browse_files_button = ctk.CTkButton(
            header_frame,
            text="📁 Browse Files",
            command=self._toggle_file_browser_view,
            state=DISABLED
        )
        self.browse_files_button.pack(side=LEFT)
        ToolTip(self.browse_files_button, "Toggle between viewing generated code and browsing all project files.")
        
        # --- NEW: Main frame to hold both conversation display and minimap ---
        code_output_content_frame = ctk.CTkFrame(tab, fg_color="transparent")
        code_output_content_frame.pack(expand=True, fill=BOTH, padx=10, pady=10)

        # --- BUG FIX: Use CTkScrollableFrame instead of CTkTextbox ---
        # This is the correct widget to hold multiple child widgets (our code blocks).
        # The "embedding widgets is forbidden" error occurs when trying to pack
        # complex frames into a Textbox.
        self.conversation_display = ctk.CTkScrollableFrame(
            code_output_content_frame,
            fg_color="#000000"  # Pure black background
        )
        # The scrollable frame doesn't need the key binding for copy, as copy
        # functionality is handled by buttons within each code block.
        self.conversation_display.pack(fill="both", expand=True)

    def _toggle_file_browser_view(self):
        """Toggles the file browser mode on and off."""
        self.is_browsing_files = not self.is_browsing_files

        if not self.conversation_display or not self.browse_files_button:
            return

        # Clear all existing widgets from the scrollable frame
        for widget in self.conversation_display.winfo_children():
            widget.destroy()

        if self.is_browsing_files:
            self.browse_files_button.configure(text="📖 View Generated Code", fg_color="#0078D4")
            self.status_var.set("Browsing project files...")
            self._display_project_files()
        else:
            self.browse_files_button.configure(text="📁 Browse Files", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"]) # type: ignore
            self.status_var.set("Viewing generated code...")
            # The view will now be populated by new agent actions.

    def _display_project_files(self):
        """Scans the project directory and displays all file contents."""
        if not self.file_system_manager or not self.conversation_display:
            return

        try:
            all_files = self.file_system_manager.get_all_files_in_project()

            # Add a header label to the scrollable frame
            header_label = ctk.CTkLabel(self.conversation_display, text=f"📂 Project Files ({len(all_files)} files found)", font=("Segoe UI", 16, "bold"), anchor="w")
            header_label.pack(fill=X, padx=10, pady=(5, 15))

            for file_path in sorted(all_files):
                try:
                    content = self.file_system_manager.read_file(file_path)
                    # --- BUG FIX: Handle .txt files correctly ---
                    # Pygments uses 'text' for plain text files, not 'txt'.
                    file_suffix = Path(file_path).suffix[1:]
                    if file_suffix == 'txt':
                        language = 'text'
                    else:
                        language = get_lexer_by_name(file_suffix).name.lower() if file_suffix else "text"

                    self._create_modern_code_block(self.conversation_display, content, language=language, file_path=file_path)
                except Exception as e:
                    error_label = ctk.CTkLabel(self.conversation_display, text=f"--- Error reading {file_path} ---\n{e}\n\n", text_color="red")
                    error_label.pack(fill=X, padx=10, pady=5)

        except Exception as e:
            logger.error(f"Failed to display project files: {e}")
            error_label = ctk.CTkLabel(self.conversation_display, text=f"Error scanning project directory: {e}\n", text_color="red")
            error_label.pack(fill=X, padx=10, pady=5)

    def _create_notebook(self, parent_frame: ctk.CTkFrame):
        """Creates the tabbed notebook for displaying updates/logs and conversation."""
        self.notebook = ctk.CTkTabview(parent_frame, border_width=1, border_color="#4A4A4A", segmented_button_selected_color="#0078D4", fg_color="#1E1E1E")
        self.notebook.pack(expand=True, fill=BOTH, padx=20, pady=(0, 0))

        updates_tab = self.notebook.add("📊 Updates / Logs")
        self._create_updates_tab(updates_tab)
        self._create_code_output_tab(self.notebook.add("📄 Code Output"))
        
        # --- NEW: Add the split view tab ---
        diff_tab = self.notebook.add("↔️ Code Diff")
        self.left_diff_text, self.right_diff_text = self._create_split_view(diff_tab)

    def _create_split_view(self, parent):
        """Create split view for comparing code versions"""
        
        split_container = ctk.CTkFrame(parent, fg_color="#1E1E1E")
        split_container.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Left pane (Original)
        left_pane = ctk.CTkFrame(split_container, fg_color="#252526", border_width=1, border_color="#4A4A4A")
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 2))
        
        left_label = ctk.CTkLabel(
            left_pane, text="📄 Original", font=("Segoe UI", 13, "bold"),
            fg_color="#3E3E42", height=30, anchor="w", padx=10
        )
        left_label.pack(fill="x")
        
        left_text = ctk.CTkTextbox(left_pane, font=("Consolas", 14, "bold"), wrap="none")
        left_text.pack(fill="both", expand=True, padx=1, pady=1)
        
        # Right pane (Modified)
        right_pane = ctk.CTkFrame(split_container, fg_color="#252526", border_width=1, border_color="#4A4A4A")
        right_pane.pack(side="right", fill="both", expand=True, padx=(2, 0))
        
        right_label = ctk.CTkLabel(
            right_pane, text="✏️ Modified", font=("Segoe UI", 13, "bold"),
            fg_color="#3E3E42", height=30, anchor="w", padx=10
        )
        right_label.pack(fill="x")
        
        right_text = ctk.CTkTextbox(right_pane, font=("Consolas", 14, "bold"), wrap="none")
        right_text.pack(fill="both", expand=True, padx=1, pady=1)
        
        # --- NEW: Configure tags for diff highlighting ---
        left_text.tag_config("diff_delete", background="#5A2D2D")
        right_text.tag_config("diff_add", background="#1e3a1e")
        # --- NEW: Configure tags for syntax highlighting (VS Code Theme) ---
        left_text.tag_config("syntax_keyword", foreground="#f92672")
        left_text.tag_config("syntax_string", foreground="#e6db74")
        left_text.tag_config("syntax_comment", foreground="#75715e")
        right_text.tag_config("syntax_keyword", foreground="#f92672")
        right_text.tag_config("syntax_string", foreground="#e6db74")
        right_text.tag_config("syntax_comment", foreground="#75715e")
        right_text.tag_config("syntax_number", foreground="#ae81ff")
        right_text.tag_config("syntax_function", foreground="#a6e22e")
        # --- END NEW ---

        return left_text, right_text

    def _display_diff_with_highlighting(self, original_content: str, modified_content: str):
        """
        Calculates a line-by-line diff and displays it in the split view
        with added/removed lines highlighted. It also applies syntax highlighting.
        """
        if not self.left_diff_text or not self.right_diff_text:
            return

        # --- Clear previous content ---
        self.left_diff_text.configure(state="normal")
        self.right_diff_text.configure(state="normal")
        self.left_diff_text.delete("1.0", "end")
        self.right_diff_text.delete("1.0", "end")

        # --- Determine language for syntax highlighting ---
        try:
            lexer = guess_lexer(modified_content or original_content)
            language = lexer.aliases[0]
        except Exception:
            language = "text"

        # --- Use difflib for line-by-line comparison ---
        diff = difflib.ndiff(original_content.splitlines(), modified_content.splitlines())

        original_lines = []
        modified_lines = []

        for line in diff:
            code = line[2:] + '\n'
            if line.startswith('+ '):
                # Line added to modified version
                original_lines.append(('\n', None)) # Add a blank line to original for alignment
                modified_lines.append((code, 'diff_add'))
            elif line.startswith('- '):
                # Line removed from original version
                original_lines.append((code, 'diff_delete'))
                modified_lines.append(('\n', None)) # Add a blank line to modified for alignment
            elif line.startswith('  '):
                # Line is unchanged
                original_lines.append((code, None))
                modified_lines.append((code, None))
            # Ignore '? ' lines which are informational diff lines

        # --- Render content with syntax and diff highlighting ---
        self._render_highlighted_lines(self.left_diff_text, original_lines, language)
        self._render_highlighted_lines(self.right_diff_text, modified_lines, language)

        self.left_diff_text.configure(state="disabled")
        self.right_diff_text.configure(state="disabled")

    def _render_highlighted_lines(self, widget: ctk.CTkTextbox, lines: List[Tuple[str, Optional[str]]], language: str):
        """
        Renders lines into a widget, applying a background tag for the whole line
        and then applying syntax highlighting on top.
        """
        for line_content, background_tag in lines:
            start_index = widget.index("end-1c")
            widget.insert("end", line_content)
            end_index = widget.index("end-1c")

            # Apply the background diff tag to the entire line first
            if background_tag:
                widget.tag_add(background_tag, start_index, end_index)

            # --- NEW: Apply syntax highlighting on top of the background ---
            self._apply_syntax_highlighting_to_range(widget, start_index, end_index, line_content, language)

    def _apply_syntax_highlighting_to_range(self, widget: ctk.CTkTextbox, start_index: str, end_index: str, code: str, language: str):
        """Applies pygments-based syntax highlighting to a specific range in a CTkTextbox."""
        try:
            lexer = get_lexer_by_name(language, stripall=True)
        except Exception: # pygments.util.ClassNotFound
            lexer = TextLexer() # Fallback for unknown languages

        # Define a mapping from Pygments token types to our custom Tkinter tags
        from pygments.token import Keyword, Name, String, Comment, Number, Operator, Punctuation, Text
        token_to_tag = {
            Keyword: "syntax_keyword",              # if, class, def
            String: "syntax_string",                # "strings"
            Comment: "syntax_comment",              # # comments
            Number: "syntax_number",                # 123
            Name.Function: "syntax_function",       # function_name()
            Name.Class: "syntax_class",             # ClassName
            Name.Builtin: "syntax_builtin",         # print, len
            Name.Decorator: "syntax_decorator",     # @decorator
            Name.Variable: "syntax_variable",       # variable_name
            # Name.Constant: "syntax_constant",       # CONSTANT_NAME
            Operator: "syntax_operator",            # +, -, =
            Punctuation: "syntax_operator",         # (, ), [, ]
        }

        # Tokenize the line of code
        tokens = lex(code, lexer)

        # Iterate through tokens and apply tags
        current_pos = 0
        for ttype, tvalue in tokens:
            tag = None
            # Find the most specific tag for the token type
            for token_class, tag_name in token_to_tag.items():
                if ttype in token_class:
                    tag = tag_name
                    break
            if tag:
                widget.tag_add(tag, f"{start_index}+{current_pos}c", f"{start_index}+{current_pos + len(tvalue)}c")
            current_pos += len(tvalue)

    # --- NEW: Keyboard Shortcuts and Helper Methods ---
    def setup_keyboard_shortcuts(self):
        """Setup intuitive keyboard shortcuts for common actions."""
        
        shortcuts = {
            "<Control-n>": self.handle_start_workflow,
            "<F5>": self.handle_start_workflow,
            "<Control-s>": self.save_project_state,
            "<Control-w>": self.clear_output,
            "<Control-l>": lambda: self.notebook.set("📊 Updates / Logs") if self.notebook else None,
            "<Control-o>": lambda: self.notebook.set("📄 Code Output") if self.notebook else None,
            "<Escape>": self.handle_stop_workflow
        }
        
        for key, func in shortcuts.items():
            # Use a lambda to capture the current function `f` in the loop
            self.master.bind(key, lambda e, f=func: f())
        logger.info("Keyboard shortcuts initialized.")

    def save_project_state(self):
        """Saves the current project state via the WorkflowManager."""
        if self.workflow_manager_instance and not self.is_running:
            try:
                self.workflow_manager_instance.save_current_project_state()
                self.status_var.set("Project state saved successfully.")
                logger.info("Project state saved via keyboard shortcut.")
            except Exception as e:
                self.status_var.set("Error saving project state.")
                logger.error(f"Failed to save project state via shortcut: {e}")
        elif self.is_running:
            logger.warning("Attempted to save project state while a task is running. Ignoring.")
        else:
            logger.warning("Attempted to save project state, but workflow manager is not initialized.")

    def clear_output(self):
        """Clears the main code output display."""
        if self.conversation_display and self.conversation_display.winfo_exists():
            self.conversation_display.configure(state="normal")
            self.conversation_display.delete("1.0", "end")
            self.conversation_display.configure(state="disabled")
            logger.info("Code output cleared via keyboard shortcut.")

    def toggle_full_code_view(self, codetextbox: ctk.CTkTextbox, 
                             button: ctk.CTkButton,
                             line_count: int):
        """
        Toggles between limited height and full code view.
        """
        current_text = button.cget("text")
        
        if current_text == "Show Full Code":
            # Expand
            font_line_height = 18 # Approximation for Consolas 11 + padding
            new_height = line_count * font_line_height
            
            # Set a max height to avoid performance issues with huge files
            max_height = self.master.winfo_height() * 0.8 
            if new_height > max_height:
                new_height = int(max_height)

            # But don't make it smaller than the original collapsed height
            if new_height < 300:
                new_height = 300

            codetextbox.configure(height=new_height)
            button.configure(text="Hide Full Code")
        else:
            # Collapse
            codetextbox.configure(height=300)
            button.configure(text="Show Full Code")


    # --- NEW: Command Palette and its actions ---
    def create_command_palette(self):
        """Create a quick command palette overlay"""
        
        # Overlay background
        overlay = ctk.CTkFrame(
            self.master,
            fg_color=("#000000", "#000000"),
            corner_radius=0
        )
        overlay.configure(fg_color=overlay.cget("fg_color") + (0.7,)) # Add alpha
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()
        
        # Command palette window
        palette = ctk.CTkFrame(
            overlay,
            fg_color="#1E1E1E",
            border_width=2,
            border_color="#6366F1",
            corner_radius=10,
            width=600,
            height=400
        )
        palette.place(relx=0.5, rely=0.3, anchor="center")
        
        # Search input
        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            palette,
            placeholder_text="Type a command...",
            textvariable=search_var,
            height=40,
            font=("Segoe UI", 15),
            fg_color="#252526",
            border_width=0
        )
        search_entry.pack(fill="x", padx=10, pady=10)
        search_entry.focus()
        
        # Commands list
        commands_list = [
            ("▶️ Start / Continue Agent", self.handle_start_workflow),
            ("⏹️ Stop Agent", self.handle_stop_workflow),
            ("🗑️ Clear Output", lambda: self.conversation_display.delete("1.0", "end") if self.conversation_display else None),
            ("💾 Export Logs", self._export_logs),
            ("📁 Open Project Folder", self.open_project_folder),
            ("🔑 Change API Key", self._change_api_key_manual),
            ("📊 View Project State", self.view_project_state)
        ]
        
        scrollable = ctk.CTkScrollableFrame(palette, fg_color="transparent")
        scrollable.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        for cmd_text, cmd_func in commands_list:
            btn = ctk.CTkButton(
                scrollable,
                text=cmd_text,
                anchor="w",
                height=35,
                fg_color="transparent",
                hover_color="#313244",
                command=lambda f=cmd_func: [overlay.destroy(), f()]
            )
            btn.pack(fill="x", pady=2)
        
        # Close on Escape or click outside
        overlay.bind("<Escape>", lambda e: overlay.destroy())
        overlay.bind("<Button-1>", lambda e: overlay.destroy())
        palette.bind("<Button-1>", lambda e: "break")  # Don't propagate to overlay

    def open_project_folder(self):
        """Opens the current project directory in the default file explorer."""
        if self.project_root and os.path.isdir(self.project_root):
            try:
                if platform.system() == "Windows":
                    os.startfile(self.project_root)
                elif platform.system() == "Darwin": # macOS
                    subprocess.run(["open", self.project_root])
                else: # Linux
                    subprocess.run(["xdg-open", self.project_root])
            except Exception as e:
                messagebox.showerror("Error", f"Could not open project folder: {e}", parent=self.master)
        else:
            messagebox.showwarning("No Project", "Please select a project directory first.", parent=self.master)

    def view_project_state(self):
        """Displays the current project state JSON in a message box."""
        if self.workflow_manager_instance and self.workflow_manager_instance.project_state:
            state_json = self.workflow_manager_instance.project_state.model_dump_json(indent=2)
            # This might be too large for a messagebox. A dedicated window would be better.
            # For now, we'll show a snippet.
            messagebox.showinfo("Project State", state_json[:2000] + "...", parent=self.master)
        else:
            messagebox.showwarning("No State", "Project state is not available.", parent=self.master)

    def _set_ui_initial_state(self):
        """Disables all interactive UI controls that require a project to be loaded."""
        """
        Sets the initial disabled state for controls before project selection.
        The project selection button itself must remain enabled.
        """
        if self.select_project_button: self.select_project_button.configure(state=NORMAL)
        if self.framework_dropdown: self.framework_dropdown.configure(state=DISABLED)
        if self.new_project_check: self.new_project_check.configure(state=DISABLED)
        # help_label is just a label, no state
        if self.prompt_entry: self.prompt_entry.configure(state=DISABLED)
        if self.send_button: self.send_button.configure(state=DISABLED)
        if self.provider_dropdown: self.provider_dropdown.configure(state=DISABLED)
        if self.model_dropdown: self.model_dropdown.configure(state=DISABLED)
        if self.tars_temp_scale: self.tars_temp_scale.configure(state=DISABLED)
        if self.case_temp_scale: self.case_temp_scale.configure(state=DISABLED)
        if self.change_api_key_button: self.change_api_key_button.configure(state=DISABLED)
        if hasattr(self, 'manage_models_button'):
            self.manage_models_button.configure(state=DISABLED)


    def _set_ui_project_selected_state(self):
        """Enables UI controls after a project directory is selected and basic configs are loaded."""
        """Enables UI controls after a project directory is selected and stage 1 init is done."""
        if self.prompt_entry: self.prompt_entry.configure(state=NORMAL)
        # Framework dropdown enabled only if frameworks are found
        fw_state = "readonly" if self.available_frameworks else "disabled"
        if self.framework_dropdown: self.framework_dropdown.configure(state=fw_state)
        if self.new_project_check: self.new_project_check.configure(state=NORMAL)
        if self.provider_dropdown: self.provider_dropdown.configure(state="readonly")
        if self.browse_files_button: self.browse_files_button.configure(state=NORMAL)

        if self.model_dropdown: self.model_dropdown.configure(state="readonly")
        if self.tars_temp_scale: self.tars_temp_scale.configure(state=NORMAL)
        if self.case_temp_scale: self.case_temp_scale.configure(state=NORMAL)
        if self.change_api_key_button: self.change_api_key_button.configure(state=NORMAL)
        if hasattr(self, 'manage_models_button'):
            self.manage_models_button.configure(state=NORMAL)
        # Send button enabled only after stage 2 init is complete
        if self.send_button: self.send_button.configure(state=DISABLED) # Keep disabled until stage 2 finishes

    def _initialize_core_stage1(self):
        """
        Performs the first stage of core component initialization.

        This stage is non-blocking and safe to run immediately after project selection.
        It initializes managers that read configuration from disk but do not require
        potentially slow or user-interactive setup like loading API keys.
        Initializes non-blocking core components (Memory, Config, FS, CommandExecutor).
        This stage reads configuration and prepares for agent initialization.
        Called after a project directory is selected.
        """
        if not self.project_root:
            logger.error("Stage 1 Init Error: Project directory path is not set.")
            self.status_var.set("Error: Project directory not set.")
            self._set_ui_running_state(False) # Ensure UI is not locked
            return

        self.is_initializing_stage1 = True # Set flag to prevent premature event handling
        # Reset state variables
        self.core_components_initialized = False
        self.workflow_manager_instance = None
        self.agent_manager = None
        self.status_var.set("Initializing (Stage 1)...")
        self.progress_var.set(5) # Show initial progress
        self.master.update_idletasks() # Force UI update

        try:
            # Initialize components that don't require user interaction (like API keys yet)
            self.memory_manager = MemoryManager(self.project_root)
            self.config_manager = ConfigManager() # Uses default plugins path
            self.file_system_manager = FileSystemManager(self.project_root)
            # Pass the UI callback for command confirmation directly
            self.command_executor = CommandExecutor(
                project_root_path=self.project_root,
                confirmation_cb=self._request_confirmation_dialog_from_thread,
                stop_event=self.stop_event_thread
            )

            # --- Load Providers and Models ---
            providers = self.config_manager.get_providers()
            if self.provider_dropdown:
                self.provider_dropdown.configure(values=list(providers.values()))

            # --- Load UI Preferences (Provider & Model) ---
            project_state_model = self.memory_manager.load_project_state()
            saved_provider_id = "all"
            saved_model_id = ""
            if project_state_model and project_state_model.placeholders:
                saved_provider_id = project_state_model.placeholders.get(UI_PREF_PROVIDER, "all")
                saved_model_id = project_state_model.placeholders.get(UI_PREF_MODEL, "")
                logger.info(f"Loaded UI prefs from state: Provider='{saved_provider_id}', Model='{saved_model_id}'")
            else:
                logger.info("Using default provider 'All' (no preferences found in state).")
            
            # --- FIX: Temporarily disconnect callbacks to prevent premature firing ---
            if self.provider_dropdown: self.provider_dropdown.configure(command=None)
            if self.model_dropdown: self.model_dropdown.configure(command=None)
            
            try:
                # Set provider dropdown and trigger model list update
                self.provider_var.set(providers.get(saved_provider_id, "All"))
                self._update_model_list(saved_provider_id)

                # Set the saved model if it's in the newly populated list
                if saved_model_id and any(m['id'] == saved_model_id for m in MODEL_DATA):
                    self.model_var.set(next(m['display'] for m in MODEL_DATA if m['id'] == saved_model_id))
                elif MODEL_DATA:
                    # If saved model not found, default to the first in the list
                    self.model_var.set(MODEL_DATA[0]['display'])
            finally:
                # --- FIX: Reconnect callbacks after programmatic changes ---
                if self.provider_dropdown: self.provider_dropdown.configure(command=self.on_provider_selected)
                if self.model_dropdown: self.model_dropdown.configure(command=self.on_model_selected)

            # --- Load Available Frameworks ---
            self.available_frameworks = self.config_manager.get_available_frameworks()
            if self.framework_dropdown:
                self.framework_dropdown.configure(values=self.available_frameworks)
            if self.available_frameworks:
                # Set default framework if none is selected or current is invalid
                current_fw = self.framework_var.get()
                # Set the initial last_selected_framework
                if self.last_selected_framework is None:
                    if current_fw and current_fw in self.available_frameworks:
                        self.last_selected_framework = current_fw
                    else:
                        self.last_selected_framework = self.available_frameworks[0]
                if not current_fw or current_fw not in self.available_frameworks:
                    self.framework_var.set(self.available_frameworks[0])
                logger.info(f"Found frameworks: {self.available_frameworks}")
                self._set_ui_project_selected_state() # Enable relevant UI controls
            else:
                # No frameworks found - critical error
                self.framework_var.set("")
                logger.error("No framework plugins found in plugins directory.")
                messagebox.showerror("Initialization Error", "No framework plugins found.\nPlease ensure plugins (e.g., 'django') exist in 'src/plugins'.", parent=self.master)
                self.status_var.set("Error: No frameworks found.")
                self._set_ui_initial_state() # Keep UI disabled
                self._set_ui_running_state(False)
                return # Stop initialization

            logger.info("Core components Stage 1 initialized successfully.")
            # --- FIX: Automatically trigger Stage 2 if a model is already selected from state ---
            if self.model_var.get():
                logger.info("Valid model loaded from state. Automatically proceeding to Stage 2 initialization.")
                # Use 'after' to allow the UI to update before starting the next, potentially blocking, stage.
                self.master.after(50, self._initialize_core_stage2)
            elif self.project_root: # Only show this if a project is actually loaded
                self.status_var.set("Project loaded. Please select a model to initialize agents.")

        except (ValueError, RuntimeError, ImportError, FileNotFoundError, NotADirectoryError, Exception) as e:
            logger.exception("Failed to initialize core components (Stage 1).")
            messagebox.showerror("Initialization Error", f"Failed to initialize core components (Stage 1):\n\n{e}\n\nCheck logs for details.", parent=self.master)
            self.core_components_initialized = False
            # Reset instances if initialization failed
            self.memory_manager = None
            self.config_manager = None
            self.file_system_manager = None
            self.command_executor = None
            self.status_var.set("Initialization Error (Stage 1). Check logs.")
            self._set_ui_initial_state()
            self._set_ui_running_state(False)

    def _set_dialog_icon(self, dialog_window: tk.Toplevel):
        """
        Sets the application icon on a given Toplevel window (dialog).
        This ensures consistent branding across all pop-ups.
        """
        try:
            # The self.logo_photo_image is created during main window icon setup.
            # If it exists, we can reuse it for dialogs.
            if self.logo_photo_image and hasattr(dialog_window, 'iconphoto'):
                dialog_window.iconphoto(True, self.logo_photo_image)
        except Exception as e:
            logger.warning(f"Could not set icon on dialog window: {e}")

        finally:
            self.is_initializing_stage1 = False # Unset the flag after setup is complete

    def _initialize_core_stage2(self):
        """
        Performs the second stage of core component initialization.

        This stage initializes components that might require user interaction (like
        prompting for an API key via `AgentManager`) or are dependent on the full
        configuration being loaded. It's called after Stage 1 completes and a
        model has been selected.
        Initializes components that might require user interaction (AgentManager)
        and the main WorkflowManager. Called after Stage 1 completes successfully.
        """
        # Check prerequisites from Stage 1
        if not self.project_root or not self.memory_manager or not self.config_manager or \
           not self.file_system_manager or not self.command_executor:
            logger.error("Stage 2 Init Error: Prerequisites from Stage 1 not met.")
            self.status_var.set("Initialization Error (Stage 2 - Prerequisites missing).")
            self._set_ui_running_state(False)
            return

        self.status_var.set("Initializing agents (Stage 2)...")
        self.progress_var.set(20)
        self.master.update_idletasks()

        try:
            # Check secure storage backend (non-blocking)
            if not check_keyring_backend():
                messagebox.showwarning("Secure Storage Warning",
                                       "Could not verify secure storage (keyring) backend.\n"
                                       "API keys might not be stored securely across sessions.\n"
                                       "See logs or keyring documentation for setup.",
                                       parent=self.master)
            else:
                logger.info("Keyring backend check successful.")

            selected_model_details = self._get_selected_model_details()
            if not selected_model_details:
                raise ValueError("No valid model selected. Cannot initialize agent.")
            self.agent_manager = AgentManager(
                provider_id=selected_model_details['provider'],
                model_id=selected_model_details['id'],
                config_manager=self.config_manager,
                show_input_prompt_cb=self._request_input_dialog_from_thread,
                request_api_key_update_cb=self._request_api_key_update_dialog_from_thread,
                site_url=None,      # Pass site_url, required by signature
                site_title=None     # Pass site_title, required by signature
            )
            self.progress_var.set(25)

            # Initialize WorkflowManager with all dependencies and UI callbacks
            self.workflow_manager_instance = WorkflowManager(
                agent_manager=self.agent_manager,
                memory_manager=self.memory_manager,
                config_manager=self.config_manager,
                file_system_manager=self.file_system_manager,
                command_executor=self.command_executor,
                show_input_prompt_cb=self._request_input_dialog_from_thread,
                show_file_picker_cb=self._request_file_picker_from_thread,
                progress_callback=self.update_progress_safe, # Thread-safe progress update
                show_confirmation_dialog_cb=self._request_confirmation_dialog_from_thread,
                request_command_execution_cb=self._request_command_execution_from_thread, # Pass command exec callback
                show_user_action_prompt_cb=self._request_user_action_dialog_from_thread, # type: ignore
                request_network_retry_cb=self._request_network_retry_dialog_from_thread, # Pass new callback
                request_api_key_update_cb=self._request_api_key_update_dialog_from_thread, # Pass API key update callback
                default_tars_temperature=self.tars_temp_var.get(), # Pass UI temperature
                default_case_temperature=self.case_temp_var.get(),  # Pass UI temperature
                ui_communicator=self.ui_communicator,
                remediation_config=(
                    loaded_state.remediation_config
                    if (loaded_state := self.memory_manager.load_project_state()) and hasattr(loaded_state, 'remediation_config')
                    else None
                )
            )

            
            # --- DEFINITIVE FIX: Explicitly load state into WorkflowManager ---
            self.workflow_manager_instance.load_existing_project()
            # --- DEFINITIVE FIX: Save the newly created state to disk immediately ---
            # This ensures that if the user changes the model before starting, the state file exists.
            if self.workflow_manager_instance.project_state:
                self.memory_manager.save_project_state(self.workflow_manager_instance.project_state)
            
            # ✅ CORRUPTION DETECTION: Check if the loaded state is suspiciously empty
            if self.project_root and self.workflow_manager_instance.project_state:
                state = self.workflow_manager_instance.project_state
                # A simple check for code existence (e.g., manage.py)
                has_code = os.path.exists(os.path.join(self.project_root, "manage.py"))
                state_is_empty = not state.features and not state.registered_apps and not state.defined_models

                if has_code and state_is_empty:
                    logger.error("UI DETECTED POTENTIAL STATE CORRUPTION: Empty state loaded for a project with code.")
                    # Show user-friendly message in UI
                    self.update_progress_safe({
                        'system_message': "🔍 Detected existing project code. Performing initial scan to understand your codebase..."
                    })
                    # Create a temporary Toplevel to get a handle for setting the icon
                    temp_dialog_parent = tk.Toplevel(self.master)
                    temp_dialog_parent.withdraw() # Hide the temporary window
                    response = messagebox.askyesno( # type: ignore
                        "Potential State Corruption",
                        "Warning: The project's saved state appears to be empty, but code files were found.\n\n"
                        "This can happen if the state file was corrupted. Would you like to attempt to restore from the most recent backup?\n\n"
                        "(Choosing 'No' will proceed with the empty state, potentially losing history.)",
                        parent=self.master
                    )
                    if response and self.memory_manager:
                        self._set_dialog_icon(temp_dialog_parent)
                        temp_dialog_parent.destroy()
                        restored = self.memory_manager.restore_from_latest_backup()
                        if restored and restored.features:
                            self.workflow_manager_instance.project_state = restored
                            self.add_message("System", f"Successfully restored {len(restored.features)} features from backup.")
                        else:
                            self.add_message("System", "Could not restore from backup. The project state may be lost.")
                            messagebox.showwarning("Restore Failed", "No valid backup could be found.", parent=self.master)
                    else:
                        # Ensure the temporary window is destroyed if 'No' is clicked
                        temp_dialog_parent.destroy()

            project_name = Path(self.project_root).name # type: ignore
            self.project_path_var.set(f"{project_name} ({self.project_root})")
            logger.info(f"Core components Stage 2 initialized successfully for project: {project_name}")
            self.add_message("System", f"Project '{project_name}' loaded. Framework: {self.framework_var.get()}. Ready for prompts.")

            # Initialization complete
            self.core_components_initialized = True
            self.needs_initialization = False # Workflow manager is created and ready.
            self.status_var.set(f"Project: {project_name} | Ready")
 
            # ✅ FIX: If we can continue, add a helpful message to the user.
            if self.is_continuing_run and self.memory_manager:
                loaded_state = self.memory_manager.load_project_state()
                if loaded_state and loaded_state.current_feature_id and (current_feature := loaded_state.get_feature_by_id(loaded_state.current_feature_id)):
                    self.add_message("System", f"🚀 Project loaded. Press 'Continue' to resume work on '{current_feature.name}'.")
                elif loaded_state and self.workflow_manager_instance.can_continue():
                    self.add_message("System", "Project loaded with features ready to continue. Press 'Continue' to resume work.")
            
            # ✅ FIX: Check for continuable state AFTER all loading and potential restoration is complete.
            self._update_continue_state()
            # This second call ensures the button state is refreshed based on the final `is_continuing_run` value.
            self._set_ui_running_state(False) # This will now correctly set the "Continue" button

        except (ValueError, RuntimeError, ImportError, AuthenticationError, RateLimitError, Exception) as e:
            # Handle errors during AgentManager or WorkflowManager initialization
            logger.exception("Failed to initialize core components (Stage 2).")
            messagebox.showerror("Initialization Error", f"Failed to initialize agents or workflow (Stage 2):\n\n{e}\n\nCheck API keys or logs.", parent=self.master)
            self.core_components_initialized = False
            self.workflow_manager_instance = None
            self.agent_manager = None
            self.status_var.set("Initialization Error (Stage 2). Check logs.") # type: ignore
            self._set_ui_initial_state()
        finally:
            # The logic has been moved into the `try` block to ensure it only runs on successful initialization.
            # The `except` block now handles setting the UI state on failure.
            pass

    def select_project_directory(self):
        """
        Handles the 'Select Project Directory' menu action. Prompts the user to
        choose a folder, then kicks off the two-stage core initialization process.
        """
        """Handles the 'Select Project Directory' menu action."""
        if self.is_running:
            messagebox.showwarning("Busy", "Cannot change project while a task is running.", parent=self.master)
            return

        # Ask user to select a directory
        directory = filedialog.askdirectory(
            title="Select Project Root Directory",
            mustexist=True, # Ensure the selected directory exists
            parent=self.master
        )

        if directory:
            logger.info(f"Project directory selected: {directory}")
            self.project_root = directory # Store the selected path
            self.project_path_var.set(f"{Path(directory).name}")

            # Auto-detect if it's an existing project and update the checkbox
            project_state_path = Path(directory) / ".vebgen" / "project_state.json" # type: ignore
            is_existing = project_state_path.exists()
            self.is_new_project.set(not is_existing)
            logger.info(f"Project auto-detected as {'existing' if is_existing else 'new'}. 'New Project' checkbox set to {not is_existing}.")
            # CRITICAL FIX: Reset continue state to allow prompt entry for new/re-loaded projects.
            self.is_continuing_run = False
            # --- Clear previous displays and reset progress ---
            # Clear the updates display (CTkScrollableFrame) by destroying its children
            # Destroy the entire notebook and recreate it. This is the safest way
            # to ensure all child widgets and their pending `after` jobs are gone.
            if self.notebook and self.notebook.winfo_exists():
                self.notebook.destroy()
            self._create_notebook(self.main_content_frame) # type: ignore
            self.progress_var.set(0)
            self.status_var.set("Initializing...")
            self._set_ui_running_state(True) # Lock UI during initialization
            self.is_continuing_run = False # Reset continue flag on new project selection
            self.needs_initialization = True # Flag that next run needs full initialization

            # --- FIX: Run the entire initialization in a background thread ---
            # This prevents the UI from freezing during agent setup or key prompts.
            init_thread = threading.Thread(target=self._run_initialization_thread, daemon=True)
            init_thread.start()
            # --- END FIX ---
        else:
            logger.info("Project directory selection cancelled.")
            # Update status only if core components weren't already initialized
            if not self.project_root:
                self.status_var.set("Project selection cancelled. Please select a directory.")

    def _run_initialization_thread(self):
        """
        Target for a background thread to run the entire two-stage initialization
        process without blocking the UI.
        """
        try:
            # Stage 1 is quick and reads configs.
            self._initialize_core_stage1()
            # Stage 2 can be slow (API key prompts, agent init) and is now safely off the main thread.
            self._initialize_core_stage2()
        except Exception as e:
            logger.exception("An error occurred during the background initialization thread.")
            self.update_progress_safe({"error": f"Initialization failed: {e}"})
        finally:
            # Ensure the UI is unlocked, even if initialization fails.
            self.update_progress_safe({"finalize": True, "success": self.core_components_initialized})

    def _update_model_list(self, provider_id: str):
        """Helper to update the model dropdown based on the selected provider."""
        global MODEL_DATA
        self.model_var.set("") # Clear previous selection
        MODEL_DATA = self.config_manager.get_models_for_provider(provider_id)
        model_display_names = [m['display'] for m in MODEL_DATA]
        self.model_dropdown.configure(values=model_display_names)

        if model_display_names:
            self.model_var.set(model_display_names[0])
            self.model_dropdown.configure(state="readonly")
        else: # No models for this provider
            self.model_var.set("")
            self.model_dropdown.configure(state=DISABLED)

        # Update the model badge in the status bar
        if self.model_badge_label:
            self.model_badge_label.configure(text=f"🤖 {self.model_var.get().split(' - ')[0]}")

    def _get_selected_provider_id(self) -> str:
        """Helper to get the internal ID of the currently selected provider from its display name."""
        """Gets the ID of the currently selected provider."""
        selected_provider_display = self.provider_var.get()
        if not self.config_manager: return "all"
        # Find the provider ID from the display name
        for pid, data in self.config_manager.providers_config.items():
            if data.get("display_name") == selected_provider_display:
                return pid
        return "all" # Default

    def _get_selected_model_details(self) -> Optional[Dict[str, str]]:
        """Helper to get the full details dict for the currently selected model."""
        """Gets the details dictionary {'id': ..., 'provider': ...} of the currently selected model."""
        selected_model_display = self.model_var.get()
        for model in MODEL_DATA:
            if model['display'] == selected_model_display:
                return model
        return None

    # --- Start of Part 2 ---

    def on_framework_selected(self, event=None):
        """
        Callback for when the framework dropdown selection changes.
        It shows a "Coming Soon" message for unsupported frameworks and triggers
        re-initialization if a valid framework is chosen.
        """
        """Callback when the framework dropdown selection changes."""
        selected_framework = self.framework_var.get()

        if selected_framework in ["flask", "node", "react"]:
            messagebox.showinfo(
                "Coming Soon", # type: ignore
                # This is a simple dialog, but we can still try to set the icon
                # by creating a temporary parent and setting its icon.
                # However, for a simple info box, this might be overkill. Let's focus on the main ones.
                f"Support for the '{selected_framework}' framework is coming soon!",
                parent=self.master
            )
            # Revert to the last valid selection
            if self.last_selected_framework and self.last_selected_framework in self.available_frameworks:
                self.framework_var.set(self.last_selected_framework)
            elif self.available_frameworks:
                # Fallback to the first available framework if last selection is somehow invalid
                self.framework_var.set(self.available_frameworks[0])
            else:
                # No frameworks available, clear selection
                self.framework_var.set("")
            return # Stop further processing for the invalid selection

        # If the selection is valid, update the last selected framework
        self.last_selected_framework = selected_framework

        if self.core_components_initialized and not self.is_running and self.project_root:
            self.on_model_selected() # Trigger re-initialization with the new valid framework


    def on_provider_selected(self, event=None):
        """Callback for when the API provider dropdown selection changes."""
        """Callback when the API provider dropdown selection changes."""
        if not self.config_manager or self.is_running:
            return
        provider_id = self._get_selected_provider_id()
        logger.info(f"Provider selection changed to: {provider_id}")
        self._update_model_list(provider_id)

    def on_model_selected(self, event=None):
        """
        Callback for when the LLM model selection changes.
        This is a critical event that saves the user's preference and triggers
        the re-initialization of the `AgentManager` and `WorkflowManager`.
        """
        """
        Callback when a model selection changes.
        Saves the preference and triggers agent/workflow initialization or re-initialization.
        """
        # --- DEFINITIVE FIX: This guard clause prevents this method from running during the automatic setup process. ---
        if self.is_running:
            logger.warning("Attempted to change model while task is running. Ignoring.")
            return

        selected_model_details = self._get_selected_model_details()
        if not selected_model_details:
            # This can happen when switching providers, before a model in the new list is selected.
            # It's not an error, just an intermediate state.
            logger.debug("No model selected yet for the current provider.")
            if self.send_button: self.send_button.configure(state=DISABLED)
            return

        selected_provider_id = selected_model_details['provider']
        selected_model_id = selected_model_details['id']
        logger.info(f"Model selection changed: Provider='{selected_provider_id}', Model='{selected_model_id}'")

        # --- Save Preferences ---
        if self.memory_manager:
            project_state_model = self.memory_manager.load_project_state()
            if project_state_model:
                if project_state_model.placeholders is None:
                    project_state_model.placeholders = {}
                project_state_model.placeholders[UI_PREF_PROVIDER] = selected_provider_id
                project_state_model.placeholders[UI_PREF_MODEL] = selected_model_id
                try:
                    self.memory_manager.save_project_state(project_state_model)
                    logger.info("Saved updated model preferences to project state.")
                except Exception as e:
                    logger.error(f"Failed to save model preferences to project state: {e}")
            else:
                logger.warning("Cannot save model preferences: Project state not loaded/available yet.")

        # --- Re-initialize Agents and Workflow ---
        if self.agent_manager:
            self.status_var.set("Re-initializing agents with new models...")
            # Update model badge in status bar
            if self.model_badge_label:
                self.model_badge_label.configure(text=f"🤖 {selected_model_details['display'].split(' - ')[0]}")

            self._set_ui_running_state(True) # Lock UI during re-initialization
            self.master.update_idletasks()
            try:
                # Tell AgentManager to use the new models (this might prompt for keys again if needed)
                self.agent_manager.reinitialize_agent(selected_provider_id, selected_model_id)

                # Recreate WorkflowManager instance with the updated AgentManager
                # Safely load the project state once to get the remediation config
                loaded_state = self.memory_manager.load_project_state()
                remediation_config_from_state = None
                if loaded_state and hasattr(loaded_state, 'remediation_config'):
                    remediation_config_from_state = loaded_state.remediation_config

                if self.memory_manager and self.config_manager and self.file_system_manager and self.command_executor:
                    self.workflow_manager_instance = WorkflowManager(
                        agent_manager=self.agent_manager,
                        memory_manager=self.memory_manager,
                        config_manager=self.config_manager,
                        file_system_manager=self.file_system_manager,
                        command_executor=self.command_executor,
                        show_input_prompt_cb=self._request_input_dialog_from_thread,
                        show_file_picker_cb=self._request_file_picker_from_thread,
                        progress_callback=self.update_progress_safe,
                        show_confirmation_dialog_cb=self._request_confirmation_dialog_from_thread,
                        request_command_execution_cb=self._request_command_execution_from_thread,
                        show_user_action_prompt_cb=self._request_user_action_dialog_from_thread, # type: ignore
                        request_network_retry_cb=self._request_network_retry_dialog_from_thread,
                        request_api_key_update_cb=self._request_api_key_update_dialog_from_thread,
                        default_tars_temperature=self.tars_temp_var.get(),
                        default_case_temperature=self.case_temp_var.get(),  # Pass UI temperature
                        remediation_config=remediation_config_from_state,
                        ui_communicator=self.ui_communicator
                    )
                    # --- DEFINITIVE FIX: Reload state into the newly created instance ---
                    self.workflow_manager_instance.load_existing_project()
                    # --- END FIX ---

                    # self.needs_initialization = True # This was causing a state conflict. It's correctly set to False after Stage 2 init.
                    self.status_var.set("Agent re-initialized. Ready.")
                    self.add_message("System", f"Agent re-initialized. Provider: {selected_provider_id}, Model: {selected_model_id}")
                    
                    # ✅ FIX: Unlock UI after successful re-initialization
                    self._set_ui_running_state(False)
                else:
                    # This shouldn't happen if core components were initialized correctly before
                    raise RuntimeError("Core components missing, cannot recreate WorkflowManager.")
            except (ValueError, RuntimeError, AuthenticationError, RateLimitError, Exception) as e:
                # Handle errors during re-initialization (e.g., invalid API key for new model)
                logger.error(f"Failed to re-initialize agents/workflow after model change: {e}") # type: ignore
                # Create a temporary Toplevel to set the icon on the error dialog
                temp_dialog_parent = tk.Toplevel(self.master)
                temp_dialog_parent.withdraw()
                messagebox.showerror("Agent Error", f"Failed to re-initialize agents:\n{e}\n\nCheck keys/models or restart.", parent=self.master)
                self.status_var.set("Agent re-initialization failed.") # type: ignore
                # Unlock UI on failure
                self._set_ui_running_state(False)
                if self.send_button: self.send_button.configure(state=DISABLED) # Disable start if agents failed
        else:
            # This is the first time a model is selected by the user, trigger Stage 2 initialization
            logger.info("First user model selection. Triggering core components Stage 2 initialization.")
            self._initialize_core_stage2()

    def handle_start_stop_continue(self, event=None):
        """
        Central handler for the main action button.
        Dispatches to start, stop, or continue the workflow based on current state.
        """
        if self.is_running:
            self.handle_stop_workflow()
        else:
            self.handle_start_workflow()

    def handle_stop_workflow(self):
        """
        Handles the 'Stop' button click. Signals the backend workflow to stop gracefully.
        """
        if not self.is_running or not self.workflow_manager_instance:
            return

        logger.info("Stop button clicked. Requesting graceful shutdown of workflow...")
        self.status_var.set("Stopping workflow...")
        self.workflow_manager_instance.request_stop()
        # The UI will be fully unlocked and updated in _finalize_run_ui when the thread confirms exit.

    def handle_start_workflow(self, event=None):
        """
        Handles the 'Start' button click or Enter key press in the prompt entry.
        It validates all necessary inputs and configurations are ready, then starts
        the appropriate workflow (initial or subsequent) in a background thread.
        """
        """
        Handles the 'Start' or 'Continue' button click.
        Validates input and starts the appropriate workflow in a background thread.
        """
        if self.is_running:
            messagebox.showwarning("Busy", "A task is already running. Please wait.", parent=self.master)
            return

        # --- Input Validation ---
        user_prompt = self.prompt_entry.get().strip() if self.prompt_entry else ""
        # --- FIX: Explicitly check the button's purpose ---
        # This makes the logic robust against any race conditions with the is_continuing_run flag.
        is_continue_button_press = self.send_button.cget("text") == "▶️ Continue"
 
        # A prompt is NOT required if we are continuing a run.
        if not user_prompt and not self.is_continuing_run and not is_continue_button_press:
            messagebox.showwarning("Input Required", "Please enter a prompt describing your goal.", parent=self.master)
            return
        if user_prompt and self.is_continuing_run:
            logger.warning("A new prompt was entered, but continuing a previous run. The new prompt will be ignored for now.")

        selected_framework = self.framework_var.get()
        if not selected_framework:
            messagebox.showwarning("Framework Required", "Please select a framework.", parent=self.master)
            return

        # Check if core components are ready
        if not self.core_components_initialized or not self.workflow_manager_instance or not self.agent_manager:
            messagebox.showerror("Initialization Error", "Core components not ready. Please select a project directory and ensure agents initialize correctly.", parent=self.master)
            return
        if not self.agent_manager or not self.agent_manager.agent:
            messagebox.showerror("Agent Error", "Agents not initialized. Check API keys/models or restart.", parent=self.master)
            logger.error("Attempted run but agents not initialized.")
            # Attempt re-initialization if agents are missing
            self.status_var.set("Re-initializing agents (Stage 2)...")
            self.master.after(50, self._initialize_core_stage2)
            return

        # --- Start Workflow ---
        self.is_running = True # Set running flag
        if user_prompt:
            self.add_message("User", user_prompt) # Add user prompt to conversation display
            if self.prompt_entry: self.prompt_entry.delete(0, END) # Clear prompt entry
        else:
            self.add_message("System", "Continuing previous workflow...")
 
        self._set_ui_running_state(True) # Disable UI controls
 
        thread_target = None # Function to run in the background thread
        thread_args: Tuple = () # Arguments for the thread target
 
        # --- DEFINITIVE FIX: Restructure logic to prioritize the 'continue' state ---
        if is_continue_button_press:
            # If the UI is in a "Continue" state, ALWAYS choose the continue path.
            logger.info("Continuing previously stopped workflow based on button text.")
            thread_target = self._run_new_feature_thread
            thread_args = ("",) # Pass an empty prompt to signal continuation
        elif self.is_new_project.get() and self.project_root:
            # If not continuing, check if the "New Project" checkbox is ticked.
            # This is the most reliable way to know if we should run the initial setup workflow.
            logger.info(f"Starting initial workflow run for new project. Prompt: '{user_prompt[:100]}...'")
            thread_target = self._run_initial_workflow_thread
            thread_args = (user_prompt, selected_framework, True) # Pass True for is_new_project
            # After starting the initial run, this is no longer a "new" project for subsequent prompts.
            self.is_new_project.set(False)
        else:
            # If not continuing and not a new project, it must be a subsequent new feature request.
            logger.info(f"Handling subsequent prompt as new feature request: '{user_prompt[:100]}...'") # type: ignore
            thread_target = self._run_new_feature_thread
            thread_args = (user_prompt,)
        # --- END FIX ---

        # Start the background thread
        if thread_target:
            logger.debug(f"Starting background thread for target: {thread_target.__name__}")
            thread = threading.Thread(target=thread_target, args=thread_args, daemon=True)
            thread.start()
        else:
            # Should not happen if logic above is correct
            self.needs_initialization = False # Reset flag after starting initial run
            self.is_continuing_run = False # Reset continue flag
            logger.error("Could not determine workflow thread target.")
            self.update_progress_safe({"error": "Internal error: Could not determine workflow action."})
            self._finalize_run_ui(False) # Unlock UI on error

    def _set_ui_running_state(self, running: bool):
        """
        Centralized method to enable or disable all interactive UI elements.
        This is used to "lock" the UI while a background workflow is running
        to prevent conflicting user actions.
        """
        """Helper method to enable/disable UI elements based on workflow running state."""
        new_state = DISABLED if running else NORMAL
        readonly_state = "disabled" if running else "readonly" # For Comboboxes
        cursor = "" # Change cursor to indicate busy state

        try:
            # --- Animation Control ---
            if running:
                self._start_animation() # Start animation
            else:
                self._stop_animation() # Stop animation

            # --- MODIFIED: Dynamic Send/Stop/Continue Button ---
            if self.send_button and self.send_button.winfo_exists():
                if running:
                    self.send_button.configure(text="⏹️ Stop", state=NORMAL, fg_color="#E81123", hover_color="#C2101F")
                elif self.is_continuing_run:
                    # --- DEFINITIVE FIX: Prioritize the 'Continue' state ---
                    self.send_button.configure(text="▶️ Continue", state=NORMAL, fg_color="#F7630C", hover_color="#D9530A")
                elif self.core_components_initialized:
                    self.send_button.configure(text="▶️ Start", state=NORMAL, fg_color="#0078D4", hover_color="#0098FF")
                else:
                    self.send_button.configure(text="▶️ Start", state=DISABLED)

            # Prompt entry should be disabled if running or if we are in a 'continue' state
            if self.prompt_entry and self.prompt_entry.winfo_exists():
                if running or self.is_continuing_run:
                    self.prompt_entry.configure(state=DISABLED)
                # --- FIX: Explicitly enable the prompt if not running and not in continue mode ---
                elif not self.is_continuing_run:
                    self.prompt_entry.configure(state=NORMAL)

            # Enable/disable framework selection (allow changing only when not running)
            fw_state = readonly_state if self.available_frameworks and not running else "disabled"
            if self.framework_dropdown and self.framework_dropdown.winfo_exists() and not self.is_continuing_run:
                self.framework_dropdown.configure(state=fw_state)

            # Enable/disable New Project checkbox and help icon
            if self.new_project_check and self.new_project_check.winfo_exists():
                self.new_project_check.configure(state=new_state)
            if self.help_label and self.help_label.winfo_exists():
                # Help icon state follows the checkbox state
                self.help_label.configure(state=new_state)
            # Enable/disable provider/model selection
            if self.provider_dropdown and self.provider_dropdown.winfo_exists():
                self.provider_dropdown.configure(state=readonly_state)
            if self.model_dropdown and self.model_dropdown.winfo_exists(): self.model_dropdown.configure(state=readonly_state)
            if self.tars_temp_scale and self.tars_temp_scale.winfo_exists(): self.tars_temp_scale.configure(state=new_state)
            if self.change_api_key_button and self.change_api_key_button.winfo_exists(): self.change_api_key_button.configure(state=new_state)
            if self.case_temp_scale and self.case_temp_scale.winfo_exists(): self.case_temp_scale.configure(state=new_state)
            if self.select_project_button and self.select_project_button.winfo_exists(): self.select_project_button.configure(state=new_state)

            # Manage models button
            if hasattr(self, 'manage_models_button') and self.manage_models_button.winfo_exists():
                self.manage_models_button.configure(state=new_state)

            # Set cursor for the main window
            if self.master.winfo_exists():
                self.master.config(cursor=self.default_cursor_spec)

        except tk.TclError as e:
            # Catch potential errors if widgets are destroyed unexpectedly
            logger.warning(f"TclError setting UI running state: {e}")
        except Exception as e:
            logger.error(f"Unexpected error setting UI running state: {e}")

        # Update status bar when starting a run
        if running:
            self.progress_var.set(0) # Reset progress bar
            self.status_var.set("Workflow starting...")

    def _start_animation(self):
        """Starts the 'thinking' animation in the UI."""
        """Starts the thinking animation."""
        if self.animation_job is None:
            self._animation_step = 0
            self._animate()

    def _stop_animation(self):
        """Stops the 'thinking' animation."""
        """Stops the thinking animation."""
        if self.animation_job is not None:
            self.master.after_cancel(self.animation_job)
            self.animation_job = None
        if self.animation_label:
            self.animation_label.configure(text="")

    def _animate(self):
        """Cycles through the animation frames to create the 'thinking' effect."""
        """Cycles through the animation frames."""
        frames = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]
        if self.animation_label:
            self.animation_label.configure(text=frames[self._animation_step])
        self._animation_step = (self._animation_step + 1) % len(frames)
        self.animation_job = self.master.after(100, self._animate)

    def _start_timer(self):
        """Starts the elapsed time counter in the status bar."""
        if self.timer_job:
            self.master.after_cancel(self.timer_job)
        self.start_time = time.monotonic()
        self._update_timer()

    def _stop_timer(self):
        """Stops the elapsed time counter."""
        if self.timer_job:
            self.master.after_cancel(self.timer_job)
            self.timer_job = None

    def _update_timer(self):
        """Updates the elapsed time label every second."""
        if self.is_running and self.start_time and self.time_label:
            elapsed = time.monotonic() - self.start_time
            self.time_label.configure(text=f"⏱️ {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
            self.timer_job = self.master.after(1000, self._update_timer)

    def _run_initial_workflow_thread(self, initial_prompt: str, framework: str, is_new_project: bool):
        """
        Target function for the background thread to run the initial project setup
        and the first adaptive workflow.
        """
        success = False
        run_completed = False
        try:
            if self.workflow_manager_instance and self.project_root:
                logger.info("Background thread: Starting project initialization and adaptive workflow...")

                # The new initialize_project now handles the entire initial workflow run.
                asyncio.run(self.workflow_manager_instance.initialize_project(
                    project_root=self.project_root,
                    framework=framework,
                    initial_prompt=initial_prompt,
                    is_new_project=is_new_project
                ))

                run_completed = True # Mark as completed if no exceptions occurred
                logger.info("Background thread: Initial workflow run finished successfully.")

                # A simple success check for the adaptive workflow.
                # The workflow itself reports detailed progress and errors to the UI.
                success = True 
            else:
                logger.error("WorkflowManager instance or project root not available for initial run.")
                self.update_progress_safe({"issue": "WorkflowManager not initialized or no project selected."})
        except InterruptedError as e:
            logger.warning(f"Initial workflow cancelled by user: {e}")
            self.update_progress_safe({"system_message": "⏸️ You asked me to pause—waiting for your next action.\nPlease click 'Continue' if you’d like to resume!"})
            success = False
        except (RateLimitError, AuthenticationError) as api_err:
            logger.error(f"API Error during initial workflow: {api_err}")
            self.update_progress_safe({"issue": f"API Communication Issue: {api_err}"})
            success = False
        except Exception as e:
            logger.exception("An error occurred during the initial WorkflowManager run.")
            self.update_progress_safe({"issue": f"Workflow encountered an issue: {e}"})
            success = False
        finally:
            logger.debug("Background thread: Putting finalize message on UI queue.")
            # Pass a 'stopped' flag if the exception was an interruption
            was_stopped = isinstance(sys.exc_info()[1], InterruptedError)
            self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"finalize": True, "success": success and run_completed, "stopped": was_stopped}))

    def _run_new_feature_thread(self, prompt: str):
        """
        Target function for the background thread to handle a subsequent prompt
        by running the adaptive workflow.
        """
        success = False
        run_completed = False
        try: # --- FIX: Simplified logic to always use handle_new_prompt ---
            if self.workflow_manager_instance:
                logger.info(f"Background thread: Calling handle_new_prompt with: '{prompt[:50]}...'")
                # handle_new_prompt is smart enough to know whether to start a new feature
                # (if prompt is not empty) or continue an existing one (if prompt is empty).
                asyncio.run(self.workflow_manager_instance.handle_new_prompt(prompt))

                run_completed = True
                logger.info("Background thread: New adaptive workflow run finished.")

                # Simple success check, as the workflow itself reports errors to UI.
                success = True
            else: # --- END FIX ---
                logger.error("WorkflowManager instance or project root not available for new feature run.")
                self.update_progress_safe({"issue": "WorkflowManager not initialized or project not selected."})

        except InterruptedError as e:
            logger.warning(f"New feature workflow cancelled by user: {e}")
            self.update_progress_safe({"system_message": "⏸️ You asked me to pause—waiting for your next action.\nPlease click 'Continue' if you’d like to resume!"})
            success = False
        except (RateLimitError, AuthenticationError) as api_err:
            logger.error(f"API Error during new feature workflow: {api_err}")
            self.update_progress_safe({"issue": f"API Communication Issue: {api_err}"})
            success = False
        except Exception as e:
            logger.exception("An error occurred during the new feature WorkflowManager run.")
            self.update_progress_safe({"issue": f"Workflow encountered an issue: {e}"})
            success = False
        finally:
            logger.debug("Background thread: Putting finalize message on UI queue.")
            # Pass a 'stopped' flag if the exception was an interruption
            was_stopped = isinstance(sys.exc_info()[1], InterruptedError)
            self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"finalize": True, "success": success and run_completed, "stopped": was_stopped}))

    def _update_continue_state(self):
        """Checks the project state and updates the UI's continue flag and status messages."""
        # --- DEFINITIVE FIX: Query the WorkflowManager directly for the authoritative state ---
        if not self.workflow_manager_instance:
            self.is_continuing_run = False
            return

        continuable_feature = self.workflow_manager_instance.can_continue()

        if continuable_feature:
            self.is_continuing_run = True
            logger.info(f"Project has an in-progress feature ('{continuable_feature.name}'). Setting UI to continue.")
            self.status_var.set(f"Project loaded. Ready to continue feature: '{continuable_feature.name}'.")
        else:
            self.is_continuing_run = False
            # No need to log here, as this is the default state.
        # --- END FIX ---
    def _finalize_run_ui(self, success: bool, stopped: bool = False):
        """
        Updates all UI elements after a background workflow run completes,
        either successfully or with an error. This is always called on the main UI thread.
        """
        logger.debug(f"Finalizing run UI. Success: {success}, Stopped: {stopped}")
        self.is_running = False # Reset running flag

        self._update_continue_state()

        self._set_ui_running_state(False) # Re-enable UI controls

        # Update status bar message based on success/failure
        project_name = Path(self.project_root).name if self.project_root else "No Project"
        framework_name = self.framework_var.get() # type: ignore

        # --- FIX: Handle the 'stopped' state explicitly ---
        if stopped:
            # The 'continue' message is already set by _update_continue_state, which is what we want.
            final_status = self.status_var.get()
            logger.info(f"Workflow stopped by user. UI updated. Status: {final_status}")
            self.status_var.set(final_status)
            return # Exit early to avoid overwriting the status

        if success:
            final_status = f"Project: {project_name} | Framework: {framework_name} | Workflow finished successfully."
        elif self.is_continuing_run:
            # If we can continue, the status is already set by _update_continue_state
            final_status = self.status_var.get()
        else: # Not success and not continuable
            current_status = self.status_var.get()
            if "Issue:" not in current_status and "Cancelled" not in current_status:
                final_status = f"Project: {project_name} | Framework: {framework_name} | Workflow completed with issues."
            else:
                final_status = current_status
        self.status_var.set(final_status)
        logger.info(f"Workflow finalized. UI updated. Final Status: {final_status}")

    def add_message(self, sender: str, message: str):
        """
        A public, thread-safe method to add a message to the UI displays.
        It determines the correct message type and puts it on the UI queue
        for processing.
        """
        """
        Adds a message to the UI displays (Updates and Conversation) via the thread-safe queue.
        This is the public method to be called from anywhere (including background threads).

        Args:
            sender: The source of the message (e.g., "System", "User", "TARS", "CASE", "CMD").
            message: The message content string.
        """
        message_str = str(message) if message is not None else "" # Ensure message is a string
        # Determine the appropriate update type based on the sender
        if sender.lower() in ("tars", "case"):
            # ✅ NEW: Agent thoughts go to Updates/Logs, code goes to Code Output
            self.add_agent_thought_to_logs(sender, message_str)
        elif sender.upper() == "CMD":
            # Commands go to Updates/Logs
            self.add_log_message("INFO", "CMD", message_str)
        else:
            # System messages go to Updates/Logs
            self.add_log_message("INFO", sender, message_str)

    def format_action_card(self, action: str, parameters: Dict[str, Any]) -> str:
        """
        Formats an agent's action and parameters into a compact, readable card.
        
        Example output:
            ⚡ Running: python manage.py startapp calculator
            📄 Reading calculator/admin.py
            ✏️ Updating 🐍 calculator/models.py 
        """
        icon = ACTION_ICONS.get(action, "⚙️")
        readable_action = action.replace("_", " ").title()
        
        # Handle different parameter types
        if "file_path" in parameters:
            path = parameters["file_path"]
            ext = path.split(".")[-1] if "." in path else ""
            file_icon = self.FILE_ICONS.get(ext.lower(), "📄")
            return f"{icon} {readable_action} {file_icon} {path}"
        elif "command" in parameters:
            cmd = parameters["command"]
            return f"🛡️ Running (Sandbox): {cmd}"
        elif "prompt" in parameters:
            prompt = parameters["prompt"]
            return f"{icon} {readable_action}: {prompt[:60]}..."
        elif "reason" in parameters:
            return f"{icon} {readable_action}: {parameters['reason'][:50]}..."
        else:
            return f"{icon} {readable_action}"


    def add_agent_thought_to_logs(self, agent_name: str, message: str):
        '''Parse agent message: thoughts to Updates/Logs, code to Code Output'''
        # Parse for Thought + Action from the agent's plaintext message
        thought_match = re.search(r'Thought:\s*(.*?)(?=\nAction:|$)', message, re.DOTALL)
        action_match = re.search(r'Action:\s*(\w+)', message)
        params_match = re.search(r'Parameters:\s*(\{.*?\})', message, re.DOTALL)

        # Display Thought (if exists)
        if thought_match:
            # ✅ FIX #1: Clean up the thought text before displaying
            thought = thought_match.group(1).strip()
            thought = thought.replace("Thought:", "").strip()
            thought = re.sub(r'^[🤔💭🧠🔧✅]\s*', '', thought)
            formatted_thought = f"💭 {thought}"
            self.add_log_message("INFO", agent_name, formatted_thought)

        # Display Action (if exists)
        if action_match and params_match:
            action = action_match.group(1)
            try: # ✅ FIX #2: Only display the formatted action, not the raw text
                parameters = ast.literal_eval(params_match.group(1)) # type: ignore
                formatted_action = self.format_action_card(action, parameters)
                self.add_log_message("INFO", agent_name, formatted_action)
                return  # Exit here to prevent logging the raw message
            except Exception as e:
                logger.warning(f"Failed to parse action parameters: {e}")
                self.add_log_message("INFO", agent_name, f"⚙️ {action.replace('_', ' ').title()}")
                return  # Exit here as well
        elif not thought_match:
            # No thought or action, display as-is
            self.add_log_message("INFO", agent_name, message)

    def add_log_message(self, level: str, source: str, message: str, details: Optional[Dict] = None):
        """
        Adds a structured and colored log message to the 'Updates / Logs' display.
        This method is designed to be called from the main UI thread.
        """
        if not self.updates_display or not self.updates_display.winfo_exists(): # type: ignore
            return
        
        log_entry_frame = ctk.CTkFrame(self.updates_display, fg_color="transparent")
        
        # --- REFACTORED: Create a single, formatted log line ---
        timestamp = f"[{datetime.now().strftime('%H:%M:%S')}]"
        
        # Main log line
        main_line_frame = ctk.CTkFrame(log_entry_frame, fg_color="transparent")
        main_line_frame.pack(fill=X)

        # --- FIX: Determine the correct source *before* selecting the icon ---
        # Auto-detect if this is a sandbox message based on keywords.
        sandbox_keywords = ["virtual environment", "installing requirements", "running command", "executing", "sandbox"]
        if any(keyword in message.lower() for keyword in sandbox_keywords):
            source = "Sandbox"

        # Use a single label for the main log message for better alignment and wrapping
        full_message = f"{timestamp} " # type: ignore
        if source:
            # Now that the source is corrected, select the appropriate icon.
            if source == "Sandbox":
                icon = "🛡️"
            else:
                icon = "⚙️" if source == "System" else ("🤖" if source in ("TARS", "CASE") else "👤")
            full_message += f"{icon} {source} · "
        # --- END FIX ---

        full_message += message.strip() # type: ignore

        message_label = ctk.CTkLabel(main_line_frame, text=full_message, text_color="#DCE4EE", font=("Segoe UI", 12), wraplength=self.updates_display.winfo_width() - 50, justify=LEFT, anchor="w")
        message_label.pack(fill=X, expand=True)

        # --- NEW: Collapsible Action Details ---
        if details:
            details_frame = ctk.CTkFrame(log_entry_frame, fg_color="#1E1E2E", corner_radius=4)
            # Initially hidden

            def toggle_details():
                if details_frame.winfo_viewable():
                    details_frame.pack_forget()
                    toggle_button.configure(text="▶ Show details")
                else:
                    details_frame.pack(fill=X, padx=(20, 0), pady=5, ipady=5)
                    toggle_button.configure(text="▼ Hide details")

            toggle_button = ctk.CTkButton(main_line_frame, text="▶ Show details", command=toggle_details, fg_color="transparent", text_color="#808080", hover=False, width=20, font=("Segoe UI", 10))
            toggle_button.pack(side=LEFT, padx=(20, 0))

            # Populate the details frame
            for key, value in details.items():
                detail_line = ctk.CTkLabel(details_frame, text=f"│ {key.title():<10}: {value}", font=("Consolas", 11), anchor="w")
                detail_line.pack(fill=X, padx=10)

        log_entry_frame.pack(fill=X, padx=10, pady=(2, 2))
        
        # Scroll to the bottom to show the latest message
        self._scroll_updates_to_bottom()

    def _add_message_to_widget(self, widget: Optional[ctk.CTkTextbox], sender: str, message: str, tag: Optional[str] = None):
        """
        Internal method to add a formatted message directly to a CTkTextbox widget.
        This method MUST be called only from the UI thread.
        """
        """
        Internal method to add a formatted message directly to a ScrolledText widget.
        This method MUST be called only from the UI thread (via _process_ui_queue).

        Args:
            widget: The CTkTextbox widget to add the message to.
            sender: The source of the message.
            message: The message content.
            tag: An optional specific tag to apply (overrides default logic).
        """
        if not widget or not widget.winfo_exists():
            # logger.debug(f"Skipping message add, widget does not exist: {widget}")
            return # Widget might have been destroyed

        try:
            widget.configure(state=NORMAL) # Enable widget for modification

            # Determine sender tag for formatting the sender name
            sender_tag = sender.lower() if sender.lower() in self.text_tags else "agent_name"
            widget.insert(END, f"{sender}: ", sender_tag)

            # Determine message tag for formatting the message content
            message_tag = tag if tag and tag in self.text_tags else "default"
            # Auto-detect tag based on content if no specific tag is provided
            if tag is None:
                msg_lower = message.lower()
                if "error" in msg_lower or "failed" in msg_lower: message_tag = "error"
                elif "warning" in msg_lower or "skipping" in msg_lower: message_tag = "warning"
                elif "success" in msg_lower or "completed" in msg_lower or "merged" in msg_lower or "passed" in msg_lower: message_tag = "success"
                elif "action" in msg_lower or "running command" in msg_lower or "creating directory" in msg_lower or "writing file" in msg_lower or "generating code" in msg_lower: message_tag = "action"

            # Handle special formatting for code blocks or command output
            is_command_output = (tag == "command_output") # Check specific tag first
            is_code_block = message.strip().startswith("```") and message.strip().endswith("```")

            if is_code_block:
                # Extract code content, remove fences and optional language hint
                code_content = message.strip()[3:-3].strip()
                if '\n' in code_content:
                    first_line, rest_of_code = code_content.split('\n', 1)
                    # Basic check for language hint (short, alphanumeric first line)
                    if len(first_line.strip()) < 15 and re.match(r"^[a-zA-Z0-9_\-]+", first_line.strip()):
                        code_content = rest_of_code
                widget.insert(END, "\n") # Newline before code block
                widget.insert(END, code_content, "code") # Apply code tag
                widget.insert(END, "\n\n") # Newlines after code block
            elif is_command_output:
                # Apply command output tag
                # Use determined tag (e.g., error if command failed) for the whole line
                widget.insert(END, f"{message}\n", message_tag)
            else:
                # Insert standard message with determined tag
                widget.insert(END, f"{message}\n", message_tag)

            widget.see(END) # Scroll to the end
            widget.configure(state=DISABLED) # Disable widget after modification
        except tk.TclError as e:
            logger.warning(f"TclError adding message to widget {widget}: {e}")
        except Exception as e:
            logger.exception(f"Error adding message to widget {widget}: {e}")

    # --- NEW: Syntax Highlighting Parser ---
    class PygmentsHTMLParser(HTMLParser):
        """Parses Pygments-generated HTML and applies styles to a CTkTextbox."""
        def __init__(self, text_widget: ctk.CTkTextbox, style_name: str = 'monokai'):
            super().__init__()
            self.widget = text_widget # The CTkTextbox to apply tags to
            self.tags = [] # A stack to keep track of current HTML tags
            self.style_name = style_name # The Pygments style name
            # Pre-define the base style for the code block background
            if "code_block_base" not in self.widget.tag_names():
                try:
                    self.widget.tag_config("code_block_base", background="#1e1e1e") # VS Code editor background
                except Exception as e:
                    logger.warning(f"Could not configure base code block tag: {e}")

        def handle_starttag(self, tag, attrs):
            if tag == 'span':
                style_dict = {}
                for attr, value in attrs:
                    if attr == 'style':
                        # Simple style parser for "key: value; key2: value2".
                        # This is how Pygments' HtmlFormatter with noclasses=True works.
                        style_rules = value.split(';')
                        for rule in style_rules:
                            if ':' in rule:
                                key, val = rule.split(':', 1)
                                style_dict[key.strip()] = val.strip()
                
                if style_dict:
                    # Create a unique tag name based on the style hash to avoid conflicts
                    tag_name = f"style_{hash(value)}"
                    
                    # Configure the tag in the widget if it doesn't exist
                    if tag_name not in self.widget.tag_names():
                        # We can't set the font per-tag in CTkTextbox, so we focus on color.
                        font_weight = "bold" if style_dict.get('font-weight') == 'bold' else "normal"
                        font_slant = "italic" if style_dict.get('font-style') == 'italic' else "roman"

                        self.widget.tag_config(
                            tag_name,
                            foreground=style_dict.get('color'),
                            # The 'font' option is not supported per-tag in CTkTextbox, so we omit it.
                            # We can add underline or other supported styles here if needed
                        )
                    self.tags.append(tag_name)

        def handle_endtag(self, tag):
            if tag == 'span' and self.tags:
                self.tags.pop()

        def handle_data(self, data):
            # Apply the current stack of tags plus the base style
            current_tags = tuple(self.tags + ["code_block_base"]) # Apply background and then foreground styles
            self.widget.insert("end", data, current_tags)

    def _display_highlighted_code(self, widget: ctk.CTkTextbox, code: str, language: str):
        """Renders syntax-highlighted code into a CTkTextbox."""
        try:
            lexer = get_lexer_by_name(language, stripall=True)
        except Exception:
            try:
                lexer = guess_lexer(code)
            except Exception:
                # Fallback to plain text if lexer guessing fails
                widget.insert("end", code, "code_block_base")
                return

        # Use a dark theme that fits the UI. 'monokai' is a good default.
        formatter = HtmlFormatter(style='monokai', noclasses=True, nobackground=True)
        highlighted_html = highlight(code, lexer, formatter)

        # Use the custom parser to render the HTML into the widget
        parser = self.PygmentsHTMLParser(widget)
        parser.feed(highlighted_html)

    def copy_with_animation(self, text: str, button: ctk.CTkButton): # type: ignore
        """Copy with smooth animation feedback"""
        try:
            self.master.clipboard_clear()
            self.master.clipboard_append(text)
            
            # Animate button
            original_text = button.cget("text")
            original_color = button.cget("fg_color")
            button.configure(text="✓ Copied!", fg_color="#10B981", state="disabled")
            
            def reset():
                if button.winfo_exists():
                    button.configure(text=original_text, fg_color=original_color, state="normal")
            
            self.master.after(2000, reset)
        except Exception as e:
            logger.error(f"Failed to copy to clipboard: {e}")
            button.configure(text="✗ Failed", fg_color="#EF4444")
            self.master.after(2000, lambda: button.configure(text="📋 Copy"))

    def toggle_code_visibility(self, code_frame: ctk.CTkFrame, button: ctk.CTkButton):
        """Toggles the visibility of the code block."""
        if code_frame.winfo_viewable():
            code_frame.pack_forget()
            button.configure(text="▶ Expand")
        else:
            code_frame.pack(fill="both", expand=True, padx=1, pady=(0, 1))
            button.configure(text="▼ Collapse")

    def _create_modern_code_block(self, parent: Union[ctk.CTkTextbox, ctk.CTkScrollableFrame], code: str, language: str = "python", agent_name: Optional[str] = None, file_path: Optional[str] = None):
        """Create a modern, collapsible code block with copy button and syntax highlighting."""
        
        # Container with modern styling
        code_container = ctk.CTkFrame(
            parent,
            fg_color="#000000",  # Black background
            border_width=1,
            border_color="#313244",
            corner_radius=8
        )
        # --- BUG FIX: Pack the container into the parent scrollable frame ---
        # This is the correct way to add a widget to a CTkScrollableFrame.
        code_container.pack(fill="x", padx=10, pady=5, expand=True)

        # Header with language badge and copy button
        header = ctk.CTkFrame(code_container, fg_color="#181825", corner_radius=0)
        header.pack(fill="x", padx=0, pady=0)
        
        # --- NEW: Display Agent Name or File Path ---
        header_text = ""
        if agent_name:
            header_text = f"⚙️ {agent_name.upper()}"
        elif file_path:
            header_text = f"📄 {file_path}"
        
        header_label = ctk.CTkLabel(header, text=header_text, font=("Segoe UI", 11, "bold"), text_color="#CDD6F4", anchor="w")
        header_label.pack(side="left", padx=10, pady=5)

        lang_badge = ctk.CTkLabel(
            header,
            text=f"  {language}  ",
            fg_color="#6366F1",
            text_color="#FFFFFF",
            corner_radius=4,
            font=("Consolas", 10, "bold")
        )
        lang_badge.pack(side="left", padx=0, pady=5)
        
        # Line count info
        line_count = len(code.split('\n'))
        info_label = ctk.CTkLabel(
            header,
            text=f"{line_count} lines",
            text_color="#7F849C",
            font=("Segoe UI", 9)
        )
        info_label.pack(side="left", padx=5)
        
        # Copy button (modern style)
        copy_btn = ctk.CTkButton(
            header,
            text="📋 Copy",
            width=80,
            height=24,
            fg_color="transparent",
            hover_color="#313244",
            border_width=1,
            border_color="#45475A",
                font=("Segoe UI", 12),
            command=lambda: self.copy_with_animation(code, copy_btn)
        )
        copy_btn.pack(side="right", padx=10, pady=5)
        
        # Show Full Code button
        show_full_btn = ctk.CTkButton(
            header, 
            text="Show Full Code", 
            width=120, 
            height=24, 
            fg_color="transparent", 
            hover_color="#313244",
            border_width=1,
            border_color="#45475A",
            command=lambda: self.toggle_full_code_view(code_textbox, show_full_btn, line_count)
        )
        show_full_btn.pack(side="right", padx=5)
        # Code textbox frame
        code_frame = ctk.CTkFrame(code_container, fg_color="#1E1E2E", corner_radius=0)
        
        # Expand/Collapse button for long code
        # Always add the collapse button for consistency
        collapse_btn = ctk.CTkButton(
            header,
            text="▼ Collapse",
            width=90,
            height=24,
            fg_color="transparent",
            hover_color="#313244",
            command=lambda: self.toggle_code_visibility(code_frame, collapse_btn)
        )
        collapse_btn.pack(side="right", padx=5)

        # Code content textbox
        code_textbox = ctk.CTkTextbox(
            code_frame,
            fg_color="#1e1e1e",    # VS Code editor background
            text_color="#d4d4d4",  # VS Code default text color (slightly muted white)
            font=("Consolas", 11),
            wrap="none", # type: ignore
            activate_scrollbars=True,
            height=300  # Initial limited height
        )        
        # Insert highlighted code
        self._display_highlighted_code(code_textbox, code, language)
        
        # Pack the frame containing the textbox
        code_frame.pack(fill="x", padx=1, pady=(0, 1))
        code_textbox.pack(fill="both", expand=True)
        code_textbox.configure(state="disabled")

        return code_container

    def update_progress_safe(self, progress_data: Dict[str, Any]):
        """
        Thread-safe method to send progress updates to the UI thread via the queue.
        This is the primary way background threads communicate status back to the UI.
        """
        """
        Thread-safe method to send progress updates to the UI thread via the queue.

        Args:
            progress_data: A dictionary containing progress information (e.g., 
                           {'increment': 50, 'message': 'Processing...', 'system_message': '...', 'error': '...'}).
        """
        self.ui_queue.put((QUEUE_MSG_UPDATE_UI, progress_data))

    def update_ui_elements(self, progress_data: Dict[str, Any]):
        """
        Updates UI elements based on data received from the queue.
        This method MUST be called only from the UI thread. 

        Args:
            progress_data: The dictionary containing UI update information.
        """
        try:
            if not self.master.winfo_exists():
                return  # Check if window still exists
            
            # --- Update Progress Bar ---
            if "increment" in progress_data and self.progress_bar and self.progress_bar.winfo_exists():
                try: # type: ignore
                    new_progress = min(max(0, float(progress_data["increment"])), 100)
                    self.progress_var.set(new_progress) # type: ignore
                except (ValueError, TypeError):
                    pass

            # --- Update Status Bar Message ---
            if "message" in progress_data:
                status_msg = str(progress_data["message"])
                status_patterns = [
                    "loading", "created", "setup", "virtual environment",
                    "installing", "requirements", "django", "initializing",
                    "analyzing", "identified", "ready", "starting", "processing",
                    "planning", "implementing", "running", "agent", "project"
                ]
                
                is_status = any(p in status_msg.lower() for p in status_patterns)
                
                if is_status:
                    self.status_var.set(status_msg) # type: ignore                else:
                    # Not a status update, log it instead
                    self.add_log_message("INFO", "System", status_msg)
            
            # --- Display Agent Message (Handles thoughts + actions) ---
            if "agent_name" in progress_data and "agent_message" in progress_data:
                agent_name = str(progress_data.get("agent_name", "Agent")) # type: ignore
                agent_message_str = str(progress_data.get("agent_message", "")) # type: ignore
                
                # Parse for Thought + Action
                thought_match = re.search(r'Thought:\s*(.*?)(?=\nAction:|$)', agent_message_str, re.DOTALL)
                action_match = re.search(r'Action:\s*(\w+)', agent_message_str)
                params_match = re.search(r'Parameters:\s*(\{.*?\})', agent_message_str, re.DOTALL)
                
                # Display Thought
                if thought_match:
                    thought = thought_match.group(1).strip()
                    # Remove emoji if already present
                    thought = re.sub(r'^[🤔💭🧠]\s*', '', thought)
                    self.add_log_message("INFO", agent_name, f"💭 {thought}")
                
                # Display Action
                if action_match and params_match:
                    action = action_match.group(1)
                    try:
                        parameters = ast.literal_eval(params_match.group(1)) # type: ignore
                        formatted = self.format_action_card(action, parameters)
                        self.add_log_message("INFO", agent_name, formatted)
                    except:
                        self.add_log_message("INFO", agent_name, f"⚙️ {action.replace('_', ' ').title()}")
                elif not thought_match:
                    # No thought or action, display as-is
                    self.add_log_message("INFO", agent_name, agent_message_str)

            # --- Display System Message in Logs Tab ---
            if "system_message" in progress_data:
                full_msg = str(progress_data["system_message"])
                
                # The add_log_message function now handles sender detection and icon selection internally.
                self.add_log_message("INFO", "System", full_msg)
                
            # --- NEW: Handle displaying code diffs ---
            if progress_data.get("display_code_diff"):
                self.logger.info("Received request to display code diff.")
                original = progress_data.get("original_content", "")
                modified = progress_data.get("modified_content", "")
                filepath = progress_data.get("filepath", "Unknown File")
                
                self._display_diff_with_highlighting(original, modified)
                
                # Switch to the diff tab to make it visible
                if self.notebook:
                    self.notebook.set("↔️ Code Diff")

            # --- Display Error Message ---
            if "issue" in progress_data:
                issue_msg = str(progress_data["issue"]) # type: ignore
                self.status_var.set(f"Notice: {issue_msg[:100]}...") # type: ignore
                self.add_log_message("ERROR", "System", issue_msg)  # Keep ERROR level for logging clarity

            # --- Display Action Details ---
            if "action_details" in progress_data:
                self.add_log_message("DEBUG", "System", str(progress_data["action_details"]))

            # --- Handle Internal UI Updates (e.g., button state changes) ---
            if "internal_update" in progress_data and "widget_ref" in progress_data and "config" in progress_data:
                widget = progress_data["widget_ref"] # type: ignore
                config = progress_data["config"] # type: ignore
                try:
                    if widget and widget.winfo_exists():
                        widget.configure(**config)
                        logger.debug(f"Internal UI update applied to {widget}: {config}")
                    else:
                        logger.warning(f"Internal UI update skipped: Widget {widget} does not exist or reference lost.")
                except Exception as e:
                    logger.warning(f"Failed internal UI update for {widget}: {e}")
                return  # Stop processing other keys for internal updates
            
            # Batch internal updates
            if "internal_updates" in progress_data:
                updates = progress_data["internal_updates"]
                if isinstance(updates, list):
                    for update in updates:
                        widget = update.get("widget_ref")
                        config = update.get("config")
                        if widget and config:
                            try:
                                if widget.winfo_exists():
                                    widget.configure(**config)
                                    logger.debug(f"Batched UI update applied to {widget}: {config}") # type: ignore
                            except Exception as e: # type: ignore
                                logger.warning(f"Failed batched UI update for {widget}: {e}")
                return  # Stop processing other keys for internal updates
            
            # Scroll to bottom
            self._scroll_updates_to_bottom() # type: ignore
            
        except tk.TclError as e: # type: ignore
            logger.warning(f"TclError updating UI elements: {e}")
        except Exception as e:
            logger.exception(f"Error updating UI elements: {e}")

    def add_code_output(self, agent_name: str, thought: Optional[str] = None, action_type: Optional[str] = None, code_content: str = ""):
        """
        Adds a formatted block of agent output (thought, code) to the main conversation display.
        This method MUST be called only from the UI thread.
        """        
        # If in file browser mode, don't add new generated code to the display.
        if self.is_browsing_files:
            logger.debug("In file browser mode, skipping display of newly generated code.")
            return

        if not self.conversation_display or not self.conversation_display.winfo_exists():
            return

        agent_emojis = { # type: ignore
            "TARS": "🤖", "CASE": "⚙️", "SYSTEM": "💻", "USER": "👤", "CMD": "⚡"
        }
        agent_tag_map = {
            "TARS": "agent_tars", "CASE": "agent_case", "SYSTEM": "agent_system", "USER": "agent_user", "CMD": "agent_system"
        }
        agent_emoji = agent_emojis.get(agent_name.upper(), "💡")
        agent_tag = agent_tag_map.get(agent_name.upper(), "agent_system")

        if code_content:
            language = "python" # Default
            if action_type:
                try:
                    language = get_lexer_by_name(action_type.lower()).name.lower()
                except Exception:
                    language = "text"
            self._create_modern_code_block(self.conversation_display, code_content, language=language, agent_name=agent_name)

    def _process_ui_queue(self):
        """
        The main UI event loop. It runs periodically on the UI thread, checking for
        messages from background threads and dispatching them to the appropriate
        UI update handlers.
        """
        """
        Periodically checks the UI queue and processes messages from background threads.
        This method runs on the main UI thread.
        """
        try:
            # Process all messages currently in the queue
            while not self.ui_queue.empty():
                # --- FIX: Show the command card frame when a command is displayed ---
                if self.command_card_frame and not self.command_card_frame.winfo_viewable():
                    if any(msg[0] == QUEUE_MSG_DISPLAY_COMMAND for msg in list(self.ui_queue.queue)):
                        self.command_card_frame.pack(side=BOTTOM, fill=X, expand=False, pady=(5,0), ipady=5)

                message_type, data = self.ui_queue.get_nowait()
                # logger.debug(f"Processing UI queue message: Type={message_type}, Data Keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                try: # type: ignore
                    if message_type == QUEUE_MSG_UPDATE_UI:
                        # Check for the special 'finalize' key
                        if data.get("finalize"):
                            logger.debug(f"Processing finalize UI message: {data}")
                            self._finalize_run_ui(data.get("success", False), data.get("stopped", False))
                        else:
                            # Process standard UI updates
                            self.update_ui_elements(data)
                    elif message_type == QUEUE_MSG_SHOW_DIALOG:
                        # Handle requests to show modal dialogs
                        self._handle_dialog_request(data)
                    elif message_type == QUEUE_MSG_DISPLAY_COMMAND:
                        # Handle requests to display command tasks
                        self._display_command_task(data)
                    elif message_type == QUEUE_MSG_REQUEST_API_KEY_UPDATE:
                        # Handle requests for API key update dialog
                        self._handle_api_key_update_dialog(data)
                    elif message_type == QUEUE_MSG_REQUEST_NETWORK_RETRY:
                        # Handle requests for network retry dialog
                        self._handle_network_retry_dialog(data)
                    else:
                        logger.warning(f"Unknown message type received in UI queue: {message_type}")
                except Exception as msg_proc_e:
                    # Log errors processing a single message, but continue processing queue
                    logger.exception(f"Error processing single UI queue message (Type: {message_type}): {msg_proc_e}")
        except queue.Empty:
            pass # Queue is empty, nothing to do
        except Exception as e:
            # Catch errors in the queue processing loop itself
            logger.exception(f"Error during UI queue processing loop: {e}")
        finally:
            # Reschedule the queue check
            try:
                if self.master.winfo_exists():
                    self.master.after(100, self._process_ui_queue) # Check again after 100ms
            except tk.TclError:
                # Window was likely destroyed
                logger.info("Master window destroyed, stopping UI queue processing loop.")

    def _handle_dialog_request(self, data: Dict[str, Any]):
        """
        Processes a dialog request from the queue. It shows the correct type of
        modal dialog, stores the user's response, and signals the waiting
        background thread that the interaction is complete.
        """
        """
        Shows the appropriate modal dialog based on the request data received via the queue.
        Stores the result in self.dialog_result and signals the waiting thread via event.
        This method runs on the main UI thread.

        Args:
            data: Dictionary containing dialog parameters ('type', 'title', 'prompt', 'event', etc.).
        """
        dialog_type = data.get("type")
        event_to_set: Optional[threading.Event] = data.get("event")
        result: Any = None # Store result from the dialog

        try:
            logger.debug(f"Handling dialog request: Type='{dialog_type}', Title='{data.get('title')}'")
            if dialog_type == "input":
                result = simpledialog.askstring(
                    data.get("title", "Input Required"),
                    data.get("prompt", "Enter value:"),
                    show='*' if data.get("is_password") else None, # Show '*' for passwords
                    parent=self.master # Ensure dialog is on top of main window
                )
            elif dialog_type == "file_picker":
                result = filedialog.askopenfilename(
                    title=data.get("title", "Select File"),
                    parent=self.master
                )
                # filedialog returns empty string on cancel, convert to None for consistency
                if not result: result = None
            elif dialog_type == "confirmation":
                result = messagebox.askyesno(
                    data.get("title", "Confirm Action"),
                    data.get("prompt", "Are you sure?"),
                    parent=self.master
                ) # Returns True (Yes) or False (No)
            elif dialog_type == "user_action":
                # Use the custom dialog for user actions
                dialog = UserActionDialog(
                    self.master,
                    data.get("title", "Action Required"),
                    data.get("instructions", "Please perform the required action."),
                    data.get("command", "")
                )
                result = dialog.result # Get boolean result from custom dialog
            else:
                logger.error(f"Unknown dialog type requested: {dialog_type}")
                result = None # Indicate error or unknown type

        except Exception as e:
            logger.exception(f"Error showing dialog type '{dialog_type}': {e}")
            result = None # Ensure result is None on error
        finally:
            # Store the result and signal the waiting background thread
            self.dialog_result = result
            if event_to_set:
                logger.debug(f"Dialog '{dialog_type}' closed. Result: {result}. Signaling event.")
                event_to_set.set() # Signal the waiting thread
            elif threading.current_thread() is not threading.main_thread():
                logger.error("Dialog request from a background thread was processed, but no event object was found to signal completion!")

    # New synchronous helper for specific dialog types
    def _request_specific_dialog_from_thread_sync(self, queue_message_type: int, **kwargs) -> Any:
        """
        A synchronous helper for background threads to request a dialog that has a
        specific handler (like API key updates), rather than the generic one.
        It blocks the calling thread until the UI provides a result.
        """
        """
        Synchronous helper called by background threads (via asyncio.to_thread)
        to request a dialog that has a specific queue message type and handler.
        """
        # Ensure this is not called from the main UI thread directly for these specific types
        if threading.current_thread() is threading.main_thread():
            logger.error(f"Dialog request (type {queue_message_type}) should not be called synchronously from main thread.")
            # Depending on the dialog, could try to handle, but for API/Network it's better to fail.
            return None # Or raise an error

        event = threading.Event()
        request_data = {"event": event, **kwargs} # Data for the specific handler

        self.ui_queue.put((queue_message_type, request_data))
        logger.debug(f"Background thread put specific dialog request (type {queue_message_type}) on queue and is now waiting...")
        event.wait() # Wait for UI thread to process and set event
        logger.debug(f"Background thread received signal for specific dialog (type {queue_message_type}). Retrieving result.")
        result = self.dialog_result
        self.dialog_result = None # Clear shared result
        return result

    def _handle_api_key_update_dialog(self, data: Dict[str, Any]):
        """
        UI-thread handler for showing the API key update dialog. This dialog gives
        the user options to enter a new key, retry, or cancel.
        """
        """
        Shows a dialog prompting the user to update API key or retry.
        Stores (new_key_or_none, retry_current_bool) in self.dialog_result.
        """
        event_to_set: Optional[threading.Event] = data.get("event")
        agent_desc = data.get("agent_desc", "Agent")
        error_type = data.get("error_type", "API Error")
        current_key_name = data.get("current_key_name", "API_KEY")
        result: Tuple[Optional[str], bool] = (None, False)

        try:
            is_rate_limit = "RateLimitError" in error_type
            title = f"API Key Issue: {agent_desc}"
            if is_rate_limit:
                message = (f"The API rate limit was exceeded for {agent_desc}.\n\n"
                           "This is usually temporary. You can retry with the current key, or provide a different key.\n\n"
                           "Click 'Yes' to enter a new key.\nClick 'No' to retry with the current key.\nClick 'Cancel' to stop.")
            else: # AuthenticationError
                message = (f"An authentication error occurred for {agent_desc}.\n\n"
                           f"The API key for '{current_key_name}' may be invalid or expired.\n\n"
                           "Click 'Yes' to enter a new key.\nClick 'No' to retry with the current key.\nClick 'Cancel' to stop.")

            # askyesnocancel returns True for Yes, False for No, None for Cancel
            update_key_choice = messagebox.askyesnocancel(
                title,
                message,
                parent=self.master
            )

            if update_key_choice is True: # Yes - enter new key
                new_key = simpledialog.askstring(
                    f"Update API Key for {agent_desc}",
                    f"Enter new API key for {current_key_name}:",
                    show='*', # Mask input
                    parent=self.master
                )
                if new_key is not None: # User clicked OK in askstring
                    result = (new_key.strip() if new_key.strip() else None, False) # (new_key, dont_retry_current)
                else: # User clicked Cancel in askstring
                    result = (None, False) # (no_new_key, dont_retry_current) -> effectively cancel
            elif update_key_choice is False: # No - retry with current key
                result = (None, True) # (no_new_key, retry_current_key)
            else: # Cancel - update_key_choice is None
                result = (None, False) # (no_new_key, dont_retry_current) -> cancel

        except Exception as e:
            logger.exception(f"Error showing API key update dialog: {e}")
            result = (None, False) # Default to cancel on error
        finally:
            self.dialog_result = result
            if event_to_set:
                event_to_set.set()

    def _handle_network_retry_dialog(self, data: Dict[str, Any]):
        """UI-thread handler for showing the network retry confirmation dialog."""
        """Shows a dialog prompting the user to retry a network operation."""
        event_to_set: Optional[threading.Event] = data.get("event")
        agent_desc = data.get("agent_desc", "Operation")
        error_message = data.get("error_message", "A network error occurred.")
        result: bool = False # Default to not retry

        try:
            result = messagebox.askyesno(
                f"Network Error: {agent_desc}",
                f"A network error occurred while communicating for {agent_desc}:\n\n{error_message}\n\nWould you like to retry?",
                parent=self.master
            )
        except Exception as e:
            logger.exception(f"Error showing network retry dialog: {e}")
            result = False
        finally:
            self.dialog_result = result
            if event_to_set:
                event_to_set.set()

    # --- Thread-Safe Dialog Request Methods (Passed as Callbacks to Backend) ---

    def _request_dialog_from_thread(self, dialog_type: str, **kwargs) -> Any:
        """
        Generic function called by background threads to request a modal dialog.
        It queues the request and blocks the calling thread using a `threading.Event`
        until the UI thread processes the dialog and signals completion.
        """
        """
        Generic function called by background threads to request a modal dialog from the UI thread.
        It puts a request on the UI queue and blocks the calling thread until the UI thread
        processes the request, shows the dialog, and signals completion via an Event.

        Args:
            dialog_type: The type of dialog ("input", "file_picker", "confirmation", "user_action").
            **kwargs: Additional arguments specific to the dialog type (title, prompt, etc.).

        Returns:
            The result from the dialog (e.g., string input, file path, boolean confirmation), or None.
        """
        # Check if called from the main thread (should not happen for background tasks)
        if threading.current_thread() is threading.main_thread():
            logger.warning(f"Dialog request '{dialog_type}' called directly from main thread. Showing dialog synchronously.")
            # Handle synchronously if called from main thread (e.g., during initial setup before threading)
            temp_data = {"type": dialog_type, "event": None, **kwargs}
            self._handle_dialog_request(temp_data) # Show dialog directly
            return self.dialog_result # Return stored result

        # --- Logic for background thread request ---
        event = threading.Event() # Create an event to wait on
        request_data = {"type": dialog_type, "event": event, **kwargs}
        
        # Put the request onto the queue for the UI thread to process
        self.ui_queue.put((QUEUE_MSG_SHOW_DIALOG, request_data))
        logger.debug(f"Background thread put dialog request '{dialog_type}' on queue and is now waiting...")

        # Block the background thread until the UI thread signals completion via the event
        event.wait() # Wait indefinitely until event.set() is called by _handle_dialog_request

        logger.debug(f"Background thread received signal for dialog '{dialog_type}'. Retrieving result.")
        result = self.dialog_result # Retrieve the result stored by the UI thread
        self.dialog_result = None # Clear the shared result variable
        return result

    # --- Specific Thread-Safe Dialog Request Methods ---
    # These are the methods passed as callbacks to the backend components (AgentManager, WorkflowManager).

    def _request_input_dialog_from_thread(self, title: str, is_password: bool, prompt: Optional[str]) -> Optional[str]:
        """A specific, thread-safe callback for requesting simple text input."""
        """Thread-safe method to request a simple input dialog (e.g., for API keys)."""
        logger.info(f"Requesting input dialog from thread: '{title}' (Password: {is_password})")
        # Calls the generic request method with specific parameters
        return self._request_dialog_from_thread("input", title=title, is_password=is_password, prompt=prompt)

    def _request_file_picker_from_thread(self, title: str) -> Optional[str]:
        """A specific, thread-safe callback for requesting a file path from the user."""
        """Thread-safe method to request a file picker dialog."""
        logger.info(f"Requesting file picker from thread: '{title}'")
        return self._request_dialog_from_thread("file_picker", title=title)

    def _request_confirmation_dialog_from_thread(self, prompt: str) -> bool:
        """A specific, thread-safe callback for requesting a yes/no confirmation."""
        """Thread-safe method to request a yes/no confirmation dialog."""
        logger.info(f"Requesting confirmation dialog from thread: '{prompt}'")
        # Returns True for Yes, False for No/Cancel
        return bool(self._request_dialog_from_thread("confirmation", title="Confirm Action", prompt=prompt))

    def _request_user_action_dialog_from_thread(self, title: str, instructions: str, command: str) -> bool:
        """A specific, thread-safe callback for showing the custom user action dialog."""
        """Thread-safe method to request the custom user action dialog."""
        logger.info(f"Requesting user action dialog from thread: '{title}'")
        # Returns True if user clicks "Done", False otherwise
        return bool(self._request_dialog_from_thread("user_action", title=title, instructions=instructions, command=command))

    async def _request_api_key_update_dialog_from_thread(self, agent_desc: str, error_type: str, current_key_name: str) -> Tuple[Optional[str], bool]:
        """An async, thread-safe callback for handling API key update requests."""
        """Thread-safe method to request API key update after an error."""
        logger.info(f"Requesting API key update dialog for {agent_desc} due to {error_type}")
        # Call the new synchronous helper via asyncio.to_thread,
        # passing QUEUE_MSG_REQUEST_API_KEY_UPDATE as the message type.
        result = await asyncio.to_thread(
            self._request_specific_dialog_from_thread_sync,
            QUEUE_MSG_REQUEST_API_KEY_UPDATE, # Correct message type
            agent_desc=agent_desc,
            error_type=error_type,
            current_key_name=current_key_name
        )
        # Ensure the result is a tuple, even if None was returned (e.g., dialog error)
        if not isinstance(result, tuple) or len(result) != 2:
            logger.error(f"API key update dialog returned unexpected result type: {type(result)}. Defaulting to cancel.")
            return (None, False) # Default to cancel
        return result

    async def _request_network_retry_dialog_from_thread(self, agent_desc: str, error_message: str) -> bool:
        """An async, thread-safe callback for handling network retry requests."""
        """Thread-safe method to request network retry using the specific dialog handler."""
        logger.info(f"Requesting network retry dialog for {agent_desc}")
        result = await asyncio.to_thread(
            self._request_specific_dialog_from_thread_sync,
            QUEUE_MSG_REQUEST_NETWORK_RETRY, # Correct message type
            agent_desc=agent_desc,
            error_message=error_message
        )
        if not isinstance(result, bool):
            logger.error(f"Network retry dialog returned unexpected result type: {type(result)}. Defaulting to False.")
            return False
        return result

    async def _request_remediation_retry_from_thread(self, task_id: str, failure_reason: str) -> bool:
        """An async, thread-safe callback to ask the user if they want to retry a failed remediation cycle."""
        """Thread-safe method to ask the user if they want to retry a failed remediation cycle."""
        logger.info(f"Requesting remediation retry dialog from thread for task {task_id}")
        prompt = (
            f"Automated remediation for task '{task_id}' failed after multiple attempts.\n\n"
            f"Last known reason: {failure_reason[:250]}...\n\n"
            "Would you like to retry the entire remediation cycle for this task?"
        )
        # Use the generic dialog request method which is thread-safe
        return bool(await asyncio.to_thread(self._request_dialog_from_thread, "confirmation", title="Remediation Failed", prompt=prompt))

    def _change_api_key_manual(self):
        """
        Handles the manual 'Change API Key' button click.
        Prompts the user to select a provider and enter a new key, then re-initializes the agent.
        """
        if not self.config_manager or not self.agent_manager:
            messagebox.showwarning("Not Ready", "Please select a project and initialize agents before changing keys.", parent=self.master)
            # Since this is a simple warning, we won't add the icon logic here to keep it clean.
            # The main issue is with the more complex dialogs that follow.
            return

        if self.is_running:
            messagebox.showwarning("Busy", "Cannot change API key while a task is running.", parent=self.master)
            return

        # Create a temporary parent for the dialogs to set the icon
        dialog_parent = tk.Toplevel(self.master)
        dialog_parent.withdraw()

        # Use the currently selected provider as the default
        current_provider_display_name = self.provider_var.get()

        # --- NEW: User-friendly check if "All" is selected ---
        if current_provider_display_name == "All":
            logger.info("User clicked 'Change API Key' with 'All' providers selected. Prompting for provider selection.")
            messagebox.showinfo(
                "Select a Provider",
                "Please select a specific API provider from the dropdown menu first, then click 'Change API Key...' to update the key for that provider.",
                parent=dialog_parent
            )
            return
        # --- END NEW ---

        # Find the provider ID and key name from the display name
        provider_id_to_change = None
        api_key_name_to_change = None
        for pid, data in self.config_manager.providers_config.items():
            if data.get("display_name") == current_provider_display_name:
                provider_id_to_change = pid
                api_key_name_to_change = data.get("api_key_name")
                break

        if not provider_id_to_change or not api_key_name_to_change:
            # This case should now be rare, but kept as a safeguard.
            logger.error(f"Could not find configuration for provider '{current_provider_display_name}' during manual key change.") # type: ignore
            messagebox.showerror("Configuration Error", f"Could not find configuration for provider '{current_provider_display_name}'.", parent=dialog_parent)
            return

        # Set the icon on the temporary parent before showing the dialog
        self._set_dialog_icon(dialog_parent)

        # Prompt for the new key
        new_key = simpledialog.askstring(
            f"Update API Key for {current_provider_display_name}",
            f"Enter new API key for {api_key_name_to_change}:",
            show='*',
            parent=dialog_parent # Use the temporary parent
        )

        if new_key and new_key.strip():
            try:
                dialog_parent.destroy() # Clean up the temporary window
                # Store the new key
                store_credential(api_key_name_to_change, new_key.strip())
                self.add_message("System", f"API key for '{current_provider_display_name}' has been updated.")

                # Trigger re-initialization
                logger.info(f"Manual key change triggered re-initialization for provider '{provider_id_to_change}'.")
                # We can simply call on_model_selected, as it contains all the necessary re-initialization logic.
                self.on_model_selected()

                messagebox.showinfo("Success", f"API key for {current_provider_display_name} updated successfully. Agents have been re-initialized.", parent=self.master) # type: ignore

            except Exception as e:
                logger.exception(f"Failed to store or re-initialize after manual key change for {current_provider_display_name}.")
                messagebox.showerror("Error", f"Failed to update key or re-initialize agents: {e}", parent=self.master)
        elif new_key is not None: # User clicked OK but entered an empty string
            dialog_parent.destroy()
            messagebox.showwarning("Input Required", "API key cannot be empty.", parent=self.master) # type: ignore
        else: # User clicked Cancel
            dialog_parent.destroy()
            logger.info("Manual API key change was cancelled by the user.")

    def _open_manage_models_dialog(self):
        """Opens a dialog to add or remove models for the current provider."""
        if not self.config_manager:
            return

        provider_id = self._get_selected_provider_id()
        if provider_id == "all":
            messagebox.showwarning("Select Provider", "Please select a specific provider to manage its models.", parent=self.master)
            return

        dialog = ctk.CTkToplevel(self.master)
        dialog.title(f"Manage Models for {self.provider_var.get()}")
        dialog.geometry("500x600")
        dialog.transient(self.master)
        dialog.grab_set()

        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        label = ctk.CTkLabel(main_frame, text=f"Models for {self.provider_var.get()}", font=("Segoe UI", 16, "bold"))
        label.pack(pady=(0, 10))

        scroll_frame = ctk.CTkScrollableFrame(main_frame, label_text="Current Models")
        scroll_frame.pack(fill="both", expand=True, pady=5)

        def refresh_model_list():
            for widget in scroll_frame.winfo_children():
                widget.destroy()

            current_models = self.config_manager.get_models_for_provider(provider_id)
            for model in current_models:
                model_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
                model_frame.pack(fill="x", pady=2)

                model_label = ctk.CTkLabel(model_frame, text=model['id'], anchor="w")
                model_label.pack(side="left", fill="x", expand=True, padx=5)

                delete_button = ctk.CTkButton(
                    model_frame, text="🗑️", width=30,
                    command=lambda p=provider_id, m=model['id']: remove_model(p, m)
                )
                delete_button.pack(side="right")

        def remove_model(p_id, m_id):
            if messagebox.askyesno("Confirm Delete", f"Are you sure you want to remove model '{m_id}'?", parent=dialog):
                if self.config_manager.remove_model_from_provider(p_id, m_id):
                    refresh_model_list()
                    self._update_model_list(p_id) # Refresh main window dropdown

        def add_model():
            new_model_id = new_model_entry.get().strip()
            if new_model_id:
                if self.config_manager.add_model_to_provider(provider_id, new_model_id):
                    new_model_entry.delete(0, "end")
                    refresh_model_list()
                    self._update_model_list(provider_id) # Refresh main window dropdown
                    self.model_var.set(new_model_id) # Select the new model
            else:
                messagebox.showwarning("Input Required", "Please enter a model ID to add.", parent=dialog)

        add_frame = ctk.CTkFrame(main_frame)
        add_frame.pack(fill="x", pady=(10, 0))
        add_frame.grid_columnconfigure(0, weight=1)

        new_model_entry = ctk.CTkEntry(add_frame, placeholder_text="Enter new model ID (e.g., gpt-4o-mini)")
        new_model_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        add_button = ctk.CTkButton(add_frame, text="Add Model", command=add_model)
        add_button.grid(row=0, column=1)

        close_button = ctk.CTkButton(main_frame, text="Close", command=dialog.destroy)
        close_button.pack(pady=(10,0))

        refresh_model_list()




    # --- Command Execution Handling ---

    async def _request_command_execution_from_thread(self, task_id: str, command: str, description: str) -> Tuple[bool, str]:
        """
        The primary callback method for the `WorkflowManager` to request command execution.

        This method is async and runs in the `WorkflowManager`'s thread. It queues a request
        for the UI to display the command, then asynchronously waits for the UI thread to
        execute it and signal completion.
        """
        # This method is called from the backend thread.
        # It needs to queue a request for the UI and then wait for the result.
        if threading.current_thread() is threading.main_thread():
            logger.error("Command execution requested directly from main thread - this is unsafe!")
            return False, "Internal error: Command execution requested synchronously from main thread."

        # Create an event that this backend thread will wait on.
        # The UI thread will set this event when the command is done.
        event = threading.Event()
        self.command_exec_events[task_id] = event

        # Queue the request for the UI thread to display the command widget.
        self.ui_queue.put((QUEUE_MSG_DISPLAY_COMMAND, {
            "task_id": task_id,
            "command": command,
            "description": description
        }))

        logger.debug(f"Backend thread for task {task_id} is now waiting for UI command execution...")

        # --- Asynchronous Wait ---
        # Since this method is called via `await` in WorkflowManager, we need to wait
        # without blocking the asyncio event loop. We run the blocking `event.wait()`
        # in a separate thread using asyncio's `to_thread`.
        await asyncio.to_thread(event.wait)

        logger.debug(f"Backend thread for task {task_id} received signal. Retrieving result.")

        # Once the event is set, retrieve the result stored by the UI thread.
        result = self.command_exec_results.pop(task_id, (False, "Result not found after execution."))
        self.command_exec_events.pop(task_id, None) # Clean up

        # --- FIX: Ensure the second element of the tuple is always a valid JSON string ---
        success, output_str = result
        if not output_str.strip().startswith('{'):
            try: # type: ignore
                # If the output is not a JSON object (e.g., an error string), wrap it in a JSON structure.
                error_json = json.dumps({
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": output_str,
                    "structured_error": None
                })
                return success, error_json
            except Exception as e:
                logger.exception(f"Error executing command for task {task_id} in backend thread: {e}")
                return success, json.dumps({"success": False, "exit_code": -1, "stderr": str(e)})

        return success, output_str
    def _display_command_task(self, data: Dict[str, Any]):
        """
        Creates the interactive UI widget for a command task within the 'Updates / Logs' display.
        This includes the description, command text, and Run/Copy buttons. This method
        runs on the main UI thread.
        """
        command = data.get("command", "")
        task_id = data.get("task_id", "")
        description = data.get("description", "No description provided.")
        if not all([task_id, command, description]):
            logger.error(f"Missing data to display command task: {data}")
            event = self.command_exec_events.get(task_id)
            if event:
                self.command_exec_results[task_id] = (False, "Internal error: Failed to display command task UI.")
                event.set()
            return

        # The parent widget is now the main updates display textbox.
        parent_widget = self.updates_display

        if not parent_widget or not parent_widget.winfo_exists():
            logger.error(f"Command card frame does not exist. Cannot display command task {task_id}.")
            event = self.command_exec_events.get(task_id)
            if event:
                self.command_exec_results[task_id] = (False, "Internal UI error: Command display area not found.")
                event.set()
            return

        try:
            # Create the card inside the scrollable frame.
            task_frame = ctk.CTkFrame(parent_widget, fg_color="#2D2D3A", corner_radius=8, border_width=1, border_color=STATUS_COLORS["pending"])
            task_frame.grid_columnconfigure(1, weight=1) # Allow description label to expand

            header_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
            header_frame.pack(fill=X, padx=15, pady=(12, 8))
            header_frame.grid_columnconfigure(1, weight=1)

            status_icon_label = ctk.CTkLabel(header_frame, text="🕒", font=ctk.CTkFont(size=16))
            status_icon_label.grid(row=0, column=0, sticky="w", padx=(0, 8))

            # --- IMPROVEMENT 1: Enhance Task Title ---
            desc_label = ctk.CTkLabel(header_frame, text=f"Task {task_id}: {description} (Sandbox Protected)", wraplength=parent_widget.winfo_width() - 250, justify=LEFT, font=ctk.CTkFont(weight="bold"))
            desc_label.grid(row=0, column=1, sticky="w")

            # --- NEW: Frame for the status badge ---
            status_badge_label = ctk.CTkLabel(header_frame, text="Pending", font=ctk.CTkFont(size=12, weight="bold"), fg_color=STATUS_COLORS["pending"], text_color="white", corner_radius=12)
            status_badge_label.grid(row=0, column=2, sticky="e", padx=(10, 0))

            # --- IMPROVEMENT 2: Enhance Sandbox Badge Visuals ---
            sandbox_badge = ctk.CTkLabel(
                header_frame,
                text="🛡️ SANDBOX",  # All caps for emphasis
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#059669",  # Darker green for contrast
                text_color="white",
                corner_radius=6,
                padx=8,
                pady=2
            )
            sandbox_badge.grid(row=0, column=3, sticky="e", padx=(8, 0))
            
            # --- IMPROVEMENT 5: Add Tooltip to Sandbox Badge ---
            ToolTip(
                sandbox_badge,
                "All commands run in an isolated sandbox with:\n"
                "• Command whitelisting\n"
                "• Path traversal prevention"
            )

            body_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
            body_frame.pack(fill=X, padx=15, pady=(0, 15))

            # --- Standardize Card Height ---
            fixed_command_box_height = 80

            cmd_textbox = ctk.CTkTextbox(
                body_frame, # type: ignore
                font=("Consolas", 11),
                fg_color="#1A1A1A",
                border_width=0,
                corner_radius=6,
                height=fixed_command_box_height
            )
            # --- FIX: Insert command first, then the colored icon ---
            cmd_textbox.insert("1.0", command)
            cmd_textbox.tag_config("green_shield", foreground="#10B981")
            cmd_textbox.insert("1.0", "🛡️ ", "green_shield")

            cmd_textbox.configure(state="disabled") # Make it read-only
            cmd_textbox.pack(fill=X, expand=True)

            actions_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
            actions_frame.pack(fill=X, padx=15, pady=(0, 15))

            button_container = ctk.CTkFrame(actions_frame, fg_color="transparent")
            button_container.pack(side=RIGHT)

            copy_button = ctk.CTkButton(button_container, text="Copy", width=40, command=lambda: self.copy_with_animation(command, copy_button), fg_color="transparent", border_color="#4A4A4A", border_width=1, hover_color="#555555")
            copy_button.pack(side=LEFT, padx=(0, 10))

            run_button = ctk.CTkButton(button_container, text="Run Command", fg_color="#0078D4", hover_color="#0098FF", font=ctk.CTkFont(weight="bold"))
            run_button.pack(side=LEFT)

            ui_widgets = {
                "container": task_frame, "status_icon": status_icon_label,
                "status_badge": status_badge_label, "run_button": run_button, "copy_button": copy_button
            }

            # Configure button commands
            run_button.configure(command=partial(self._trigger_command_execution, task_id, command, ui_widgets))

            # Pack the new command card into the scrollable frame
            task_frame.pack(fill=X, padx=10, pady=5) # type: ignore
            self._scroll_updates_to_bottom()

        except Exception as e:
            logger.exception(f"Error displaying command task {task_id}: {e}")
            event = self.command_exec_events.get(task_id)
            if event:
                self.command_exec_results[task_id] = (False, f"UI Error displaying command: {e}")
                event.set()

    def _scroll_updates_to_bottom(self):
        """Scrolls the updates_display scrollable frame to the bottom."""
        if self.updates_display and self.updates_display.winfo_exists():
            self.updates_display._parent_canvas.yview_moveto(1.0)

    def _trigger_command_execution(self, task_id: str, command: str, ui_widgets: Dict[str, ctk.CTkBaseClass]):
        """
        Handles the 'Run Command' button click within an embedded task frame.
        It disables the UI for that task and starts the background execution thread
        (`_execute_command_ui_thread`).
        """
        """
        Handles the 'Run Command' button click within the embedded task frame.
        Disables buttons and starts the background execution thread.
        This method runs on the main UI thread.
        """
        logger.info(f"User clicked Run for Task {task_id}: {command}")
        # Get the event object needed to signal the waiting workflow thread
        event_to_signal = self.command_exec_events.get(task_id)
        if not event_to_signal:
            logger.error(f"Cannot execute command for task {task_id}: No waiting event found.")
            ui_widgets["run_button"].configure(text="Error!", state=DISABLED) # type: ignore
            return
        # Start the actual command execution in a separate thread
        logger.debug(f"Starting background thread for command execution: Task {task_id}")
        exec_thread = threading.Thread(target=self._execute_command_ui_thread, args=(task_id, command, event_to_signal, ui_widgets), daemon=True)
        exec_thread.start()

    def _execute_command_ui_thread(self, task_id: str, command: str, event_to_signal: threading.Event, ui_widgets: Dict[str, ctk.CTkBaseClass]):
        """
        Executes a command using the safe CommandExecutor and updates the UI.
        This method runs in a background thread.
        """
        success = False
        result_json = ""
        start_time = time.time()

        # --- Update UI to "Running" state ---
        def update_card_state(icon, badge_text, color, button_text, button_state="disabled"):
            ui_widgets["status_icon"].configure(text=icon)
            ui_widgets["status_badge"].configure(text=badge_text, fg_color=color)
            ui_widgets["container"].configure(border_color=color)
            ui_widgets["run_button"].configure(text=button_text, state=button_state)
            ui_widgets["copy_button"].configure(state=button_state)

        try:
            if not self.command_executor:
                raise RuntimeError("CommandExecutor is not initialized.")

            # --- DELEGATE EXECUTION TO COMMAND_EXECUTOR ---
            # The command_executor handles validation, venv, timeouts, and secure execution.
            # Its internal `read_stream` will log stdout/stderr to the console.
            # We will also stream it to the UI.
            
            # Queue the UI update to be done on the main thread
            self.master.after(0, lambda: update_card_state("⏳", "Running", STATUS_COLORS["running"], "Running..."))

            # The `execute` method returns a CommandResult object.
            result = self.command_executor.execute(command)
            success = result.success

            # Stream final output to UI
            self.update_progress_safe({"command_output": f"--- Command Finished: {command} ---"})
            if result.stdout:
                self.update_progress_safe({"command_output": f"STDOUT:\n{result.stdout}"})
            if result.stderr:
                self.update_progress_safe({"command_output": f"STDERR:\n{result.stderr}"})
            self.update_progress_safe({"command_output": f"--- Exit Code: {result.exit_code} ---"})

            # Prepare JSON result for the workflow manager
            result_json = result.model_dump_json()

            # --- Update UI based on final result ---
            if success:
                self.master.after(0, lambda: update_card_state("✅", "Success", STATUS_COLORS["success"], "✅ Success"))
            else:
                self.master.after(0, lambda: update_card_state("❌", "Check Needed", STATUS_COLORS["error"], "❌ Check Needed"))

        except (ValueError, FileNotFoundError, InterruptedError, PatchApplyError) as e:
            # Catch validation, interruption, or other pre-execution errors from CommandExecutor
            success = False
            error_message = f"Command execution failed: {e}"
            logger.error(f"Error executing command for task {task_id}: {error_message}", exc_info=True)
            self.update_progress_safe({"error": error_message})
            result_json = json.dumps({
                "command_str": command, "success": False, "exit_code": -1,
                "stdout": "", "stderr": str(e), "structured_error": None
            })
            self.master.after(0, lambda: update_card_state("🚫", "Blocked", STATUS_COLORS["error"], "Blocked")) # "Blocked" is a good neutral term

        except Exception as e:
            success = False
            error_message = f"An unexpected error occurred during command execution: {e}"
            logger.exception(f"Unexpected error in command execution thread for task {task_id}")
            self.update_progress_safe({"error": error_message})
            result_json = json.dumps({
                "command_str": command, "success": False, "exit_code": -1,
                "stdout": "", "stderr": str(e), "structured_error": None
            })
            self.master.after(0, lambda: update_card_state("❌", "Issue", STATUS_COLORS["error"], "Issue"))

        finally:
            # --- Signal completion to the waiting workflow thread ---
            self.command_exec_results[task_id] = (success, result_json)
            event_to_signal.set()
            logger.debug(f"Event signaled for task {task_id}.")

    def _parse_python_traceback(self, stderr: str) -> Optional[Dict[str, Any]]:
        """
        Parses a standard Python traceback string into a structured dictionary.
        This helps the remediation system understand the error context more deeply
        than just reading raw text.
        """
        """
        Parses a Python traceback from a string (typically stderr).

        Args:
            stderr: The string containing the potential traceback.

        Returns:
            A dictionary with structured error info if a traceback is found, otherwise None.
            The dictionary format is:
            {
              "errorType": "ExceptionName",
              "message": "The error message.",
              "stack": [
                { "file": "path/to/file.py", "line": 123, "code": "line of code" },
                ...
              ]
            }
        """
        traceback_match = re.search(
            r"Traceback \(most recent call last\):(.+?)^(?P<type>[a-zA-Z_]\w*Error): (?P<msg>.*)",
            stderr, re.DOTALL | re.MULTILINE
        )
        if not traceback_match:
            return None

        traceback_body, error_type, error_message = traceback_match.group(1), traceback_match.group('type'), traceback_match.group('msg').strip()
        stack = []
        frame_regex = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in .*\n\s*(?P<code>.*)', re.MULTILINE)

        for match in frame_regex.finditer(traceback_body):
            file_path_full = match.group('file')
            file_path_relative = file_path_full
            if self.project_root:
                try:
                    file_path_relative = str(Path(file_path_full).relative_to(self.project_root))
                except ValueError:
                    pass # File is not within the project root, keep full path
            
            stack.append({"file": file_path_relative.replace('\\', '/'), "line": int(match.group('line')), "code": match.group('code').strip()})

        return {"errorType": error_type, "message": error_message, "stack": stack}

    def show_about_dialog(self):
        """Displays the 'About' dialog box with application information."""
        """Displays the About dialog box."""
        messagebox.showinfo(
            "About Vebgen AI Agent",
            "Vebgen - AI Agent Development Application\n\n"
            "Version: 0.2\n"            "Developed by: Vebgen Team\n\n"
            "This tool uses AI agents to assist with software development tasks.",
            parent=self.master
        )

    def on_closing(self):
        """Handles the window close event, confirming with the user if a task is running."""
        """Handles the window close event (clicking the 'X' button)."""
        if self.is_running:
            # Ask for confirmation if a workflow is running
            if messagebox.askyesno("Confirm Exit", "A task is currently running. Exiting now might leave the project in an inconsistent state.\n\nAre you sure you want to exit?", parent=self.master):
                logger.warning("Exiting application while task is running.")
                self.master.destroy() # Close the window
            else:
                return # User cancelled exit
        else:
            logger.info("Closing application window.")
            self.master.destroy() # Close the window
