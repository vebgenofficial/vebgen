# src/ui/main_window.py
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
import re
import platform
import sys # For command execution output redirection (optional)
import subprocess # For command execution
import shlex
from tkinter import scrolledtext, messagebox, filedialog, simpledialog, Menu, StringVar, BooleanVar, END, WORD, BOTH, X, LEFT, RIGHT, BOTTOM, SUNKEN, NORMAL, DISABLED, W, E, ttk
from pathlib import Path # Keep Path import
from typing import List, Dict, Any, Optional, Tuple, Callable, Awaitable, Union
from functools import partial # For creating button commands with arguments
import json # Import json

# Import core components
# Assuming they are in the 'core' directory relative to 'src'
try:
    from src.core.workflow_manager import WorkflowManager, RequestCommandExecutionCallable # Import the specific callback type
    from src.core.agent_manager import AgentManager # Use relative import
    from src.core.memory_manager import MemoryManager
    from src.core.config_manager import ConfigManager
    from src.core.file_system_manager import FileSystemManager
    from src.core.command_executor import CommandExecutor
    from src.core.secure_storage import check_keyring_backend
    from src.core.secure_storage import store_credential, delete_credential, retrieve_credential # Import storage functions
    # Import specific exceptions if needed for more granular handling
    from src.core.llm_client import RateLimitError, AuthenticationError
    from src.core.workflow_manager import InterruptedError
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
# --- End Constants ---


