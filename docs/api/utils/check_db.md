<a id="utils.check_db"></a>

# utils.check\_db

<a id="utils.check_db.check_table_exists"></a>

#### check\_table\_exists

```python
def check_table_exists(table_name: str) -> bool
```

Checks if a specific table exists in the default database using Django's introspection API.
Assumes Django settings are configured via environment variables or django.setup().

