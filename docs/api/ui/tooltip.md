<a id="ui.tooltip"></a>

# ui.tooltip

<a id="ui.tooltip.ToolTip"></a>

## ToolTip Objects

```python
class ToolTip()
```

Creates a basic tooltip that appears when hovering over a Tkinter widget.

<a id="ui.tooltip.ToolTip.__init__"></a>

#### \_\_init\_\_

```python
def __init__(widget: tk.Widget,
             text: str = 'widget info',
             delay_ms: int = 500)
```

Initializes the ToolTip.

**Arguments**:

- `widget` - The Tkinter widget to attach the tooltip to.
- `text` - The text content of the tooltip. Can include newlines.
- `delay_ms` - The delay in milliseconds before the tooltip appears.

<a id="ui.tooltip.ToolTip.enter"></a>

#### enter

```python
def enter(event=None)
```

Schedules the tooltip to appear after a delay.

<a id="ui.tooltip.ToolTip.leave"></a>

#### leave

```python
def leave(event=None)
```

Unschedules the tooltip and hides it if visible.

<a id="ui.tooltip.ToolTip.schedule"></a>

#### schedule

```python
def schedule()
```

Schedules the showtip() method to be called after the delay.

<a id="ui.tooltip.ToolTip.unschedule"></a>

#### unschedule

```python
def unschedule()
```

Cancels any pending scheduled call to showtip().

<a id="ui.tooltip.ToolTip.showtip"></a>

#### showtip

```python
def showtip()
```

Creates and displays the tooltip window.

<a id="ui.tooltip.ToolTip.hidetip"></a>

#### hidetip

```python
def hidetip()
```

Destroys the tooltip window if it exists.

