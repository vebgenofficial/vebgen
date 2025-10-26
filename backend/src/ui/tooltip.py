# backend/src/ui/tooltip.py
import tkinter as tk
from tkinter import ttk
from typing import Optional
class ToolTip:
    """
    Creates a basic tooltip that appears when hovering over a Tkinter widget.
    """
    def __init__(self, widget: tk.Widget, text: str = 'widget info', delay_ms: int = 500):
        """
        Initializes the ToolTip.

        Args:
            widget: The Tkinter widget to attach the tooltip to.
            text: The text content of the tooltip. Can include newlines.
            delay_ms: The delay in milliseconds before the tooltip appears.
        """
        self.widget = widget
        self.text = text
        self.delay = delay_ms
        self.tooltip_window: Optional[tk.Toplevel] = None
        self.id: Optional[str] = None # Stores the after() id

        # Bind mouse events to the widget
        self.widget.bind("<Enter>", self.enter, add='+')
        self.widget.bind("<Leave>", self.leave, add='+')
        self.widget.bind("<ButtonPress>", self.leave, add='+') # Hide tooltip on click

    def enter(self, event=None):
        """Schedules the tooltip to appear after a delay."""
        self.schedule()

    def leave(self, event=None):
        """Unschedules the tooltip and hides it if visible."""
        self.unschedule()
        self.hidetip()

    def schedule(self):
        """Schedules the showtip() method to be called after the delay."""
        self.unschedule() # Cancel any existing schedule
        self.id = self.widget.after(self.delay, self.showtip)

    def unschedule(self):
        """Cancels any pending scheduled call to showtip()."""
        scheduled_id = self.id
        self.id = None
        if scheduled_id:
            try:
                self.widget.after_cancel(scheduled_id)
            except tk.TclError:
                # Ignore error if the widget or after() call no longer exists
                pass

    def showtip(self):
        """Creates and displays the tooltip window."""
        # Don't show if already visible or widget destroyed
        if self.tooltip_window or not self.widget.winfo_exists():
            return

        # Calculate position relative to the widget's screen coordinates
        try:
            # Get widget position relative to the screen root
            x = self.widget.winfo_rootx() + 20 # Offset slightly right
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5 # Offset slightly below
        except tk.TclError:
            # Widget might have been destroyed between scheduling and showing
            return

        # Create a Toplevel window for the tooltip
        self.tooltip_window = tk.Toplevel(self.widget)
        # Remove window decorations (title bar, borders)
        self.tooltip_window.wm_overrideredirect(True)
        # Position the tooltip window
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        # Create the label inside the tooltip window
        # Use a light yellow background and simple font, similar to standard tooltips
        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background="#ffffe0", relief='solid', borderwidth=1,
                         font=("Segoe UI", 9, "normal")) # Consistent font
        label.pack(ipadx=2, ipady=2) # Add internal padding

    def hidetip(self):
        """Destroys the tooltip window if it exists."""
        tw = self.tooltip_window
        self.tooltip_window = None
        if tw and tw.winfo_exists():
            try:
                tw.destroy()
            except tk.TclError:
                # Ignore errors if the window is already gone
                pass

# Example usage (optional, for testing this file directly)
if __name__ == '__main__':
    root = tk.Tk()
    root.title("Tooltip Test")
    root.geometry("300x200")

    style = ttk.Style()
    try:
        style.theme_use('vista') # Or 'clam', 'alt', 'default'
    except tk.TclError:
        pass # Use default if theme not available

    btn = ttk.Button(root, text="Hover over me")
    btn.pack(pady=50, padx=50)
    ToolTip(btn, text="This is a tooltip message!\nIt can span multiple lines.")

    entry = ttk.Entry(root)
    entry.pack(pady=10)
    ToolTip(entry, text="Enter text here.")

    root.mainloop()