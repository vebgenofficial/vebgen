<a id="core.secure_storage"></a>

# core.secure\_storage

<a id="core.secure_storage.store_credential"></a>

#### store\_credential

```python
def store_credential(key: str, secret: str) -> None
```

Stores a secret securely using the OS credential manager (keyring).

**Arguments**:

- `key` - The identifier for the secret (e.g., "OPENROUTER_API_KEY_TARS").
- `secret` - The actual secret value to store.
  

**Raises**:

- `ValueError` - If the key or secret is invalid (empty).
- `RuntimeError` - If keyring fails to store the credential (backend issue).

<a id="core.secure_storage.retrieve_credential"></a>

#### retrieve\_credential

```python
def retrieve_credential(key: str) -> Optional[str]
```

Retrieves a secret from the OS credential manager (keyring).

**Arguments**:

- `key` - The identifier for the secret to retrieve.
  

**Returns**:

  The retrieved secret string, or None if not found or an error occurred.
  

**Raises**:

- `ValueError` - If the key is invalid (empty).

<a id="core.secure_storage.delete_credential"></a>

#### delete\_credential

```python
def delete_credential(key: str) -> bool
```

Deletes a secret from the OS credential manager (keyring).

**Arguments**:

- `key` - The identifier for the secret to delete.
  

**Returns**:

  True if the deletion was successful or the key didn't exist, False on error.
  

**Raises**:

- `ValueError` - If the key is invalid (empty).

<a id="core.secure_storage.check_keyring_backend"></a>

#### check\_keyring\_backend

```python
def check_keyring_backend()
```

Checks if the keyring backend is accessible and functional by performing
a quick set/get/delete test operation.

Logs information about the backend or potential issues.

**Returns**:

  True if the backend seems okay, False otherwise.