class MainWindow:
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
        self.master.title("Vebgen")
        self.master.geometry("1280x768") # Wider to accommodate sidebar
        self.master.minsize(1024, 700)   # Adjusted minimum size
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

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
        self.is_running = False # Tracks if a background workflow is active
        self.available_frameworks: List[str] = [] # Populated by ConfigManager
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
        self.updates_display: Optional[tk.Text] = None
        self.conversation_display: Optional[ctk.CTkTextbox] = None
        self.status_frame: Optional[ctk.CTkFrame] = None
        self.status_label: Optional[ctk.CTkLabel] = None
        self.updates_status_frame: Optional[ctk.CTkFrame] = None
        self.updates_status_label: Optional[ctk.CTkLabel] = None # This will be removed
        self.conversation_status_frame: Optional[ctk.CTkFrame] = None
        self.conversation_status_label: Optional[ctk.CTkLabel] = None
        self.progress_bar: Optional[ctk.CTkProgressBar] = None # This will be removed
        self.logo_image: Optional[ctk.CTkImage] = None
        self.exec_settings_icon: Optional[ctk.CTkImage] = None
        self.wash_effect_image: Optional[ctk.CTkImage] = None
        self.wash_effect_label: Optional[ctk.CTkLabel] = None
        self.animation_label: Optional[ctk.CTkLabel] = None # For loading animation
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
            "user": {"font": ("Segoe UI", 14, 'bold')},
            "system": {"foreground": "#A0A0A0", "font": ("Segoe UI", 12, 'italic')},
            "error": {"foreground": "#E81123", "font": ("Segoe UI", 12, 'bold')},
            "warning": {"foreground": "#F7630C", "font": ("Segoe UI", 12)},
            "agent_name": {"foreground": "#0078D4", "font": ("Segoe UI", 14, 'bold')},
            "action": {"foreground": "#0078D4", "font": ("Segoe UI", 12, 'bold')},
            "success": {"foreground": "#2ECC71", "font": ("Segoe UI", 12, 'bold')},
            # Code tag for command entry widgets and code blocks - darker background
            "code": {"font": ("Consolas", 11), "background": "#252526", "foreground": "#DCE4EE", "wrap": "none",
                     "lmargin1": 10, "lmargin2": 10, "spacing1": 5, "spacing3": 5, "relief": tk.GROOVE, "borderwidth": 1},
            # Command output: monospaced, darker background
            "command_output": {"font": ("Consolas", 11), "foreground": "#CCCCCC", "background": "#252526", "wrap": "none",
                               "lmargin1": 10, "lmargin2": 10, "spacing1": 2, "spacing3": 2},
            # Default tag for regular messages
            "default": {"font": ("Segoe UI", 14)}
        }

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
        self.project_path_label = ctk.CTkLabel(project_frame, textvariable=self.project_path_var, fg_color="#3C3C3C", corner_radius=5, height=30, font=ctk.CTkFont(family="Consolas", size=12), anchor="w", padx=10)
        self.project_path_label.pack(fill=X, pady=(0, 10))
        ToolTip(self.project_path_label, text="Current project directory.")

        self.select_project_button = ctk.CTkButton(
            project_frame,
            text="📂  Select Project Directory...",
            command=self.select_project_directory,
            font=ctk.CTkFont(size=20)   # bigger emoji/text
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
        exec_title = ctk.CTkLabel(exec_title_frame, text="Execution Settings", font=ctk.CTkFont(size=14, weight="bold"))
        exec_title.pack(side=LEFT, anchor="w")

        fw_label = ctk.CTkLabel(exec_settings_frame, text="Framework", anchor="w")
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
        ai_title = ctk.CTkLabel(ai_title_frame, text="AI Model Settings", font=ctk.CTkFont(size=14, weight="bold"))
        ai_title.grid(row=0, column=1, sticky="w", padx=8)

        provider_label = ctk.CTkLabel(ai_settings_frame, text="API Provider", anchor="w")
        provider_label.pack(fill=X, pady=(0, 5))
        self.provider_dropdown = ctk.CTkComboBox(ai_settings_frame, variable=self.provider_var, state=DISABLED, command=self.on_provider_selected)
        self.provider_dropdown.pack(fill=X, pady=(0, 15))
        ToolTip(self.provider_dropdown, text="Select the AI service provider.")

        model_label = ctk.CTkLabel(ai_settings_frame, text="LLM Model", anchor="w")
        model_label.pack(fill=X, pady=(0, 5))
        self.model_dropdown = ctk.CTkComboBox(ai_settings_frame, variable=self.model_var, state=DISABLED, command=self.on_model_selected)
        self.model_dropdown.pack(fill=X, pady=(0, 15))
        ToolTip(self.model_dropdown, text="Select the specific LLM to use for all tasks.")

        # Temperature Sliders
        tars_slider_frame = ctk.CTkFrame(ai_settings_frame, fg_color="transparent")
        tars_slider_frame.pack(fill=X, pady=(5,0))
        self.tars_temp_label = ctk.CTkLabel(tars_slider_frame, text="Tars Temp", width=70, anchor="w")
        self.tars_temp_label.pack(side=LEFT)
        self.tars_temp_scale = ctk.CTkSlider(tars_slider_frame, from_=0.0, to=1.0, variable=self.tars_temp_var, number_of_steps=10)
        self.tars_temp_scale.pack(side=LEFT, expand=True, fill=X, padx=10)
        ToolTip(self.tars_temp_scale, text="Adjust Tars (Planner/Analyzer) temperature (0.0-1.0).")

        case_slider_frame = ctk.CTkFrame(ai_settings_frame, fg_color="transparent")
        case_slider_frame.pack(fill=X, pady=(5,0))
        self.case_temp_label = ctk.CTkLabel(case_slider_frame, text="Case Temp", width=70, anchor="w")
        self.case_temp_label.pack(side=LEFT)
        self.case_temp_scale = ctk.CTkSlider(case_slider_frame, from_=0.0, to=1.0, variable=self.case_temp_var, number_of_steps=10)
        self.case_temp_scale.pack(side=LEFT, expand=True, fill=X, padx=10)
        ToolTip(self.case_temp_scale, text="Adjust Case (Coder) temperature (0.0-1.0).")

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

        self.prompt_entry = ctk.CTkEntry(prompt_wrapper, placeholder_text="Describe your project goal...", font=ctk.CTkFont(size=16), border_width=0, height=40)
        self.prompt_entry.pack(side=LEFT, fill=X, expand=True, pady=5)
        self.prompt_entry.bind("<Return>", self.handle_send_prompt)

        # Add an animation label that will be shown when busy
        self.animation_label = ctk.CTkLabel(prompt_wrapper, text="", font=ctk.CTkFont(family="Consolas", size=16), text_color="#0078D4")
        self.animation_label.pack(side=LEFT, padx=10)

        self.send_button = ctk.CTkButton(prompt_wrapper, text="▶️ Start", command=self.handle_send_prompt, state=DISABLED, width=100, height=40, font=ctk.CTkFont(weight="bold"), corner_radius=6)
        self.send_button.pack(side=RIGHT, padx=5, pady=5)

        # Notebook
        self._create_notebook(parent_frame)

        # Status Bar
        # self._create_status_bar(parent_frame)

    def _create_notebook(self, parent_frame: ctk.CTkFrame):
        """Creates the tabbed notebook for displaying updates/logs and conversation."""
        self.notebook = ctk.CTkTabview(parent_frame, border_width=1, border_color="#4A4A4A", segmented_button_selected_color="#0078D4", fg_color="#1E1E1E")
        self.notebook.pack(expand=True, fill=BOTH, padx=20, pady=(0, 0))

        updates_tab = self.notebook.add("Updates / Logs")
        conversation_tab = self.notebook.add("Conversation")

        # --- Updates / Logs Tab ---
        updates_main_frame = ctk.CTkFrame(updates_tab, fg_color="transparent")
        updates_main_frame.pack(expand=True, fill=BOTH)

        # --- FIX: Replace tk.Text with CTkScrollableFrame for consistent widget layout ---
        self.updates_display = ctk.CTkScrollableFrame(
            updates_main_frame,
            fg_color="#1E1E1E",
            scrollbar_button_color="#4A4A4A",
            scrollbar_button_hover_color="#7F8488"
        )
        self.updates_display.pack(expand=True, fill=BOTH, padx=5, pady=5)

        # Status bar for the updates tab
        self.updates_status_frame = ctk.CTkFrame(updates_main_frame, height=25, fg_color="#252526", corner_radius=0, border_width=1, border_color="#4A4A4A")
        self.updates_status_frame.pack(side=BOTTOM, fill=X)
        self.status_label = ctk.CTkLabel(self.updates_status_frame, textvariable=self.status_var, anchor="w", font=ctk.CTkFont(size=12), text_color="#A0A0A0")
        self.status_label.pack(side=LEFT, fill=X, expand=True, padx=10)


        # --- Conversation Tab ---
        conversation_main_frame = ctk.CTkFrame(conversation_tab, fg_color="transparent")
        conversation_main_frame.pack(expand=True, fill=BOTH)

        # Create the status bar at the bottom of the conversation tab
        self.conversation_status_frame = ctk.CTkFrame(conversation_main_frame, height=25, fg_color="#252526", corner_radius=0)
        self.conversation_status_frame.pack(side=BOTTOM, fill=X)
        self.conversation_status_label = ctk.CTkLabel(self.conversation_status_frame, textvariable=self.status_var, anchor="w", font=ctk.CTkFont(size=12), text_color="#A0A0A0")
        self.conversation_status_label.pack(side=LEFT, fill=X, expand=True, padx=10)

        self.conversation_display = ctk.CTkTextbox(
            conversation_main_frame,
            wrap=WORD,
            state=DISABLED,
            font=self.text_tags["default"]["font"], # type: ignore
            fg_color="#1E1E1E", # Match main content background
            scrollbar_button_color="#4A4A4A",
            scrollbar_button_hover_color="#7F8488"
        )
        self.conversation_display.pack(expand=True, fill=BOTH, padx=5, pady=5)

        # Apply configured text tags to both widgets
        for name, config in self.text_tags.items():
            # CTkTextbox needs a modified config without the 'font' key
            tag_specific_config_ctk = config.copy()
            tag_specific_config_ctk.pop('font', None)

            if self.conversation_display:
                # CTkTextbox uses tag_config and the modified config
                self.conversation_display.tag_config(name, **tag_specific_config_ctk)

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

    def _set_ui_initial_state(self):
        """Disables all interactive UI controls that require a project to be loaded."""
        """Sets the initial disabled state for controls before project selection."""
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

    def _set_ui_project_selected_state(self):
        """Enables UI controls after a project directory is selected and basic configs are loaded."""
        """Enables UI controls after a project directory is selected and stage 1 init is done."""
        if self.prompt_entry: self.prompt_entry.configure(state=NORMAL)
        # Framework dropdown enabled only if frameworks are found
        fw_state = "readonly" if self.available_frameworks else "disabled"
        if self.framework_dropdown: self.framework_dropdown.configure(state=fw_state)
        if self.new_project_check: self.new_project_check.configure(state=NORMAL)
        if self.provider_dropdown: self.provider_dropdown.configure(state="readonly")
        if self.model_dropdown: self.model_dropdown.configure(state="readonly")
        if self.tars_temp_scale: self.tars_temp_scale.configure(state=NORMAL)
        if self.case_temp_scale: self.case_temp_scale.configure(state=NORMAL)
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
                confirmation_cb=self._request_confirmation_dialog_from_thread
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

            # Set provider dropdown and trigger model list update
            self.provider_var.set(providers.get(saved_provider_id, "All"))
            self._update_model_list(saved_provider_id)

            # Set the saved model if it's in the newly populated list
            if saved_model_id and any(m['id'] == saved_model_id for m in MODEL_DATA):
                self.model_var.set(next(m['display'] for m in MODEL_DATA if m['id'] == saved_model_id))

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
                # Use 'after' to allow the UI to update before starting the next stage.
                self.master.after(50, self._initialize_core_stage2)
            else:
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
                request_remediation_retry_cb=self._request_remediation_retry_from_thread, # New callback for remediation retry
                default_tars_temperature=self.tars_temp_var.get(), # Pass UI temperature
                default_case_temperature=self.case_temp_var.get(),  # Pass UI temperature
                ui_communicator=self.ui_communicator,
                remediation_config=(
                    loaded_state.remediation_config
                    if (loaded_state := self.memory_manager.load_project_state()) and hasattr(loaded_state, 'remediation_config')
                    else None
                )
            )
            self.progress_var.set(30)

            # Initialization complete
            self.core_components_initialized = True
            self.needs_initialization = True # Workflow manager created, needs project init run
            project_name = Path(self.project_root).name
            self.project_path_var.set(f"{project_name} ({self.project_root})")
            logger.info(f"Core components Stage 2 initialized successfully for project: {project_name}")
            self.add_message("System", f"Project '{project_name}' loaded. Framework: {self.framework_var.get()}. Ready for prompts.")
            self.status_var.set(f"Project: {project_name} | Ready")
            if self.send_button: self.send_button.configure(state=NORMAL) # Enable Start button

        except (ValueError, RuntimeError, ImportError, AuthenticationError, RateLimitError, Exception) as e:
            # Handle errors during AgentManager or WorkflowManager initialization
            logger.exception("Failed to initialize core components (Stage 2).")
            messagebox.showerror("Initialization Error", f"Failed to initialize agents or workflow (Stage 2):\n\n{e}\n\nCheck API keys or logs.", parent=self.master)
            self.core_components_initialized = False
            self.workflow_manager_instance = None
            self.agent_manager = None
            self.status_var.set("Initialization Error (Stage 2). Check logs.")
            # Keep UI disabled if stage 2 fails



            self._set_ui_initial_state()
        finally:
            # Ensure UI is unlocked regardless of success/failure in stage 2
            self._set_ui_running_state(False)

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

            # --- Clear previous displays and reset progress ---
            # Clear the updates display (CTkScrollableFrame) by destroying its children
            if self.updates_display and self.updates_display.winfo_exists():
                try:
                    for widget in self.updates_display.winfo_children():
                        widget.destroy()
                except tk.TclError: pass # Ignore if widget destroyed

            # Clear the conversation display (CTkTextbox)
            if self.conversation_display and self.conversation_display.winfo_exists():
                try:
                    self.conversation_display.configure(state=NORMAL)
                    self.conversation_display.delete('0.0', END)
                    self.conversation_display.configure(state=DISABLED)
                except tk.TclError: pass # Ignore if widget destroyed
            self.progress_var.set(0)
            self.status_var.set("Initializing...")
            self._set_ui_running_state(True) # Lock UI during initialization
            self.needs_initialization = True # Flag that next run needs full initialization

            # Start the two-stage initialization process
            self.master.after(50, self._initialize_core_stage1)
        else:
            logger.info("Project directory selection cancelled.")
            # Update status only if core components weren't already initialized
            if not self.project_root:
                self.status_var.set("Project selection cancelled. Please select a directory.")

    def _update_model_list(self, provider_id: str):
        """Updates the model dropdown list based on the selected provider."""
        """Helper to update the model dropdown based on the selected provider."""
        if getattr(self, 'is_initializing_stage1', False):
            logger.debug("Skipping model list update during Stage 1 initialization to prevent event loops.")
        global MODEL_DATA
        if not self.config_manager or not self.model_dropdown:
            return
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
                "Coming Soon",
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
        # Prevent this from running during the initial project loading phase
        if getattr(self, 'is_initializing_stage1', False):
            return
        # Stage 1 must be complete before a model can be selected.
        if not self.memory_manager or not self.config_manager:
            logger.warning("Cannot handle model selection: Core components (Stage 1) not initialized.")
            return
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
                        default_tars_temperature=self.tars_temp_var.get(), # Pass UI temperature
                        request_remediation_retry_cb=self._request_remediation_retry_from_thread, # New callback for remediation retry
                        default_case_temperature=self.case_temp_var.get(),  # Pass UI temperature
                        remediation_config=remediation_config_from_state
                    )
                    self.needs_initialization = True # Flag that workflow manager was recreated
                    self.status_var.set("Agent re-initialized. Ready.")
                    self.add_message("System", f"Agent re-initialized. Provider: {selected_provider_id}, Model: {selected_model_id}")
                else:
                    # This shouldn't happen if core components were initialized correctly before
                    raise RuntimeError("Core components missing, cannot recreate WorkflowManager.")
            except (ValueError, RuntimeError, AuthenticationError, RateLimitError, Exception) as e:
                # Handle errors during re-initialization (e.g., invalid API key for new model)
                logger.error(f"Failed to re-initialize agents/workflow after model change: {e}")
                messagebox.showerror("Agent Error", f"Failed to re-initialize agents:\n{e}\n\nCheck keys/models or restart.", parent=self.master)
                self.status_var.set("Agent re-initialization failed.") # type: ignore
                if self.send_button: self.send_button.configure(state=DISABLED) # Disable start if agents failed
            finally:
                # Unlock UI after re-initialization attempt
                self._set_ui_running_state(False)
        else:
            # This is the first time a model is selected, trigger Stage 2 initialization
            logger.info("First model selected. Triggering core components Stage 2 initialization.")
            self.status_var.set("Initializing agents and workflow (Stage 2)...")
            self._set_ui_running_state(True) # Lock UI during init
            # Schedule Stage 2 initialization to run after the UI has a chance to update.
            self.master.after(50, self._initialize_core_stage2)

    def handle_send_prompt(self, event=None):
        """
        Handles the 'Start' button click or Enter key press in the prompt entry.
        It validates all necessary inputs and configurations are ready, then starts
        the appropriate workflow (initial or subsequent) in a background thread.
        """
        """
        Handles the 'Start' button click or Enter key press in the prompt entry.
        Validates input and starts the appropriate workflow in a background thread.
        """
        if self.is_running:
            messagebox.showwarning("Busy", "A task is already running. Please wait.", parent=self.master)
            return

        # --- Input Validation ---
        user_prompt = ""
        if self.prompt_entry: user_prompt = self.prompt_entry.get().strip()
        if not user_prompt:
            messagebox.showwarning("Input Required", "Please enter a prompt describing your goal.", parent=self.master)
            return

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
        self.add_message("User", user_prompt) # Add user prompt to conversation display
        if self.prompt_entry: self.prompt_entry.delete(0, END) # Clear prompt entry
        self._set_ui_running_state(True) # Disable UI controls

        thread_target = None # Function to run in the background thread
        thread_args: Tuple = () # Arguments for the thread target

        # Determine if this is the initial run (needs project init) or a subsequent prompt
        run_as_initial = self.needs_initialization # Check the flag set during init/re-init

        if run_as_initial and self.project_root:
            logger.info(f"Starting initial workflow run. Prompt: '{user_prompt[:100]}...'")
            thread_target = self._run_initial_workflow_thread
            is_new = self.is_new_project.get()
            thread_args = (user_prompt, selected_framework, is_new)
            self.needs_initialization = False # Reset flag after starting initial run
        else:
            logger.info(f"Handling subsequent prompt as new feature request: '{user_prompt[:100]}...'")
            thread_target = self._run_new_feature_thread
            thread_args = (user_prompt,)

        # Start the background thread
        if thread_target:
            logger.debug(f"Starting background thread for target: {thread_target.__name__}")
            thread = threading.Thread(target=thread_target, args=thread_args, daemon=True)
            thread.start()
        else:
            # Should not happen if logic above is correct
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
        readonly_state = DISABLED if running else "readonly" # For Comboboxes
        cursor = "watch" if running else "" # Change cursor to indicate busy state

        try:
            # --- Animation Control ---
            if running:
                self._start_animation() # Start animation
            else:
                self._stop_animation() # Stop animation

            # --- MODIFIED LOGIC ---
            # Only enable the send button and prompt if the full initialization is complete.
            # Otherwise, keep them disabled.
            if not running and self.core_components_initialized:
                if self.send_button and self.send_button.winfo_exists(): # type: ignore
                    self.send_button.configure(state=NORMAL)
                if self.prompt_entry and self.prompt_entry.winfo_exists(): # type: ignore
                    self.prompt_entry.configure(state=NORMAL)
            else:
                if self.send_button and self.send_button.winfo_exists(): # type: ignore
                    self.send_button.configure(state=DISABLED)
                if self.prompt_entry and self.prompt_entry.winfo_exists(): # type: ignore
                    self.prompt_entry.configure(state=DISABLED)

            # Enable/disable framework selection (allow changing only when not running)
            fw_state = readonly_state if self.available_frameworks and not running else "disabled"
            if self.framework_dropdown and self.framework_dropdown.winfo_exists():
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
            if self.case_temp_scale and self.case_temp_scale.winfo_exists(): self.case_temp_scale.configure(state=new_state)
            if self.select_project_button and self.select_project_button.winfo_exists(): self.select_project_button.configure(state=new_state)

            # Set cursor for the main window
            if self.master.winfo_exists():
                self.master.configure(cursor=cursor)

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

    def _run_initial_workflow_thread(self, initial_prompt: str, framework: str, is_new_project: bool):
        """
        The target function for the background thread when the user starts the
        very first workflow for a project. It runs the full `initialize_project`
        and `run_feature_cycle` methods of the `WorkflowManager`.
        """
        """
        Target function for the background thread to run the initial project setup
        and the first feature cycle.
        """
        success = False
        run_completed = False
        try:
            if self.workflow_manager_instance and self.project_root:
                logger.info("Background thread: Starting project initialization...")
                # Run the initialization part of the workflow
                # Ensure initialize_project is awaited if it's async
                asyncio.run(self.workflow_manager_instance.initialize_project(
                    project_root=self.project_root,
                    framework=framework,
                    initial_prompt=initial_prompt,
                    is_new_project=is_new_project
                ))
                logger.info("Background thread: Project initialization complete. Starting feature cycle...")
                # Run the feature development cycle
                # Ensure run_feature_cycle is awaited if it's async
                asyncio.run(self.workflow_manager_instance.run_feature_cycle())
                run_completed = True # Mark as completed if no exceptions occurred
                logger.info("Background thread: Initial workflow run finished.")

                # Check final state for errors
                if self.workflow_manager_instance.project_state:
                    # Use attribute access for Pydantic models
                    if any(f.status == "failed" for f in self.workflow_manager_instance.project_state.features):
                        success = False
                        logger.warning("Initial workflow finished, but at least one feature failed.")
                    else:
                        success = True # No exceptions and no failed features
                else:
                    success = False # Should not happen if init succeeded
                    logger.error("Initial workflow finished, but project state is missing.")
            else:
                logger.error("WorkflowManager instance or project root not available for initial run.")
                # Send error back to UI thread (note: the extra ')' was a typo, removed)
                self.update_progress_safe({"error": "WorkflowManager not initialized or no project selected."})
        except InterruptedError as e:
            # User cancelled via a dialog (e.g., API key prompt, confirmation)
            logger.warning(f"Initial workflow cancelled by user: {e}")
            self.update_progress_safe({"error": f"Operation cancelled by user: {e}"})
        except (RateLimitError, AuthenticationError) as api_err:
            # Catch specific API errors from the workflow
            logger.error(f"API Error during initial workflow: {api_err}")
            self.update_progress_safe({"error": f"API Error: {api_err}"})
            success = False # Mark as failed due to API error
        except Exception as e:
            # Catch any other exceptions during the workflow
            logger.exception("An error occurred during the initial WorkflowManager run.")
            self.update_progress_safe({"error": f"Workflow failed: {e}"})
            success = False # Mark as failed
        finally:
            # Ensure UI is updated and unlocked, regardless of success/failure
            # Put a message on the queue for the UI thread to finalize
            logger.debug("Background thread: Putting finalize message on UI queue.")
            self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"finalize": True, "success": success and run_completed}))


    def _run_new_feature_thread(self, prompt: str):
        """
        The target function for the background thread when the user submits a new
        prompt after the initial setup is complete. It runs the `handle_new_prompt` method.
        """
        """
        Target function for the background thread to handle a subsequent prompt,
        identifying new features and running the development cycle for them.
        """
        success = False
        run_completed = False
        try:
            if self.workflow_manager_instance:
                logger.info("Background thread: Starting new feature request processing...")
                # Handle the new prompt (identifies features, runs cycle)
                # Ensure handle_new_prompt is awaited if it's async
                asyncio.run(self.workflow_manager_instance.handle_new_prompt(prompt))
                run_completed = True
                logger.info("Background thread: New feature workflow run finished.")

                # Check final state for errors
                if self.workflow_manager_instance.project_state:
                    # Check if any features *overall* are marked as failed using attribute access
                    if any(f.status == "failed" for f in self.workflow_manager_instance.project_state.features):
                        success = False
                        logger.warning("New feature workflow finished, but at least one feature has failed.")
                    else:
                        success = True # No exceptions and no failed features
                else:
                    success = False
                    logger.error("New feature workflow finished, but project state is missing.")
            else:
                logger.error("WorkflowManager instance not available for new feature run.")
                self.update_progress_safe(({"error": "WorkflowManager not initialized."}))

        except InterruptedError as e:
            logger.warning(f"New feature workflow cancelled by user: {e}")
            self.update_progress_safe({"error": f"Operation cancelled by user: {e}"})
        except (RateLimitError, AuthenticationError) as api_err:
            # Catch specific API errors from the workflow
            logger.error(f"API Error during new feature workflow: {api_err}")
            self.update_progress_safe({"error": f"API Error: {api_err}"})
            success = False # Mark as failed due to API error
        except Exception as e:
            logger.exception("An error occurred during the new feature WorkflowManager run.")
            self.update_progress_safe({"error": f"Workflow failed: {e}"})
            success = False # Mark as failed
        finally:
            logger.debug("Background thread: Putting finalize message on UI queue.")
            self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"finalize": True, "success": success and run_completed}))

    def _finalize_run_ui(self, success: bool):
        """
        Updates all UI elements after a background workflow run completes,
        either successfully or with an error. This is always called on the main UI thread.
        """
        """
        Updates UI elements after a background workflow run completes.
        This method is called by the UI thread via the queue message.
        """
        logger.debug(f"Finalizing run UI. Success: {success}")
        self.is_running = False # Reset running flag
        self._set_ui_running_state(False) # Re-enable UI controls

        # Update status bar message based on success/failure
        project_name = Path(self.project_root).name if self.project_root else "No Project"
        framework_name = self.framework_var.get() # type: ignore
        if success:
            final_status = f"Project: {project_name} | Framework: {framework_name} | Workflow finished successfully."
            # The progress bar is now part of the task card, so we don't set it here.
            # We can just ensure the final status is correct.
        else:
            # Check if status already contains an error/cancelled message
            current_status = self.status_var.get()
            if "Error:" not in current_status and "Cancelled" not in current_status and "Failed" not in current_status:
                final_status = f"Project: {project_name} | Framework: {framework_name} | Workflow finished with errors."
            else:
                final_status = current_status # Keep the specific error message
            # Don't reset progress bar on failure, keep its last value
        self.status_var.set(final_status)
        logger.info(f"Workflow finished. UI updated. Final Status: {final_status}")

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
            sender: The source of the message (e.g., "System", "User", "Tars", "Case", "CMD").
            message: The message content string.
        """
        message_str = str(message) if message is not None else "" # Ensure message is a string
        # Determine the appropriate update type based on the sender
        if sender.lower() in ["tars", "case"]:
            # Agent messages go to conversation display primarily
            self.update_progress_safe({'agent_name': sender, 'agent_message': message_str})
        elif sender.upper() == "CMD":
            # Command output goes to updates display
            self.update_progress_safe({'command_output': message_str})
        else:
            # System, User, or other messages go to both (or primarily updates)
            self.update_progress_safe({'system_message': f"{sender}: {message_str}"})

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

    def _update_ui_elements(self, progress_data: Dict[str, Any]):
        """
        Updates UI elements based on data received from the queue.
        This method MUST be called only from the UI thread.

        Args:
            progress_data: The dictionary containing UI update information.
        """
        try:
            if not self.master.winfo_exists(): return # Check if window still exists

            # --- Handle Internal UI Updates (e.g., button state changes) ---
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
                                    logger.debug(f"Batched UI update applied to widget {widget}: {config}")
                            except Exception as e:
                                logger.warning(f"Failed batched UI update for {widget}: {e}")
                return # Stop processing other keys for internal updates

            if progress_data.get("internal_update") and "widget_ref" in progress_data and "config" in progress_data:
                widget = progress_data["widget_ref"]
                config = progress_data["config"]
                try:
                    if widget and widget.winfo_exists(): # type: ignore
                        widget.configure(**config)
                        logger.debug(f"Internal UI update applied to widget {widget}: {config}")
                    else:
                        logger.warning(f"Internal UI update skipped: Widget {widget} does not exist or reference lost.")
                except Exception as e:
                    logger.warning(f"Failed internal UI update for {widget}: {e}")
                return # Stop processing other keys for internal updates

            # --- Update Progress Bar ---
            if 'increment' in progress_data and self.progress_bar and self.progress_bar.winfo_exists():
                try: # type: ignore
                    new_progress_val = float(progress_data['increment'])
                    new_progress = min(max(0, new_progress_val), 100) # Clamp between 0 and 100
                    self.progress_var.set(new_progress)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid 'increment' value received for progress bar: {progress_data['increment']}")

            # --- Update Status Bar Message ---
            if 'message' in progress_data:
                status_msg = str(progress_data['message'])
                # Update the status var, which will update any status labels that use it.
                self.status_var.set(status_msg)

            # --- Display Error Message ---
            if 'error' in progress_data:
                error_msg = str(progress_data['error'])
                if self.status_label and self.status_label.winfo_exists():
                    # Show truncated error in status bar
                    self.status_var.set(f"Error: {error_msg[:100]}...")
                # Add full error to both displays
                self._add_log_message("System", f"Error: {error_msg}", tag="error")
                self._add_message_to_widget(self.conversation_display, "System", f"Error: {error_msg}", tag="error")

            # --- Display System Message ---
            if 'system_message' in progress_data:
                full_msg = str(progress_data['system_message'])

                # The message might come in with a "Sender: " prefix.
                # Let's get the core message for analysis.
                if ':' in full_msg:
                    try:
                        sender, msg = full_msg.split(':', 1)
                        msg = msg.strip()
                    except ValueError:
                        sender = "System"
                        msg = full_msg
                else:
                    sender = "System"
                    msg = full_msg.strip()

                # Define patterns for messages that are status updates
                status_patterns = [
                    "loading project state", "created new project state", "setting up",
                    "creating virtual environment", "waiting for user", "running setup",
                    "virtual environment created", "installing requirements", "requirements installed",
                    "running django-admin", "django project created", "initializing git",
                    "initial framework setup complete", "analyzing request", "identified initial features",
                    "initial project state ready", "starting feature development", "processing feature",
                    "planning feature", "defining api contracts", "planning", "plan generated",
                    "implementing feature", "implementing:", "task ", "generating code", "running test",
                    "test step passed", "creating directory", "agent re-initialized", "project loaded",
                    "ready for prompts", "using stored value"
                ]
                
                is_status_update = any(p in msg.lower() for p in status_patterns) and sender.lower() != 'user'

                if is_status_update:
                    # If it's a status update, add it to the logs
                    self._add_log_message(sender, msg)
                    # And set the status bar text
                    self.status_var.set(msg)
                else:
                    # If it's a conversational message (e.g. from User, or a summary from System)
                    # add it ONLY to the conversation display.
                    self._add_message_to_widget(self.conversation_display, sender, msg)

            # --- Display Action Details ---
            if 'action_details' in progress_data:
                msg = str(progress_data['action_details'])
                # Add action details to the logs display with 'action' tag
                self._add_log_message("System", msg, tag="action")

            # --- Display Agent Message ---
            if 'agent_name' in progress_data and 'agent_message' in progress_data:
                agent_name = str(progress_data['agent_name'])
                agent_message = str(progress_data['agent_message'])
                # Agent messages ONLY go to the conversation display
                self._add_message_to_widget(self.conversation_display, agent_name, agent_message)

            # --- Display Command Output ---
            if 'command_output' in progress_data:
                output = str(progress_data['command_output'])
                # Command output goes to the updates/logs display
                self._add_log_message("CMD", output, tag="command_output")

        except tk.TclError as e:
            logger.warning(f"TclError updating UI elements: {e}")
        except Exception as e:
            logger.exception(f"Error updating UI elements: {e}")

    def _add_log_message(self, sender: str, message: str, tag: Optional[str] = None):
        """
        Adds a formatted message to the 'Updates / Logs' tk.Text widget.
        This method is specifically for the standard tk.Text widget.
        This method MUST be called only from the UI thread.
        """
        # This method now adds a simple CTkLabel to the scrollable frame
        scrollable_frame = self.updates_display
        if not scrollable_frame or not scrollable_frame.winfo_exists():
            return

        try:
            message_tag = tag if tag and tag in self.text_tags else "default"
            if tag is None:
                msg_lower = message.lower()
                if "error" in msg_lower or "failed" in msg_lower: message_tag = "error"
                elif "warning" in msg_lower or "skipping" in msg_lower: message_tag = "warning"
                elif "success" in msg_lower or "completed" in msg_lower: message_tag = "success"

            log_label = ctk.CTkLabel(scrollable_frame, text=f"[{sender.upper()}] {message}", wraplength=scrollable_frame.winfo_width() - 40, justify=LEFT, anchor="w", font=self.text_tags[message_tag]['font'], text_color=self.text_tags[message_tag].get('foreground', '#DCE4EE'))
            log_label.pack(fill=X, padx=10, pady=2)

        except tk.TclError as e:
            logger.warning(f"TclError adding log message to widget {scrollable_frame}: {e}")
        except Exception as e:
            logger.exception(f"Error adding log message to widget {scrollable_frame}: {e}")

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
                message_type, data = self.ui_queue.get_nowait()
                # logger.debug(f"Processing UI queue message: Type={message_type}, Data Keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                try:
                    if message_type == QUEUE_MSG_UPDATE_UI:
                        # Check for the special 'finalize' key
                        if data.get("finalize"):
                            logger.debug("Processing finalize UI message.")
                            self._finalize_run_ui(data.get("success", False))
                        else:
                            # Process standard UI updates
                            self._update_ui_elements(data)
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
            title = f"API Key Issue: {agent_desc}"
            message = (f"An API error occurred for {agent_desc}:\n{error_type}\n\n"
                       f"Key name in use: {current_key_name}\n\n"
                       f"Would you like to enter a new API key, retry with the current key, or cancel?")
            # This could be a more sophisticated custom dialog. For now, using simpledialog and messagebox.
            # 1. Ask if they want to update the key.
            update_key_choice = messagebox.askyesnocancel(
                title,
                message + "\n\nClick 'Yes' to enter a new key.\nClick 'No' to retry with the current key.\nClick 'Cancel' to stop this operation.",
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


    # --- Command Execution Handling ---

    async def _request_command_execution_from_thread(self, task_id: str, command: str, description: str) -> Tuple[bool, str]:
        """
        The primary callback method for the `WorkflowManager` to request command execution.

        This method is async and runs in the `WorkflowManager`'s thread. It queues a request
        for the UI to display the command, then asynchronously waits for the UI thread to
        execute it and signal completion.
        """
        """
        Callback method for WorkflowManager to request command execution via the UI.
        This method runs in the WorkflowManager's thread (likely an asyncio event loop).

        It puts a request on the UI queue to display the command task, then waits
        asynchronously for the UI thread to execute the command (or skip it) and
        signal completion via an event.

        Args:
            task_id: A unique identifier for the command task.
            command: The command string to be executed.
            description: A user-friendly description of the command's purpose.

        Returns:
            A tuple (success: bool, output_or_error: str).
        """
        # Ensure this isn't called from the main UI thread
        if threading.current_thread() is threading.main_thread():
            logger.error("Command execution requested directly from main thread - this is unsafe!")
            return False, "Internal error: Command execution requested synchronously from main thread."

        event = threading.Event() # Event for synchronization
        self.command_exec_events[task_id] = event
        self.command_exec_results.pop(task_id, None) # Clear any previous result for this ID

        # Data package for the UI queue message
        request_data = {
            "task_id": task_id,
            "command": command,
            "description": description
        }
        # Put the request on the queue for the UI thread to display the command task
        self.ui_queue.put((QUEUE_MSG_DISPLAY_COMMAND, request_data))
        logger.debug(f"Workflow thread waiting for UI command execution result for task {task_id}...")

        # --- Asynchronous Wait ---
        # Since this method is called via `await` in WorkflowManager, we need to wait
        # without blocking the asyncio event loop. We run the blocking `event.wait()`
        # in a separate thread using asyncio's `to_thread`.
        try:
            await asyncio.to_thread(event.wait) # Wait for the UI thread to signal completion
        except Exception as wait_e:
            logger.exception(f"Error while waiting for command execution event for task {task_id}: {wait_e}")
            # Clean up event if wait fails
            self.command_exec_events.pop(task_id, None)
            self.command_exec_results.pop(task_id, None)
            return False, f"Error waiting for command result: {wait_e}"

        logger.debug(f"Workflow thread received command execution signal for task {task_id}.")
        # Retrieve the result stored by the UI's execution thread
        result = self.command_exec_results.get(task_id, (False, "Internal error: Result not found after wait."))

        # Clean up synchronization objects for this task ID
        self.command_exec_events.pop(task_id, None)
        self.command_exec_results.pop(task_id, None)

        return result

    def _display_command_task(self, data: Dict[str, Any]):
        """
        Creates the interactive UI widget for a command task within the 'Updates / Logs' display.
        This includes the description, command text, and Run/Copy buttons. This method
        runs on the main UI thread.
        """
        """
        Creates UI elements for a command task within the 'Updates / Logs' widget.
        This method runs on the main UI thread.
        """
        command = data.get("command", "")
        task_id = data.get("task_id", "")
        auto_run_patterns = [
            "-m venv venv", "pip install -r requirements.txt", "django-admin startproject",
            "git init", "git add .", 'git commit -m "Initial project setup'
        ]
        if any(pattern in command for pattern in auto_run_patterns):
            logger.info(f"Auto-executing setup command for task {task_id}: {command}")
            self.add_message("System", f"Running setup: {command}")
            event_to_signal = self.command_exec_events.get(task_id)
            if event_to_signal:
                exec_thread = threading.Thread(target=self._execute_command_ui_thread, args=(task_id, command, event_to_signal, None, None), daemon=True)
                exec_thread.start()
            else:
                logger.error(f"Cannot auto-execute command for task {task_id}: No waiting event found.")
            return

        description = data.get("description")
        widget = self.updates_display

        if not all([task_id, command, description, widget, widget.winfo_exists()]):
            logger.error(f"Missing data or widget to display command task: {data}")
            event = self.command_exec_events.get(task_id)
            if event:
                self.command_exec_results[task_id] = (False, "Internal error: Failed to display command task UI.")
                event.set()
            return

        try:
            container_frame = ctk.CTkFrame(widget, fg_color=STATUS_COLORS["pending"], corner_radius=8)
            # --- FIX: Use a grid layout to enforce consistent width ---
            # Configure column 0 to expand, forcing the frame to fill horizontal space.
            container_frame.grid_columnconfigure(0, weight=1)

            # The inner frame holds all the card's content.
            task_frame = ctk.CTkFrame(container_frame, fg_color="#333333", corner_radius=8)
            # Place the inner frame in the expanding grid cell.
            task_frame.grid(row=0, column=0, sticky="ew", padx=(4, 0), pady=0) # Use "ew" (east-west) for horizontal sticky

            # Pack the entire card into the scrollable frame
            container_frame.pack(fill=X, padx=10, pady=(10, 5))

            header_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
            header_frame.pack(fill=X, padx=15, pady=12)

            desc_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
            desc_frame.pack(side=LEFT, fill=X, expand=True)

            status_icon_label = ctk.CTkLabel(desc_frame, text="🕒", font=ctk.CTkFont(size=16))
            status_icon_label.pack(side=LEFT, padx=(0, 8))

            desc_label = ctk.CTkLabel(desc_frame, text=f"Task {task_id}: {description}", wraplength=widget.winfo_width() - 200, justify=LEFT, font=ctk.CTkFont(weight="bold"))
            desc_label.pack(side=LEFT, fill=X, expand=True)

            status_badge_label = ctk.CTkLabel(header_frame, text="Pending", font=ctk.CTkFont(size=12, weight="bold"), fg_color=STATUS_COLORS["pending"], text_color="white", corner_radius=12)
            status_badge_label.pack(side=RIGHT, padx=(10, 0), ipady=2, ipadx=8)

            body_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
            body_frame.pack(fill=X, padx=15, pady=(0, 15))

            # --- Standardize Card Height ---
            # Set a fixed height for the command textbox to ensure all cards have a uniform size.
            # The textbox will automatically show a scrollbar if the command content is too long.
            fixed_command_box_height = 80

            cmd_textbox = ctk.CTkTextbox(
                body_frame,
                font=self.text_tags["code"]["font"],
                fg_color="#1A1A1A",
                border_width=0,
                corner_radius=6,
                height=fixed_command_box_height  # <-- ADD THIS LINE
            )
            cmd_textbox.insert("1.0", command)
            cmd_textbox.configure(state="disabled") # Make it read-only
            cmd_textbox.pack(fill=X, expand=True)

            actions_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
            actions_frame.pack(fill=X, padx=15, pady=(0, 15))

            button_container = ctk.CTkFrame(actions_frame, fg_color="transparent")
            button_container.pack(side=RIGHT)

            def copy_cmd(button_ref: ctk.CTkButton, text_to_copy: str):
                try:
                    self.master.clipboard_clear()
                    self.master.clipboard_append(text_to_copy)
                    original_color = button_ref.cget("fg_color")
                    button_ref.configure(text="Copied!", fg_color="#2ECC71")
                    def restore_button():
                        if button_ref.winfo_exists():
                            button_ref.configure(text="Copy", fg_color=original_color)
                    self.master.after(2000, restore_button)
                except tk.TclError as e:
                    logger.error(f"Clipboard error: {e}")
                    button_ref.configure(text="Error")
                    self.master.after(2000, lambda: button_ref.configure(text="Copy"))

            copy_button = ctk.CTkButton(button_container, text="Copy", width=40, command=lambda: copy_cmd(copy_button, command), fg_color="transparent", border_color="#4A4A4A", border_width=1, hover_color="#555555")
            copy_button.pack(side=LEFT, padx=(0, 10))

            run_button = ctk.CTkButton(button_container, text="Run Command", fg_color="#0078D4", hover_color="#0098FF", font=ctk.CTkFont(weight="bold"))
            run_button.pack(side=LEFT)

            ui_widgets = {
                "container": container_frame, "status_icon": status_icon_label,
                "status_badge": status_badge_label, "run_button": run_button,
                "copy_button": copy_button,
            }

            run_button.configure(command=partial(self._trigger_command_execution, task_id, command, ui_widgets, copy_button))

        except Exception as e:
            logger.exception(f"Error displaying command task {task_id}: {e}")
            event = self.command_exec_events.get(task_id)
            if event:
                self.command_exec_results[task_id] = (False, f"UI Error displaying command: {e}")
                event.set()

    def _trigger_command_execution(self, task_id: str, command: str, ui_widgets: Dict[str, ctk.CTkBaseClass], copy_button: ctk.CTkButton):
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
        exec_thread = threading.Thread(target=self._execute_command_ui_thread, args=(task_id, command, event_to_signal, ui_widgets, None), daemon=True)
        exec_thread.start()

    def _execute_command_ui_thread(self, task_id: str, command: str, event_to_signal: threading.Event, ui_widgets: Dict[str, ctk.CTkBaseClass], skip_button: Optional[ctk.CTkButton]):
        """
        The target function for the background thread that executes a single command.

        It uses `subprocess.Popen` to run the command securely, streams its stdout/stderr
        back to the UI via the queue, and finally stores the result and signals the
        waiting `WorkflowManager` thread via the provided event.
        """
        """
        Target function for the background thread that executes a command requested by the UI.
        Uses subprocess.Popen with shell=False and a list of arguments.
        Streams output via the UI queue.
        Signals completion (success or failure) back to the waiting workflow thread via the event.

        Args:
            task_id: The unique ID for this command task.
            command: The command string to execute (will be parsed).
            event_to_signal: The threading.Event object to signal upon completion.
            ui_widgets: A dictionary of UI widgets associated with the task card for state updates.
            skip_button: Reference to the 'Skip' button widget (for UI updates).
        """
        success = False
        start_time = time.time()

        # --- Update UI to "Running" state immediately ---
        if ui_widgets:
            updates = [
                {"widget_ref": ui_widgets.get("container"), "config": {"fg_color": STATUS_COLORS["running"]}},
                {"widget_ref": ui_widgets.get("status_icon"), "config": {"text": "⚙️"}},
                {"widget_ref": ui_widgets.get("status_badge"), "config": {"text": "Running", "fg_color": STATUS_COLORS["running"]}},
                {"widget_ref": ui_widgets.get("run_button"), "config": {"text": "Running...", "state": "disabled"}},
                {"widget_ref": ui_widgets.get("copy_button"), "config": {"state": "disabled"}},
            ]
            self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_updates": updates}))

        cwd_at_execution = str(self.command_executor.project_root) if self.command_executor else "Unknown"
        return_code = -1 # Initialize return_code to a default failure value
        # output = "" # This variable seems unused after the refactor. Consider removing.
        # Initialize lists before the try block to ensure they are always defined
        full_output_lines: List[str] = [] # Store all output lines for potential error reporting
        stdout_lines: List[str] = [] # Initialize stdout lines list
        stderr_lines: List[str] = [] # Initialize stderr lines list
        popen_args: List[str] = [] # Initialize popen_args list
        process = None # Initialize process variable
        command_parts: List[str] = [] # Initialize command_parts
        structured_error: Optional[Dict[str, Any]] = None # For structured error JSON

        # --- NEW: Check for noisy commands to suppress verbose UI output ---
        is_pip_install = "pip" in command and "install" in command

        # --- Stream Output via UI Queue ---
        def stream_output_line(line: str, is_stderr: bool = False):
            log_prefix = "[CMD ERR]" if is_stderr else "[CMD OUT]"
            # Suppress verbose pip install logs from the UI, but still log them to the console/file
            if is_pip_install and not ("Successfully installed" in line or "Collecting" in line or is_stderr):
                logger.debug(f"UI_SUPPRESSED {log_prefix} {line}")
            else:
                self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"command_output": f"{log_prefix} {line}"}))
            full_output_lines.append(f"{log_prefix} {line}")
        # --- END NEW ---

        try:
            if not self.command_executor:
                raise RuntimeError("CommandExecutor component is not initialized.")
            if not self.command_executor.project_root:
                raise RuntimeError("CommandExecutor project root is not set.")

            # --- Prepare Command Execution ---
            original_command_string = command.strip()
            if not original_command_string:
                raise ValueError("Command string is empty.")

            try:
                is_windows = platform.system() == "Windows"
                command_parts = shlex.split(original_command_string, posix=not is_windows)
                if not command_parts: raise ValueError("Command string resulted in empty parts after parsing.")
            except ValueError as parse_e:
                raise ValueError(f"Invalid command format: {parse_e}") from parse_e
            # --- Apply CommandExecutor's venv logic to command_parts ---
            if self.command_executor and command_parts:
                command_key_to_check = self.command_executor._get_base_command_key(command_parts[0])
                # Commands that should prefer venv executables
                if command_key_to_check in ["python", "pip", "django-admin", "gunicorn", "flask"]: # Added flask
                    venv_exe_path = self.command_executor._get_venv_executable(command_key_to_check)
                    if venv_exe_path:
                        logger.info(f"UI Executor: Using venv executable for '{command_key_to_check}': {venv_exe_path}")
                        command_parts[0] = str(venv_exe_path)
                    else:
                        logger.warning(f"UI Executor: Venv not found or '{command_key_to_check}' not in venv. Using system command '{command_parts[0]}'.")
            # --- End venv logic application ---

            # --- ALWAYS USE shell=False ---
            needs_shell = False
            popen_args: List[str] = command_parts
            cwd = self.command_executor.project_root

            # --- Calculate command_key FIRST ---
            # This needs to happen before checking against windows_builtins or restricted commands
            command_key = self.command_executor._get_base_command_key(command_parts[0])

            # --- Basic Pre-Validation for UI-triggered commands ---
            # Block shell pipelines if shell=False is intended (which it always is now)
            # Check the original string as shlex might parse pipes differently depending on context
            if any(char in original_command_string for char in ['|', '>', '<', '&&', '||', ';']):
                logger.error(f"Blocked UI command: Contains shell metacharacters: {original_command_string}")
                raise ValueError(f"Test step command contains shell metacharacters and is not allowed: {original_command_string}")

            # Check against CommandExecutor's restricted list for manage.py
            if command_key == "python" and len(command_parts) > 2 and command_parts[1] == "manage.py":
                sub_command = command_parts[2]
                if sub_command in self.command_executor.restricted_manage_py:
                    logger.error(f"Blocked UI command: Restricted manage.py subcommand '{sub_command}' in '{original_command_string}'")
                    raise ValueError(f"Test step command uses a restricted manage.py subcommand: {sub_command}")
            # --- End Basic Pre-Validation ---

            # --- FIX for Windows Built-ins with shell=False ---
            # Prepend 'cmd /c' for known Windows shell built-ins
            windows_builtins = {"dir", "type", "echo", "copy", "move", "del", "mkdir", "rmdir"}
            if is_windows and command_key in windows_builtins:
                logger.info(f"Prepending 'cmd /c' for Windows built-in command: {command_key}")
                # Prepend 'cmd' and '/c' to the beginning of the argument list
                popen_args = ['cmd', '/c'] + popen_args

            # --- NEW: Proactively create .gitignore BEFORE git init runs ---
            if 'git init' in command and self.project_root and not (Path(self.project_root) / ".gitignore").exists():
                logger.info("Command is 'git init', proactively creating .gitignore file before execution.")
                try:
                    if self.file_system_manager:
                        gitignore_content = """# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]
