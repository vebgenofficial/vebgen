# c/Users/USER/Documents/webagent/vebgen sharp updated/backend/src/core/tests/test_secure_storage.py
import pytest
from unittest.mock import patch, MagicMock
from keyring.errors import KeyringError, PasswordDeleteError
import keyring

# Import the functions to be tested
from src.core.secure_storage import (
    store_credential,
    retrieve_credential,
    delete_credential,
    check_keyring_backend,
    SERVICE_NAME,
)

# --- Test Cases for store_credential ---

@patch("src.core.secure_storage.keyring")
def test_store_credential_success(mock_keyring: MagicMock):
    """Tests successful storage of a credential."""
    key = "MY_API_KEY"
    secret = " my_secret_value  "
    store_credential(key, secret)
    # Verify that keyring.set_password was called with the correct, stripped secret
    mock_keyring.set_password.assert_called_once_with(
        SERVICE_NAME, key, "my_secret_value"
    )

@patch("src.core.secure_storage.keyring")
def test_store_credential_invalid_key(mock_keyring: MagicMock):
    """Tests that storing with an empty or invalid key raises ValueError."""
    with pytest.raises(ValueError, match="Credential key cannot be empty."):
        store_credential("", "secret")
    with pytest.raises(ValueError, match="Credential key cannot be empty."):
        store_credential(None, "secret") # type: ignore

@patch("src.core.secure_storage.keyring")
def test_store_credential_invalid_secret(mock_keyring: MagicMock):
    """Tests that storing with an empty, whitespace, or invalid secret raises ValueError."""
    with pytest.raises(ValueError, match="Credential secret must be a string."):
        store_credential("key", None) # type: ignore
    with pytest.raises(ValueError, match="Credential secret cannot be empty after stripping."):
        store_credential("key", "")
    with pytest.raises(ValueError, match="Credential secret cannot be empty after stripping."):
        store_credential("key", "   ")

@patch("src.core.secure_storage.keyring")
def test_store_credential_keyring_error(mock_keyring: MagicMock):
    """Tests that a KeyringError during storage is wrapped in a RuntimeError."""
    mock_keyring.set_password.side_effect = KeyringError("Backend unavailable")
    with pytest.raises(RuntimeError, match="Secure storage unavailable: Backend unavailable"):
        store_credential("key", "secret")

# --- Test Cases for retrieve_credential ---

@patch("src.core.secure_storage.keyring")
def test_retrieve_credential_success(mock_keyring: MagicMock):
    """Tests successful retrieval of a credential."""
    key = "MY_API_KEY"
    secret = " my_secret_value  "
    mock_keyring.get_password.return_value = secret

    retrieved_secret = retrieve_credential(key)

    mock_keyring.get_password.assert_called_once_with(SERVICE_NAME, key)
    # Verify that the retrieved secret is stripped
    assert retrieved_secret == "my_secret_value"

@patch("src.core.secure_storage.keyring")
def test_retrieve_credential_not_found(mock_keyring: MagicMock):
    """Tests that retrieving a non-existent credential returns None."""
    mock_keyring.get_password.return_value = None
    assert retrieve_credential("NON_EXISTENT_KEY") is None

@patch("src.core.secure_storage.keyring")
def test_retrieve_credential_empty_stored_secret(mock_keyring: MagicMock):
    """Tests that if a stored secret is just whitespace, it's treated as not found."""
    mock_keyring.get_password.return_value = "   "
    assert retrieve_credential("EMPTY_SECRET_KEY") is None

@patch("src.core.secure_storage.keyring")
def test_retrieve_credential_invalid_key(mock_keyring: MagicMock):
    """Tests that retrieving with an invalid key raises ValueError."""
    with pytest.raises(ValueError, match="Credential key cannot be empty."):
        retrieve_credential("")

@patch("src.core.secure_storage.keyring")
def test_retrieve_credential_keyring_error(mock_keyring: MagicMock):
    """Tests that a KeyringError during retrieval returns None and does not raise."""
    mock_keyring.get_password.side_effect = KeyringError("Backend unavailable")
    assert retrieve_credential("some_key") is None

