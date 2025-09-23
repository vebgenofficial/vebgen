<a id="utils.check_model"></a>

# utils.check\_model

<a id="utils.check_model.check_model_exists"></a>

#### check\_model\_exists

```python
def check_model_exists(app_label: str, model_name: str) -> bool
```

Checks if a model class with the given name exists within the specified app's models.py.
Uses dynamic imports. Assumes the app is importable in the current environment.

