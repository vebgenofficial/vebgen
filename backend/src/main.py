# backend/src/main.py
import sys
import logging
import platform
import customtkinter as ctk
from pathlib import Path # For potential log file path manipulation
import os # For environment variables (used in optional file logging)

# Import the main UI window class
# Ensure the ui package is correctly structured relative to src

try:
    from .ui.main_window import MainWindow
except ImportError as e_initial:
    print(f"Failed to import UI components: {e_initial}", file=sys.stderr)
    print("\nThis script should be run as a module from the 'backend' directory.", file=sys.stderr)
    print("Example: python -m src.main", file=sys.stderr)
    sys.exit(1)


# --- Logging Configuration ---
# Set the desired logging level. DEBUG provides the most detail.
# Change to logging.INFO or logging.WARNING for less verbose output in production.
LOG_LEVEL = logging.DEBUG
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(message)s' # Include thread name

# Configure basic logging to print to the console (stdout)
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, stream=sys.stdout)

# --- Optional: Reduce verbosity of third-party libraries ---
# Set the logging level for noisy libraries like Pillow to a higher level
logging.getLogger('PIL').setLevel(logging.INFO)
# --- End Optional ---

# --- Optional: File Logging ---
# Uncomment and configure this section to log to a file as well.
# This is useful for debugging issues after the application closes.
# try:
#     # Determine a suitable directory for log files based on OS
#     log_dir_base = os.getenv('LOCALAPPDATA') or os.getenv('APPDATA') or Path.home() # App-specific log directory
#     log_dir = Path(log_dir_base) / 'Vebgen' / 'logs'
#     log_dir.mkdir(parents=True, exist_ok=True)
#     log_filename = log_dir / "vebgen_app.log"

#     # Create a file handler
#     # Use 'a' for append mode, 'w' to overwrite each time
#     file_handler = logging.FileHandler(log_filename, encoding='utf-8', mode='a')
#     file_handler.setLevel(LOG_LEVEL) # Set level for the file handler
#     file_handler.setFormatter(logging.Formatter(LOG_FORMAT)) # Apply the same format

#     # Add the file handler to the root logger
#     logging.getLogger().addHandler(file_handler)
#     logging.info(f"--- Log session started. File logging configured to: {log_filename} ---")
# except Exception as e:
#     logging.error(f"Failed to configure file logging: {e}")
# --- End Optional File Logging ---

# Get a logger instance specifically for this main module
logger = logging.getLogger(__name__)

def main():
    """
    Initializes and runs the Vebgen Tkinter application.
    Sets up logging, creates the main window, and starts the event loop.
    Includes basic error handling for application startup.
    """
    logger.info("="*60)
    logger.info("Starting Vebgen - AI Agent Development Application...")
    logger.info(f"Python Version: {sys.version}")
    logger.info(f"Platform: {platform.system()} ({platform.release()}) - {platform.machine()}")
    logger.info(f"Log Level: {logging.getLevelName(LOG_LEVEL)}")
    logger.info("="*60)

    root = None # Initialize root window variable
    try:
        # --- Initialize CustomTkinter Root Window ---
        root = ctk.CTk()

        # --- Instantiate the Main Application Window ---
        # The MainWindow class contains all the UI logic and connects to the core components.
        app = MainWindow(root)

        # --- Start the Tkinter Event Loop ---
        # This call blocks until the main window is closed.
        # It handles UI events, updates, and interactions.
        logger.info("Starting Tkinter main event loop...")
        root.mainloop()

        # --- Application Exit ---
        # This code runs after the main window is closed.
        logger.info("="*60)
        logger.info("Vebgen Application finished normally.")
        logger.info("="*60)

    except Exception as e:
        # --- Fatal Error Handling ---
        # Catch any unhandled exceptions during application startup or runtime.
        logger.critical("An unhandled exception occurred during application execution.", exc_info=True)

        # Attempt to show an error message box if the GUI is still usable.
        if root and root.winfo_exists():
             try:
                 # Import messagebox here to avoid potential issues if ctk itself failed early
                 import tkinter.messagebox
                 tkinter.messagebox.showerror(
                     "Fatal Error",
                     f"A critical error occurred:\n\n{e}\n\nPlease check the application logs for details.",
                     parent=root # Attach to root window if possible
                 )
             except Exception as dialog_e:
                 # Log error if even the dialog fails
                 logger.error(f"Could not display the final error dialog: {dialog_e}")
        else:
             # Fallback to printing to stderr if the GUI is unavailable
             print("\n" + "="*60, file=sys.stderr)
             print("FATAL ERROR: Application failed to start or run.", file=sys.stderr)
             print(f"Error details: {e}", file=sys.stderr)
             print("Please check application logs (if configured) for more information.", file=sys.stderr)
             print("="*60, file=sys.stderr)

        sys.exit(1) # Exit with a non-zero code to indicate an error

# --- Standard Python Entry Point Check ---
if __name__ == "__main__":
    # This ensures the main() function runs only when the script is executed directly
    # (not when imported as a module).
    main()