# --- Test Cases for delete_credential ---

@patch("src.core.secure_storage.keyring")
def test_delete_credential_success(mock_keyring: MagicMock):
    """Tests successful deletion of a credential."""
    key = "KEY_TO_DELETE"
    assert delete_credential(key) is True
    mock_keyring.delete_password.assert_called_once_with(SERVICE_NAME, key)

@patch("src.core.secure_storage.keyring")
def test_delete_credential_not_found(mock_keyring: MagicMock):
    """Tests that deleting a non-existent credential is treated as a success."""
    mock_keyring.delete_password.side_effect = PasswordDeleteError("Not found")
    assert delete_credential("NON_EXISTENT_KEY") is True

@patch("src.core.secure_storage.keyring")
def test_delete_credential_invalid_key(mock_keyring: MagicMock):
    """Tests that deleting with an invalid key raises ValueError."""
    with pytest.raises(ValueError, match="Credential key cannot be empty."):
        delete_credential("")

@patch("src.core.secure_storage.keyring")
def test_delete_credential_keyring_error(mock_keyring: MagicMock):
    """Tests that a generic KeyringError during deletion returns False."""
    mock_keyring.delete_password.side_effect = KeyringError("Backend unavailable")
    assert delete_credential("some_key") is False

# --- Test Cases for check_keyring_backend ---

@patch("src.core.secure_storage.keyring")
def test_check_keyring_backend_success(mock_keyring: MagicMock):
    """Tests a successful backend check."""
    # Mock the get_keyring() call
    mock_backend = MagicMock()
    mock_backend.__class__.__name__ = "MockKeyring"
    mock_keyring.get_keyring.return_value = mock_backend

    # Mock the internal credential functions
    test_key = "vebgen_keyring_test_credential"
    test_pw = "dummy_password_123!_for_test"
    
    # Simulate a successful get_password call
    mock_keyring.get_password.return_value = test_pw

    # Run the check
    assert check_keyring_backend() is True

    # Verify the calls
    mock_keyring.set_password.assert_called_once_with(SERVICE_NAME, test_key, test_pw)
    mock_keyring.get_password.assert_called_once_with(SERVICE_NAME, test_key)
    # The cleanup call to delete_password should always happen in the finally block
    mock_keyring.delete_password.assert_called_once_with(SERVICE_NAME, test_key)

@patch("src.core.secure_storage.keyring")
def test_check_keyring_backend_retrieval_mismatch(mock_keyring: MagicMock):
    """Tests backend check failure due to mismatched retrieved password."""
    mock_backend = MagicMock()
    mock_backend.__class__.__name__ = "MockKeyring"
    mock_keyring.get_keyring.return_value = mock_backend

    # Simulate retrieving the wrong password
    mock_keyring.get_password.return_value = "wrong_password"

    assert check_keyring_backend() is False

    # Ensure cleanup is still attempted in the finally block
    mock_keyring.delete_password.assert_called()

@patch("src.core.secure_storage.keyring")
def test_check_keyring_backend_storage_fails(mock_keyring: MagicMock):
    """Tests backend check failure if storing the test credential fails."""
    mock_backend = MagicMock()
    mock_backend.__class__.__name__ = "MockKeyring"
    mock_keyring.get_keyring.return_value = mock_backend

    # Simulate a failure during the set_password call
    mock_keyring.set_password.side_effect = keyring.errors.KeyringError("Cannot write")

    assert check_keyring_backend() is False

    # Ensure cleanup is still attempted even if storage failed
    mock_keyring.delete_password.assert_called()

@patch("src.core.secure_storage.keyring")
def test_check_keyring_backend_init_fails(mock_keyring: MagicMock):
    """Tests backend check failure if keyring.get_keyring() itself fails."""
    # Simulate a failure when trying to get the backend
    mock_keyring.get_keyring.side_effect = Exception("No backend found")

    assert check_keyring_backend() is False