*$py.class$

# Virtual Environments
venv/
.venv/
"""
                        self.file_system_manager.write_file(".gitignore", gitignore_content)
                        self.add_message("System", "Created .gitignore to exclude venv and other temporary files.")
                except Exception as e:
                    logger.error(f"Failed to create .gitignore file before git init: {e}", exc_info=True)
                    self.add_message("System", f"Warning: Failed to create .gitignore file: {e}", tag="warning")

            # --- Ensure paths for specific commands are correctly formatted using pathlib ---
            # Check if it's the py_compile command
            is_py_compile_cmd = (command_key == "python" and len(command_parts) >= 4 and
                                 command_parts[1] == "-m" and command_parts[2] == "py_compile")

            if is_py_compile_cmd:
                try:
                    path_arg_index_in_command_parts = 3 # Path is the 4th element in the original command_parts
                    
                    path_arg_in_popen_args_index = path_arg_index_in_command_parts
                    if popen_args[0:2] == ['cmd', '/c']: # Check if 'cmd /c' was prepended
                        path_arg_in_popen_args_index += 2
                    
                    if path_arg_in_popen_args_index < len(popen_args):
                        original_path_arg_from_popen = popen_args[path_arg_in_popen_args_index]
                        if self.command_executor: # Make sure command_executor is available
                            resolved_path_obj = (self.command_executor.project_root / original_path_arg_from_popen).resolve()
                            resolved_path_obj.relative_to(self.command_executor.project_root)
                            formatted_path = str(resolved_path_obj) 
                            popen_args[path_arg_in_popen_args_index] = formatted_path
                            logger.info(f"Using resolved absolute path for py_compile (shell=False): '{formatted_path}' from original '{original_path_arg_from_popen}'")
                        else:
                            logger.warning("CommandExecutor not available in UI thread for py_compile path resolution. Using original path.")
                    else:
                        logger.warning(f"Path argument index {path_arg_in_popen_args_index} out of bounds for py_compile in popen_args: {popen_args}")

                except (ValueError, IndexError) as e: # Added IndexError
                    logger.warning(f"Could not process path argument for py_compile: {e}")
            
            is_type_cmd_windows = (platform.system() == "Windows" and
                                   len(command_parts) == 2 and
                                   (command_parts[0].lower() == "type" or command_parts[0].lower() == "type.exe")) 
            
            if is_type_cmd_windows:
                original_path_arg_index_in_command_parts = 1
                path_arg_in_popen_args_index = original_path_arg_index_in_command_parts
                if popen_args[0:2] == ['cmd', '/c']:
                     path_arg_in_popen_args_index += 2 
                
                if path_arg_in_popen_args_index < len(popen_args):
                    original_path_arg_from_popen = popen_args[path_arg_in_popen_args_index]
                    try:
                        if self.command_executor: # Ensure command_executor is available
                            # For 'type', we want to resolve the path fully and ensure it's within project root
                            resolved_path_obj = (self.command_executor.project_root / original_path_arg_from_popen).resolve()
                            resolved_path_obj.relative_to(self.command_executor.project_root) # Security check
                            # Format for Windows 'type' command (backslashes)
                            formatted_path = str(resolved_path_obj).replace('/', '\\')
                            popen_args[path_arg_in_popen_args_index] = formatted_path
                            logger.info(f"Using resolved path with backslashes for 'type' (shell=False): '{formatted_path}' from original '{original_path_arg_from_popen}'")
                        else:
                            # Fallback if command_executor is not available (less ideal)
                            logger.warning("CommandExecutor not available for 'type' path resolution. Using original path with backslash normalization.")
                            formatted_path = original_path_arg_from_popen.replace('/', '\\')
                            popen_args[path_arg_in_popen_args_index] = formatted_path
                    except ValueError as ve: # Path outside root
                        logger.error(f"Path for 'type' '{original_path_arg_from_popen}' resolves outside project root: {ve}. Command will likely fail.")
                        # Let it proceed, Popen will likely fail with FileNotFoundError
                    except Exception as e: # Other path processing errors
                        logger.warning(f"Could not resolve/normalize path argument '{original_path_arg_from_popen}' for 'type': {e}. Using original with backslashes.")
                        popen_args[path_arg_in_popen_args_index] = original_path_arg_from_popen.replace('/', '\\') # Fallback
                else:
                    logger.warning(f"Path argument index {path_arg_in_popen_args_index} out of bounds for 'type' in popen_args: {popen_args}")

            # --- FIX for Windows 'dir' command path arguments ---
            is_dir_cmd_windows = (platform.system() == "Windows" and
                                  len(command_parts) >= 1 and # dir can have 0 or 1 path arg
                                  (command_parts[0].lower() == "dir" or command_parts[0].lower() == "dir.exe"))

            if is_dir_cmd_windows and len(popen_args) > (2 if popen_args[0:2] == ['cmd', '/c'] else 0): # Check if there's a path arg
                path_arg_idx_in_popen = -1
                # Find the path argument (it's usually the last non-flag argument)
                for i_arg in range(len(popen_args) -1, 0, -1): # Iterate backwards from end
                    if not popen_args[i_arg].startswith(('-', '/')): # Not a flag
                        path_arg_idx_in_popen = i_arg
                        break
                
                if path_arg_idx_in_popen != -1:
                    original_dir_path_arg = popen_args[path_arg_idx_in_popen]
                    # Normalize slashes to backslashes and remove trailing slash for 'dir'
                    normalized_dir_path = original_dir_path_arg.replace('/', '\\').rstrip('\\')
                    if normalized_dir_path != original_dir_path_arg:
                        popen_args[path_arg_idx_in_popen] = normalized_dir_path
                        logger.info(f"Normalized path for 'dir' command: '{original_dir_path_arg}' -> '{normalized_dir_path}'")
            # --- End FIX for Windows 'dir' ---


            # Platform-specific startup info to hide console window on Windows
            startupinfo = None
            creationflags = 0
            if is_windows:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW

            logger.info(f"Executing command in thread: {repr(popen_args)} (Shell={needs_shell}) in CWD: {cwd}")
            stream_output_line(f"Executing: {' '.join(map(shlex.quote, popen_args))}", is_stderr=False) # Log start

            # --- Start Subprocess ---
            process = subprocess.Popen(
                popen_args, # Pass the potentially modified list of arguments
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding=sys.stdout.encoding or 'utf-8',
                errors='replace',
                bufsize=1,
                shell=needs_shell, # Always False
                startupinfo=startupinfo,
                creationflags=creationflags
            )

            # --- Read Output Streams in Separate Threads ---
            def read_stream(stream, output_list_param, is_stderr_param): # Added params for the specific list and type
                try:
                    if stream:
                        for line in iter(stream.readline, ''):
                            stripped_line = line.strip()
                            stream_output_line(stripped_line, is_stderr_param) # Log to UI queue and full_output_lines
                            output_list_param.append(stripped_line) # Append to the specific list (stdout_lines or stderr_lines)
                        stream.close()
                except Exception as read_err:
                    logger.error(f"Error reading command output stream: {read_err}")
                    # Also log this error to the specific output list if possible
                    error_line = f"[Error reading stream: {read_err}]"
                    stream_output_line(error_line, is_stderr=True) # Log to UI queue and full_output_lines
                    output_list_param.append(error_line) # Append error to the specific list

            stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_lines, False), daemon=True)
            stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_lines, True), daemon=True)
            stdout_thread.start()
            stderr_thread.start()

            stdout_thread.join()
            stderr_thread.join()

            return_code = process.wait()
            logger.info(f"Command process for task {task_id} finished with exit code {return_code}.")
            # Initialize command_is_makemigrations_check before the conditional block
            command_is_makemigrations_check = "manage.py" in command and \
                                            "makemigrations" in command and \
                                            "--check" in command

            # --- Check Exit Code ---

            if command_is_makemigrations_check and return_code in [0, 1]:

                success = True
                output_message_detail = "No changes detected." if return_code == 0 else "Changes detected, migrations would be made."
                output = f"Command 'makemigrations --check' completed (Exit Code {return_code}): {output_message_detail}"
                stream_output_line(f"--- Execution 'makemigrations --check' considered successful (Exit Code: {return_code}): {output_message_detail} ---", is_stderr=False)
            elif return_code == 0:
                success = True
                output = f"Command completed successfully (Exit Code 0)."
                stream_output_line("--- Execution Successful ---", is_stderr=False)
                if ui_widgets:
                    # Update UI to "Success" state
                    self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("container"), "config": {"fg_color": STATUS_COLORS["success"]}}))
                    self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("status_icon"), "config": {"text": "✅"}}))
                    self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("status_badge"), "config": {"text": "Success", "fg_color": STATUS_COLORS["success"]}}))
            else:
                success = False # type: ignore
                full_log = "\n".join(full_output_lines)
                # Attempt to parse a structured error from stderr
                structured_error = self._parse_python_traceback("\n".join(stderr_lines))
                output = f"Command failed with Exit Code {return_code}.\n--- Output Log ---\n{full_log}\n--- End Log ---"
                stream_output_line(f"--- Execution Failed (Exit Code: {return_code}) ---", is_stderr=True)
                if ui_widgets:
                    # Update UI to "Remediating" state
                    self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("container"), "config": {"fg_color": STATUS_COLORS["remediating"]}}))
                    self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("status_icon"), "config": {"text": "🛠️"}})) # Wrench icon
                    self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("status_badge"), "config": {"text": "Remediating...", "fg_color": STATUS_COLORS["remediating"]}}))

        except FileNotFoundError:
            success = False
            # Ensure command_parts is defined before accessing index 0
            executable_name = command_parts[0] if command_parts else "Unknown executable"
            output = f"Command execution error: Executable '{executable_name}' not found. Is it installed and in PATH?"
            logger.error(output)
            stream_output_line(f"--- Execution Error: {output} ---", is_stderr=True)
            if ui_widgets:
                self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("container"), "config": {"fg_color": STATUS_COLORS["error"]}}))
                self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("status_badge"), "config": {"text": "Error", "fg_color": STATUS_COLORS["error"]}}))
        except InterruptedError as e:
            success = False
            output = f"Command execution cancelled: {e}"
            logger.warning(f"Command execution thread cancelled for task {task_id}: {e}")
            if ui_widgets:
                self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("status_badge"), "config": {"text": "Cancelled", "fg_color": STATUS_COLORS["error"]}}))
        except ValueError as e: # Catch validation errors (e.g., blocked commands)
            success = False
            output = f"Command blocked or invalid: {e}"
            logger.error(f"Command execution blocked for task {task_id}: {e}")
            stream_output_line(f"--- Execution Blocked: {e} ---", is_stderr=True)
            if ui_widgets:
                self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("container"), "config": {"fg_color": STATUS_COLORS["error"]}}))
                self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("status_badge"), "config": {"text": "Blocked", "fg_color": STATUS_COLORS["error"]}}))
        except Exception as e:
            success = False
            full_log = "\n".join(full_output_lines)
            output = f"Command execution error: {e}\n--- Output Log ---\n{full_log}\n--- End Log ---"
            logger.exception(f"Command execution thread failed for task {task_id}: {e}")
            stream_output_line(f"--- Execution Error: {e} ---", is_stderr=True)
            if ui_widgets:
                self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("container"), "config": {"fg_color": STATUS_COLORS["error"]}}))
                self.ui_queue.put((QUEUE_MSG_UPDATE_UI, {"internal_update": True, "widget_ref": ui_widgets.get("status_badge"), "config": {"text": "Error", "fg_color": STATUS_COLORS["error"]}}))

        finally:
            if process and process.poll() is None:
                try:
                    logger.warning(f"Command process for task {task_id} still running after completion. Terminating.")
                    process.terminate()
                    process.wait(timeout=1)
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=1)
                except Exception as kill_e:
                    logger.error(f"Error terminating command process for task {task_id}: {kill_e}")

            end_time = time.time()
            # Store comprehensive execution details
            execution_details = {
                "command_str": command, # The original command string passed to this function
                "executed_as": ' '.join(map(shlex.quote, popen_args)) if popen_args else command,
                "success": success,
                "exit_code": return_code if process else -1,
                "stdout": "\n".join(stdout_lines).strip(), # Capture from lists, #Fixed: Added a comma here.
                "stderr": "\n".join(stderr_lines).strip(), # Capture from lists
                "structured_error": structured_error, # Add structured error to the result
                "start_time": start_time,
                "end_time": end_time,
                "cwd": cwd_at_execution
            }
            logger.debug(f"Storing command result for task {task_id}. Details: {execution_details}")
            self.command_exec_results[task_id] = (success, json.dumps(execution_details)) # Serialize dict to string for output
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

    def manage_api_keys(self):
        """Handles the 'Manage API Keys' menu action, allowing users to update or clear stored keys."""
        """Allows the user to enter or clear API keys for all configured providers."""
        if self.is_running:
            messagebox.showwarning("Busy", "Cannot manage API keys while a task is running.", parent=self.master)
            return
        if not self.config_manager:
            messagebox.showerror("Error", "Configuration Manager not initialized.", parent=self.master)
            return
        
        keys_changed = False # Flag to trigger re-initialization

        for provider_id, data in self.config_manager.providers_config.items():
            key_name = data.get("api_key_name") # type: ignore
            display_name = data.get("display_name", provider_id)
            if not key_name:
                continue

            existing_key = retrieve_credential(key_name)
            action = "Update/Clear" if existing_key else "Enter"

            new_key = simpledialog.askstring(
                f"{action} API Key for {display_name}",
                f"Paste your API Key for {display_name}.\n"
                f"Leave blank and click OK to clear the stored key.",
                initialvalue=existing_key if existing_key else "", # type: ignore
                show='*',
                parent=self.master
            )

            if new_key is not None: # User clicked OK
                new_key_stripped = new_key.strip()
                if new_key_stripped:
                    if new_key_stripped != existing_key:
                        try:
                            store_credential(key_name, new_key_stripped)
                            logger.info(f"Stored new API Key for {display_name}.")
                            keys_changed = True
                        except Exception as e:
                            logger.exception(f"Failed to store API Key for {display_name}.")
                            messagebox.showerror("Storage Error", f"Failed to store key for {display_name}: {e}", parent=self.master)
                elif existing_key: # User entered blank, intending to clear an existing key
                    if delete_credential(key_name):
                        logger.info(f"Cleared stored API Key for {display_name}.")
                        keys_changed = True
                    else:
                        messagebox.showerror("Error", f"Failed to clear key for {display_name}. Check logs.", parent=self.master)
            else: # User clicked cancel
                break # Stop asking for other keys if user cancels one

        if keys_changed:
            messagebox.showinfo("Keys Updated", "API keys have been updated. Re-initializing agents.", parent=self.master)
            self.add_message("System", "API keys updated. Re-initializing agents...")
            # Force re-initialization if token changed
            self.status_var.set("Re-initializing agents after token update...")
            self._set_ui_running_state(True)
            self.master.after(50, self._initialize_core_stage2) # Trigger re-init

    def show_about_dialog(self):
        """Displays the 'About' dialog box with application information."""
        """Displays the About dialog box."""
        messagebox.showinfo(
            "About Vebgen AI Agent",
            "Vebgen - AI Agent Development Application\n\n"
            "Version: 0.1.0\n"            "Developed by: Vebgen Team\n\n"
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
