# 🎨 UI Components - Essential Documentation

## 🎯 Overview

**Directory**: `src/ui/`  
**Files**: 3 custom UI components (194 KB total)  
**Purpose**: User interface elements that enable **interactive workflows** and **user-friendly feedback**

VebGen's UI is built with **Tkinter/CustomTkinter** to provide a native desktop experience. These components solve critical UX challenges that make VebGen easy to use even for non-technical users.

---

## 📂 Component Architecture

```text
src/ui/
├── main_window.py        ← Main application window (182 KB)
├── user_action_dialog.py ← Modal for manual commands (7.7 KB)
└── tooltip.py            ← Hover hints (4.4 KB)
```

---

## 🎯 Key Components (Value-Added Only)

### 1. UserActionDialog - Manual Command Execution

**File**: `user_action_dialog.py` (7.7 KB)  
**Purpose**: **Critical bridge** between VebGen's automation and user's terminal

**Why It Matters**:
Some commands **require the user's terminal environment** (activated venvs, environment variables, shells). This dialog provides a **copy-paste workflow** instead of failing silently.

**The Problem It Solves**:
> ❌ Without UserActionDialog:
> ```python
> subprocess.run("source venv/bin/activate && pip install -r requirements.txt")
> ```
> Result: FAILS! Can't activate venv in subprocess

> ✅ With UserActionDialog:
> ```python
> dialog = UserActionDialog(
>     parent=window,
>     title="Activate Virtual Environment",
>     instructions="Please activate your venv and install dependencies:",
>     command_string="source venv/bin/activate && pip install -r requirements.txt"
> )
> ```
> Result: User copies command, runs in their terminal, clicks "Done" ✅

**Key Features**:
- **One-click copy** to clipboard (with "Copied!" visual feedback)
- **Modal dialog** (blocks workflow until user confirms)
- **Platform-aware commands** (Windows vs Linux/Mac)
- **Centered positioning** relative to parent window
- **Monospace font** for command display (easy to read)

**Real-World Usage**:
When WorkflowManager needs `pip install`:
```python
def request_command_execution_cb(cmd_id, cmd_string, description):
    """Callback from WorkflowManager to request manual command"""
    dialog = UserActionDialog(
        parent=self.master,
        title=f"Manual Action Required",
        instructions=f"{description}\n\nPlease run this command in your terminal:",
        command_string=cmd_string
    )

    if dialog.result:  # User clicked "Done"
        return True  # Continue workflow
    else:  # User clicked "Cancel"
        return False  # Stop workflow
```

**Benefits**:
✅ **Transparency** - User sees exact command being run  
✅ **Safety** - User controls execution in their environment  
✅ **Flexibility** - Works with any shell/terminal setup  
✅ **Error prevention** - No subprocess environment conflicts  

---

### 2. ToolTip - Contextual Help

**File**: `tooltip.py` (4.4 KB)  
**Purpose**: **Inline documentation** for UI elements without cluttering the interface

**Why It Matters**:
VebGen has **120+ models**, **13 agent prompts**, and complex settings. Tooltips provide **just-in-time help** without overwhelming the UI.

