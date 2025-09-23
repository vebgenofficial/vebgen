# src/ui/user_action_dialog.py
import tkinter as tk
from tkinter import ttk, messagebox
import platform  # Added platform import
from pathlib import Path # Added to resolve "Path is not defined"

class UserActionDialog(tk.Toplevel):
    """
    A custom modal dialog window designed to prompt the user to perform
    a specific manual action outside the application, typically involving
    running a command in their own terminal.

    Displays instructions, the command string (with a copy button),
    and requires the user to confirm they have performed the action.
    """
    def __init__(self, parent: tk.Misc, title: str, instructions: str, command_string: str):
        """
        Initializes the UserActionDialog.

        Args:
            parent: The parent window (usually the main application window).
            title: The title for the dialog window.
            instructions: Text explaining the action the user needs to perform.
            command_string: The command string the user should copy and run.
        """
        super().__init__(parent)
        self.transient(parent) # Associate with parent window (stays on top)
        self.title(title)
        self.parent = parent
        self.result = False # Default result is False (cancelled or closed)

        # --- Configure Styles (if needed, or rely on main window style) ---
        # You might want to pass the main ttk.Style object or configure styles here
        # style = ttk.Style(self)
        # style.configure(...)

        # --- UI Elements ---
        # Instructions Label: Displays the explanatory text. Wraps long text.
        self.instructions_label = ttk.Label(self, text=instructions, wraplength=450, justify=tk.LEFT, padding=(0, 0, 0, 10))
        self.instructions_label.pack(padx=15, pady=(15, 5), fill=tk.X) # Fill horizontally

        # Frame to hold the command text and copy button
        self.command_frame = ttk.Frame(self)
        self.command_frame.pack(fill=tk.X, padx=15, pady=5)

        # Command Text Area: Displays the command. Read-only.
        # Using Text widget allows multi-line commands if necessary.
        self.command_text = tk.Text(self.command_frame, height=3, wrap=tk.WORD,
                                    font=("Consolas", 9), relief=tk.SUNKEN, borderwidth=1,
                                    padx=5, pady=5) # Add internal padding
        self.command_text.insert(tk.END, command_string)
        self.command_text.config(state=tk.DISABLED) # Make it read-only
        self.command_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Copy Button: Allows user to easily copy the command.
        self.copy_button = ttk.Button(self.command_frame, text="Copy", command=self.copy_command, width=6)
        self.copy_button.pack(side=tk.RIGHT, padx=(5, 0), anchor='center') # Center vertically

        # Frame for action buttons
        self.button_frame = ttk.Frame(self)
        self.button_frame.pack(pady=(15, 15)) # Add more padding below buttons

        # Done Button: User clicks this after performing the action.
        self.done_button = ttk.Button(self.button_frame, text="Done (Action Performed)", command=self.on_done, style='Accent.TButton')
        self.done_button.pack(side=tk.LEFT, padx=10)

        # Cancel Button: User clicks this to skip the action.
        self.cancel_button = ttk.Button(self.button_frame, text="Cancel / Skip", command=self.on_cancel)
        self.cancel_button.pack(side=tk.RIGHT, padx=10)

        # --- Dialog Behavior ---
        self.resizable(False, False) # Prevent resizing
        self.grab_set() # Make the dialog modal (blocks interaction with parent)
        self.protocol("WM_DELETE_WINDOW", self.on_cancel) # Handle closing the window via 'X' button

        # Center the dialog relative to the parent window
        self.update_idletasks() # Ensure window size is calculated
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        dialog_width = self.winfo_width()
        dialog_height = self.winfo_height()
        x = parent_x + (parent_width // 2) - (dialog_width // 2)
        y = parent_y + (parent_height // 2) - (dialog_height // 2)
        self.geometry(f"+{x}+{y}") # Position the dialog

        self.focus_set() # Set focus to the dialog
        self.wait_window(self) # Wait until the dialog is closed (makes it modal)

    def copy_command(self):
        """Copies the command string from the text widget to the clipboard."""
        try:
            self.clipboard_clear()
            command = self.command_text.get("1.0", tk.END).strip()
            if command:
                self.clipboard_append(command)
                # Provide visual feedback by changing button text temporarily
                original_text = self.copy_button.cget("text")
                self.copy_button.config(text="Copied!")
                self.after(1500, lambda: self.copy_button.config(text=original_text))
            else:
                 messagebox.showwarning("Nothing to Copy", "Command field is empty.", parent=self)
        except tk.TclError:
            messagebox.showerror("Clipboard Error", "Could not access system clipboard.", parent=self)
        except Exception as e:
             messagebox.showerror("Error", f"Failed to copy command: {e}", parent=self)

    def on_done(self):
        """Sets the result to True (action performed) and closes the dialog."""
        self.result = True
        self.destroy()

    def on_cancel(self):
        """Sets the result to False (action cancelled/skipped) and closes the dialog."""
        self.result = False
        self.destroy()

# Example usage (optional, for testing this file directly)
if __name__ == '__main__':
    root = tk.Tk()
    root.title("Main App")
    root.geometry("500x200")

    # Apply a theme for better appearance if possible
    style = ttk.Style()
    try:
        # Try common themes
        if 'vista' in style.theme_names(): style.theme_use('vista') # type: ignore
        elif 'clam' in style.theme_names(): style.theme_use('clam')
    except tk.TclError:
        print("Default theme used.") # Use default if themes aren't available

    # Define styles used by the dialog (or ensure they exist in main app)
    style.configure('Accent.TButton', foreground='white', background='#0078D4')
    style.map('Accent.TButton', background=[('active', '#005A9E')])


    def open_dialog():
        title = "Activate Virtual Environment"
        instructions = ("To proceed, please activate the Python virtual environment "
                        "in your terminal. Open your terminal, navigate to the project "
                        "directory, and run the appropriate command below:")
        # Determine command based on platform
        if platform.system() == "Windows":
            command = f"cd /d \"{Path.cwd()}\" && .\\venv\\Scripts\\activate" # Example path
            instructions += "\n(Use Command Prompt or PowerShell)"
        else:
            command = f"cd \"{Path.cwd()}\" && source venv/bin/activate" # Example path
            instructions += "\n(Use bash, zsh, etc.)"

        print("Opening dialog...")
        dialog = UserActionDialog(root, title, instructions, command)
        print(f"Dialog result: {dialog.result}") # Print True if Done, False if Cancelled

    btn = ttk.Button(root, text="Show User Action Dialog", command=open_dialog)
    btn.pack(pady=30)
    root.mainloop()