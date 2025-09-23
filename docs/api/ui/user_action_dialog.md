<a id="ui.user_action_dialog"></a>

# ui.user\_action\_dialog

<a id="ui.user_action_dialog.UserActionDialog"></a>

## UserActionDialog Objects

```python
class UserActionDialog(tk.Toplevel)
```

A custom modal dialog window designed to prompt the user to perform
a specific manual action outside the application, typically involving
running a command in their own terminal.

Displays instructions, the command string (with a copy button),
and requires the user to confirm they have performed the action.

<a id="ui.user_action_dialog.UserActionDialog.__init__"></a>

#### \_\_init\_\_

```python
def __init__(parent: tk.Misc, title: str, instructions: str,
             command_string: str)
```

Initializes the UserActionDialog.

**Arguments**:

- `parent` - The parent window (usually the main application window).
- `title` - The title for the dialog window.
- `instructions` - Text explaining the action the user needs to perform.
- `command_string` - The command string the user should copy and run.

<a id="ui.user_action_dialog.UserActionDialog.copy_command"></a>

#### copy\_command

```python
def copy_command()
```

Copies the command string from the text widget to the clipboard.

<a id="ui.user_action_dialog.UserActionDialog.on_done"></a>

#### on\_done

```python
def on_done()
```

Sets the result to True (action performed) and closes the dialog.

<a id="ui.user_action_dialog.UserActionDialog.on_cancel"></a>

#### on\_cancel

```python
def on_cancel()
```

Sets the result to False (action cancelled/skipped) and closes the dialog.