**Key Features**:
- **500ms delay** before showing (prevents accidental triggers)
- **Auto-positioning** (appears below widget, never off-screen)
- **Multi-line support** (can explain complex concepts)
- **Yellow background** (standard tooltip appearance)
- **Auto-hide on click** (doesn't interfere with interactions)

**Real-World Usage**:
Settings screen tooltips:
```python
ToolTip(
    widget=model_dropdown,
    text="Select the AI model for CASE agent.\n\n"
         "Recommended: gpt-4o (balanced speed/quality)\n"
         "Budget: gpt-4o-mini (faster, cheaper)\n"
         "Advanced: claude-sonnet-4 (best reasoning)",
    delay_ms=500
)

ToolTip(
    widget=temperature_slider,
    text="Controls AI creativity:\n"
         "0.0 = Deterministic, consistent code\n"
         "0.5 = Balanced (recommended)\n"
         "1.0 = Creative, experimental",
    delay_ms=500
)

ToolTip(
    widget=framework_dropdown,
    text="Django: Fully supported (166 KB prompts)\n"
         "Flask/React/Node: Coming in 2-3 weeks",
    delay_ms=500
)
```

**Benefits**:
✅ **Discoverability** - Users learn features naturally  
✅ **No clutter** - Help appears only when needed  
✅ **Context-aware** - Explains the exact setting user is hovering over  
✅ **Reduces support load** - Self-documenting interface  

---

### 3. MainWindow - Application Shell

**File**: `main_window.py` (182 KB)  
**Purpose**: Main application window and orchestration hub

**Only Documenting Key Value-Adding Features** (not entire 182 KB!):

#### A. Real-Time Progress Display

**The Problem**: Users need to know what TARS/CASE are doing

**The Solution**: Live progress updates in UI
```python
def update_progress(self, data: Dict[str, Any]):
    """Display progress updates from WorkflowManager"""
    message = data.get("message", "")

    # Update status label
    self.status_label.config(text=f"Status: {message}")

    # Append to output textbox with color coding
    if "error" in message.lower():
        self.output_text.insert(tk.END, f"❌ {message}\n", "error")
    elif "success" in message.lower():
        self.output_text.insert(tk.END, f"✅ {message}\n", "success")
    else:
        self.output_text.insert(tk.END, f"📝 {message}\n", "info")
```

**Benefits**:
✅ **Transparency** - User sees every step TARS/CASE takes  
✅ **Trust** - Real-time feedback builds confidence  
✅ **Debugging** - Easy to spot where failures occur  

---

#### B. Graceful Shutdown Protection

**The Problem**: User closes window mid-feature → corrupted project state

**The Solution**: Confirmation dialog if workflow running
```python
def on_closing(self):
    """Handle window close event with safety check"""
    if self.is_running:
        # Confirm exit if task running
        if messagebox.askyesno(
            "Confirm Exit",
            "A task is currently running. Exiting now might leave the project "
            "in an inconsistent state.\n\nAre you sure you want to exit?",
            parent=self.master
        ):
            logger.warning("User force-closed during workflow")
            self.master.destroy()
        else:
            return # Cancel exit
    else:
        self.master.destroy() # Safe to exit
```

**Benefits**:
✅ **Data safety** - Prevents accidental interruptions  
✅ **User awareness** - Warns about consequences  
✅ **Professional UX** - Similar to IDEs like VS Code  

---

#### C. Settings Persistence

**The Problem**: User must re-enter API keys and settings on each restart

**The Solution**: Save settings to `config.json` and OS keyring
```python
def save_settings(self):
    """Save UI settings to config file and secure storage"""
    # Save non-sensitive settings to JSON
    config = {
        "provider": self.provider_var.get(),
        "model": self.model_var.get(),
        "temperature": self.temperature_var.get(),
        "framework": self.framework_var.get(),
        "last_project_path": self.project_path_var.get()
    }

    with open(self.config_file, 'w') as f:
        json.dump(config, f, indent=2)

    # Save API keys to secure OS keyring (not JSON!)
    store_credential("OPENAI_API_KEY", self.openai_key_var.get())
    store_credential("ANTHROPIC_API_KEY", self.anthropic_key_var.get())
```

**Benefits**:
✅ **Convenience** - One-time setup  
✅ **Security** - API keys never in plain text files  
✅ **Seamless UX** - Settings remembered across sessions  

---

#### D. Dynamic Model Management (NEW in v0.3.0)

**The Problem**: New AI models are released frequently. Users shouldn't have to manually edit `providers.json` every time OpenAI or Google releases a new model like `gpt-5` or `gemini-2.5-pro`.

**The Solution**: A "Manage" button next to the model selection dropdown that opens a dedicated dialog.

```python
def _open_manage_models_dialog(self):
    """Opens a dialog to add or remove models for the current provider."""
    provider_id = self._get_selected_provider_id()
    # ... create dialog ...

def add_model(self):
    # Calls config_manager.add_model_to_provider(...)
    # Refreshes UI lists

def remove_model(self, model_id):
    # Calls config_manager.remove_model_from_provider(...)
    # Refreshes UI lists
```

**Benefits**:
✅ **Future-Proof** - Users can add new models the day they are released.
✅ **Customization** - Users can remove models they don't use to declutter the list.
✅ **User-Friendly** - No need to find and edit configuration files.
✅ **Safe** - Prevents users from accidentally breaking the `providers.json` format.

---

## 📊 Component Value Matrix

| Component | Size | Purpose | User Benefit | Priority |
|-----------|------|---------|--------------|----------|
| **UserActionDialog** | 7.7 KB | Manual command bridge | Enables pip installs, venv activation | 🔴 Critical |
| **ToolTip** | 4.4 KB | Inline help | Self-documenting UI | 🟡 High Value |
| **MainWindow (progress)** | ~5 KB | Real-time feedback | Transparency, trust | 🔴 Critical |
| **MainWindow (shutdown)** | ~2 KB | Safety checks | Data protection | 🔴 Critical |
| **MainWindow (model mgmt)** | ~3 KB | Add/remove models in UI | Future-proofing, customization | 🟡 High Value |
| **MainWindow (settings)** | ~8 KB | Persistence | Convenience, security | 🟡 High Value |

**Total High-Value Code**: ~30 KB out of 194 KB (15% of UI code drives 90%+ of value)

---

## 🧪 Testing (Value-Added Components Only)
VebGen includes 14 focused tests for GUI control logic covering state management, workflow handling, UI updates (queue-based), and dialog interactions. Complex Tkinter widgets are tested manually via end-to-end workflows.

### Run Tests
```bash
pytest src/core/tests/test_main_window.py -v
```
**Expected output:**

```text
TestMainWindowStateManagement::test_set_ui_initial_state ✓
TestMainWindowStateManagement::test_set_ui_project_selected_state ✓
TestMainWindowStateManagement::test_set_ui_running_state_running ✓
TestMainWindowStateManagement::test_set_ui_running_state_stopped_can_continue ✓
TestMainWindowWorkflowHandling::test_handle_start_workflow_new_project ✓
TestMainWindowWorkflowHandling::test_handle_start_workflow_continue_run ✓
TestMainWindowWorkflowHandling::test_handle_stop_workflow ✓
TestMainWindowUIUpdates::test_update_progress_safe_puts_on_queue ✓
TestMainWindowUIUpdates::test_update_ui_elements_sets_status_message ✓
TestMainWindowUIUpdates::test_update_ui_elements_handles_error ✓
TestMainWindowUIUpdates::test_finalize_run_ui_success ✓
TestMainWindowUIUpdates::test_finalize_run_ui_stopped_can_continue ✓
TestMainWindowDialogs::test_handle_dialog_request_input ✓
TestMainWindowDialogs::test_handle_dialog_request_confirmation ✓

14 passed in 0.8s
```
### Test Coverage Breakdown
| Test Class | Tests | Description |
|---|---|---|
| **TestMainWindowStateManagement** | 4 tests | UI state transitions (initial → project selected → running → stopped) |
| **TestMainWindowWorkflowHandling** | 3 tests | Start/stop/continue workflow logic, thread spawning |
| **TestMainWindowUIUpdates** | 5 tests | Queue-based UI updates, status bar, error handling, finalization |
| **TestMainWindowDialogs** | 2 tests | User input dialogs, confirmation dialogs (threading-safe) |
| **Total:** | **14 tests** | with 100% pass rate |

**Note**: Complex Tkinter widgets (CTkTextbox, CTkScrollbar, syntax highlighting) are tested manually through end-to-end workflows to ensure visual correctness.

### Test Categories

#### 1. UI State Management (4 tests)
**Test: `test_set_ui_initial_state`**

```python
def test_set_ui_initial_state(self, main_window: MainWindow):
    """Verify initial state disables interactive widgets"""
    main_window._set_ui_initial_state()
    
    # All inputs disabled
    assert main_window.prompt_entry.configure.call_args.kwargs['state'] == 'disabled'
    assert main_window.send_button.configure.call_args.kwargs['state'] == 'disabled'
    assert main_window.provider_dropdown.configure.call_args.kwargs['state'] == 'disabled'
    assert main_window.model_dropdown.configure.call_args.kwargs['state'] == 'disabled'
    assert main_window.framework_dropdown.configure.call_args.kwargs['state'] == 'disabled'
    
    # Only project selection enabled
    main_window.select_project_button.configure.assert_any_call(state='normal')
```
**Initial UI state:**

```text
[ Select Project ] ← Enabled
[ Framework: ----- ] ← Disabled
[ Provider: ------ ] ← Disabled
[ Model: --------- ] ← Disabled
[ Prompt: -------- ] ← Disabled
[ ▶️ Start ] ← Disabled
```
**Test: `test_set_ui_project_selected_state`**

```python
def test_set_ui_project_selected_state(self, main_window: MainWindow):
    """Verify selecting a project enables framework/provider selection"""
    main_window.available_frameworks = ["django", "flask"]
    main_window._set_ui_project_selected_state()
    
    # Inputs enabled
    assert main_window.prompt_entry.configure.call_args.kwargs['state'] == 'normal'
    assert main_window.provider_dropdown.configure.call_args.kwargs['state'] == 'readonly'
    assert main_window.framework_dropdown.configure.call_args.kwargs['state'] == 'readonly'
    
    # Send button remains disabled until Stage 2 init completes
    assert main_window.send_button.configure.call_args.kwargs['state'] == 'disabled'
```
**After project selection:**

```text
[ /home/user/my_project ] ← Selected
[ Framework: Django ▼ ] ← Enabled (readonly)
[ Provider: OpenAI ▼ ] ← Enabled (readonly)
[ Model: gpt-4 ▼ ] ← Enabled (readonly)
[ Prompt: Create a blog ] ← Enabled
[ ▶️ Start ] ← Enabled (after init)
```
**Test: `test_set_ui_running_state_running`**

```python
def test_set_ui_running_state_running(self, main_window: MainWindow):
    """Verify UI is disabled when workflow is running"""
    main_window.is_running = True
    main_window._set_ui_running_state(True)
    
    # Send button becomes "Stop" button
    main_window.send_button.configure.assert_any_call(
        text='⏹️ Stop', 
        state='normal', 
        fg_color=ANY, 
        hover_color=ANY
    )
    
    # All other controls disabled
    assert main_window.prompt_entry.configure.call_args.kwargs['state'] == 'disabled'
    assert main_window.provider_dropdown.configure.call_args.kwargs['state'] == 'disabled'
    assert main_window.select_project_button.configure.call_args.kwargs['state'] == 'disabled'
```
**During workflow execution:**

```text
[ /home/user/my_project ] ← Disabled
[ Framework: Django ] ← Disabled
[ Provider: OpenAI ] ← Disabled
[ Model: gpt-4 ] ← Disabled
[ Prompt: -------- ] ← Disabled
[ ⏹️ Stop ] ← Enabled (only control)
```
**Test: `test_set_ui_running_state_stopped_can_continue`**

```python
def test_set_ui_running_state_stopped_can_continue(self, main_window: MainWindow):
    """Verify UI shows 'Continue' button after graceful stop"""
    main_window.is_running = False
    main_window.is_continuing_run = True
    main_window._set_ui_running_state(False)
    
    # Send button becomes "Continue" button
    main_window.send_button.configure.assert_any_call(
        text='▶️ Continue', 
        state='normal', 
        fg_color=ANY, 
        hover_color=ANY
    )
    
    # Prompt entry remains disabled (no new feature needed)
    assert main_window.prompt_entry.configure.call_args.kwargs['state'] == 'disabled'
```
**After graceful stop (continuable state):**

```text
[ /home/user/my_project ] ← Enabled
[ Framework: Django ] ← Enabled
[ Provider: OpenAI ] ← Enabled
[ Model: gpt-4 ] ← Enabled
[ Prompt: -------- ] ← Disabled
[ ▶️ Continue ] ← Enabled (resumes workflow)
```
#### 2. Workflow Handling (3 tests)
**Test: `test_handle_start_workflow_new_project`**

```python
@patch('src.ui.main_window.threading.Thread')
def test_handle_start_workflow_new_project(self, mock_thread, main_window: MainWindow):
    """Test starting workflow for new project"""
    main_window.core_components_initialized = True
    main_window.is_new_project.set(True)
    main_window.prompt_entry.get.return_value = "Create a blog"
    main_window.framework_var.set("django")
    main_window.project_root = "/fake/project"
    main_window.send_button.cget.return_value = "▶️ Start"
    
    main_window.handle_start_workflow()
    
    # Verify correct thread target
    mock_thread.assert_called_once_with(
        target=main_window._run_initial_workflow_thread,
        args=("Create a blog", "django", True),
        daemon=True
    )
    
    assert main_window.is_running is True
```
**Test: `test_handle_start_workflow_continue_run`**

```python
@patch('src.ui.main_window.threading.Thread')
def test_handle_start_workflow_continue_run(self, mock_thread, main_window: MainWindow):
    """Test continuing previously stopped workflow"""
    main_window.core_components_initialized = True
    main_window.is_continuing_run = True
    main_window.send_button.cget.return_value = "▶️ Continue"
    main_window.prompt_entry.get.return_value = ""  # No new prompt
    main_window.framework_var.set("django")
    
    main_window.handle_start_workflow()
    
    # Verify continuation thread
    mock_thread.assert_called_once_with(
        target=main_window._run_new_feature_thread,
        args=("",),  # Empty prompt signals continuation
        daemon=True
    )
    
    assert main_window.is_running is True
```
**Test: `test_handle_stop_workflow`**

```python
def test_handle_stop_workflow(self, main_window: MainWindow):
    """Test stop handler calls workflow manager's stop method"""
    main_window.is_running = True
    main_window.workflow_manager_instance = MagicMock()
    
    main_window.handle_stop_workflow()
    
    main_window.workflow_manager_instance.request_stop.assert_called_once()
```
**Workflow thread spawning logic:**

New project → `_run_initial_workflow_thread(prompt, framework, is_new)`

Continue run → `_run_new_feature_thread("")` (empty prompt)

Stop → `workflow_manager.request_stop()`

#### 3. UI Updates (Queue-Based) (5 tests)
**Test: `test_update_progress_safe_puts_on_queue`**

```python
def test_update_progress_safe_puts_on_queue(self, main_window: MainWindow):
    """Verify update_progress_safe queues messages correctly"""
    progress_data = {"message": "Testing queue"}
    
    main_window.update_progress_safe(progress_data)
    
    # Verify queue contains message
    assert not main_window.ui_queue.empty()
    msg_type, data = main_window.ui_queue.get()
    
    assert msg_type == QUEUE_MSG_UPDATE_UI
    assert data == progress_data
```
**Queue-based UI update workflow:**

```text
Backend Thread                  Main Thread (UI)
     |                                |
     | progress_data                  |
     |---> ui_queue.put() --------->  |
     |                                |
     |                          poll_queue()
     |                          _update_ui_elements()
     |                          status_var.set()
```
**Test: `test_update_ui_elements_sets_status_message`**

```python
def test_update_ui_elements_sets_status_message(self, main_window: MainWindow):
    """Verify _update_ui_elements updates status bar"""
    main_window.status_var = MagicMock()
    progress_data = {"message": "New status"}
    
    main_window._update_ui_elements(progress_data)
    
    main_window.status_var.set.assert_called_once_with("New status")
```
**Test: `test_update_ui_elements_handles_error`**

```python
def test_update_ui_elements_handles_error(self, main_window: MainWindow):
    """Verify 'issue' in progress data is logged as error"""
    main_window.status_var = MagicMock()
    main_window.add_log_message = MagicMock()
    progress_data = {"issue": "Something went wrong"}
    
    main_window._update_ui_elements(progress_data)
    
    main_window.status_var.set.assert_called_once_with("Notice: Something went wrong...")
    main_window.add_log_message.assert_called_with("ERROR", "System", "Something went wrong")
```
**Error handling:**

`{"message": "..."}` → Status bar update

`{"issue": "..."}` → Error log + status bar notice

**Test: `test_finalize_run_ui_success`**

```python
def test_finalize_run_ui_success(self, main_window: MainWindow):
    """Verify UI is re-enabled after successful run"""
    main_window.is_running = True
    main_window.core_components_initialized = True
    main_window.project_root = "/fake/project"
    main_window.framework_var.set("django")
    main_window.workflow_manager_instance.can_continue.return_value = None
    
    main_window._finalize_run_ui(success=True)
    
    assert main_window.is_running is False
    assert main_window.is_continuing_run is False
    
    # UI unlocked
    main_window.send_button.configure.assert_any_call(
        text='▶️ Start', 
        state='normal', 
        fg_color=ANY, 
        hover_color=ANY
    )
    
    assert "Workflow finished successfully" in main_window.status_var.get()
```
**Test: `test_finalize_run_ui_stopped_can_continue`**

```python
def test_finalize_run_ui_stopped_can_continue(self, main_window: MainWindow):
    """Verify UI is set to 'Continue' after graceful stop"""
    main_window.is_running = True
    main_window.project_root = "/fake/project"
    main_window.framework_var.set("django")
    main_window.workflow_manager_instance.can_continue.return_value = MagicMock(name="In-progress Feature")
    
    main_window._finalize_run_ui(success=False, stopped=True)
    
    assert main_window.is_running is False
    assert main_window.is_continuing_run is True
    
    # UI shows "Continue" button
    main_window.send_button.configure.assert_any_call(
        text='▶️ Continue', 
        state='normal', 
        fg_color=ANY, 
        hover_color=ANY
    )
    
    assert "Ready to continue feature" in main_window.status_var.get()
```
**Finalization logic:**

`success=True` → Reset to "Start" state

`stopped=True` + `can_continue()` → Set to "Continue" state

#### 4. Dialog Interactions (2 tests)
**Test: `test_handle_dialog_request_input`**

```python
def test_handle_dialog_request_input(self, main_window: MainWindow):
    """Verify 'input' dialog request calls simpledialog"""
    event = threading.Event()
    dialog_data = {
        "type": "input",
        "title": "Test Input",
        "prompt": "Enter value:",
        "is_password": True,
        "event": event
    }
    
    main_window.mock_simpledialog.askstring.return_value = "secret_value"
    
    main_window._handle_dialog_request(dialog_data)
    
    main_window.mock_simpledialog.askstring.assert_called_once_with(
        "Test Input", "Enter value:", show='*', parent=main_window.master
    )
    
    assert main_window.dialog_result == "secret_value"
    assert event.is_set()
```
**Dialog workflow (thread-safe):**

```text
Backend Thread               Main Thread (UI)
     |                              |
     | request_user_input()         |
     |---> dialog_queue.put() ---->  |
     | event.wait() ← BLOCKS         |
     |                        show_dialog()
     |                        user_enters_input
     |                        dialog_result = input
     |                        event.set()
     | ← UNBLOCKS                    |
     | return dialog_result          |
```
**Test: `test_handle_dialog_request_confirmation`**

```python
def test_handle_dialog_request_confirmation(self, main_window: MainWindow):
    """Verify 'confirmation' dialog request calls messagebox"""
    event = threading.Event()
    dialog_data = {
        "type": "confirmation",
        "title": "Confirm",
        "prompt": "Are you sure?",
        "event": event
    }
    
    main_window.mock_messagebox.askyesno.return_value = True
    
    main_window._handle_dialog_request(dialog_data)
    
    main_window.mock_messagebox.askyesno.assert_called_once_with(
        "Confirm", "Are you sure?", parent=main_window.master
    )
    
    assert main_window.dialog_result is True
    assert event.is_set()
```
**Dialog types:**

`"input"` → `simpledialog.askstring()` (text input, optional password masking)

`"confirmation"` → `messagebox.askyesno()` (Yes/No buttons)

**Example: `UserActionDialog` (Manual Testing)**
**Copy command functionality:**

```python
def test_user_action_dialog_copy():
    """Test clipboard copy functionality"""
    root = tk.Tk()
    dialog = UserActionDialog(
        parent=root,
        title="Test",
        instructions="Test instructions",
        command_string="pip install django"
    )
    
    dialog.copy_command()
    
    # Verify clipboard contains command
    assert root.clipboard_get() == "pip install django"
```
**Tooltip delayed show:**

```python
def test_tooltip_delayed_show():
    """Test tooltip appears after delay"""
    root = tk.Tk()
    button = ttk.Button(root, text="Test")
    tooltip = ToolTip(button, text="Help text", delay_ms=100)
    
    # Trigger hover
    tooltip.enter()
    
    # Wait for delay
    root.after(150)
    root.update()
    
    # Tooltip should be visible
    assert tooltip.tooltip_window is not None
```
### Why Manual Testing for Complex Widgets?
Complex Tkinter widgets are tested manually because:

- **Visual correctness** - Syntax highlighting, text wrapping, scrollbar behavior require human verification
- **Event simulation complexity** - Tkinter events (mouse hover, scroll, resize) are hard to mock accurately
- **Platform differences** - Rendering varies between Windows/macOS/Linux

**Manually tested components:**

- `CTkTextbox` (chat display with syntax highlighting)
- `CTkScrollbar` (smooth scrolling behavior)
- Custom theme rendering (dark mode support)
- Window resizing and layout management

### Running Specific Test Categories
Test state management only:

```bash
pytest src/core/tests/test_main_window.py::TestMainWindowStateManagement -v
```
Test workflow handling:

```bash
pytest src/core/tests/test_main_window.py::TestMainWindowWorkflowHandling -v
```
Test UI updates:

```bash
pytest src/core/tests/test_main_window.py::TestMainWindowUIUpdates -v
```
Test dialogs:

```bash
pytest src/core/tests/test_main_window.py::TestMainWindowDialogs -v
```
### Test Summary
| Test File | Tests | Pass Rate | Coverage |
|---|---|---|---|
| `test_main_window.py` | 14 | 100% | UI state management, workflow handling, queue-based updates, dialog interactions |

All 14 tests pass consistently, ensuring bulletproof GUI control logic! ✅

### Key Features Validated

✅ **UI State Transitions** - Initial → Project Selected → Running → Stopped/Continue  
✅ **Workflow Control** - Start new project, continue run, graceful stop  
✅ **Queue-Based Updates** - Thread-safe status bar and error handling  
✅ **Dialog Threading** - Thread-safe user input and confirmation dialogs  
✅ **Button State Management** - "Start" → "Stop" → "Continue" transitions  


---

## ✅ Best Practices

### For Users

1. **Read tooltips** - Hover over settings for explanations
2. **Use copy button** - Don't manually type terminal commands
3. **Confirm manual actions** - Click "Done" only after running commands
4. **Check progress window** - Real-time feedback shows what's happening

### For Developers

1. **Keep modals focused** - One action per dialog
2. **Provide visual feedback** - Button text changes ("Copy" → "Copied!")
3. **Center dialogs** - Calculate position relative to parent
4. **Use tooltips strategically** - Complex settings only, not obvious buttons
5. **Persist only safe data** - API keys in keyring, not config files

---

## 🌟 Summary

**3 UI components** provide **critical user experience improvements**, with key features in `MainWindow` delivering much of the value:

✅ **UserActionDialog** (7.7 KB) - Enables manual terminal commands (pip install, venv activation)  
✅ **ToolTip** (4.4 KB) - Self-documenting interface for 120+ models and complex settings  
✅ **MainWindow highlights** (~18 KB) - Real-time progress, shutdown protection, settings persistence, and dynamic model management  

**Key Achievements**:
- **Safety**: Confirms exit if workflow running (prevents data loss)
- **Transparency**: Real-time progress updates (user sees every step)
- **Convenience**: Settings and API keys persisted (one-time setup)
- **Discoverability**: Tooltips explain features (reduces support burden)
- **Flexibility**: Manual command execution and dynamic model management

**This is why VebGen feels polished and professional—these ~30 KB of UI code deliver 90%+ of the UX value.**

---

<div align="center">

**Want to understand the full UI?** Check main_window.py (182 KB)  
**Questions?** See workflow_manager.md for backend orchestration

</div>