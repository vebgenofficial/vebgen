# backend/src/core/secure_storage.py
import logging
import keyring # Needs: pip install keyring
# Consider installing a backend if needed (e.g., pip install keyrings.cryptfile)
# See keyring documentation for backend setup: https://pypi.org/project/keyring/
import platform
from typing import Optional

logger = logging.getLogger(__name__)

# Use a consistent service name for the application to group all its credentials.
# This prevents Vebgen's stored keys from conflicting with other applications
# on the user's system that might also be using the keyring library.
SERVICE_NAME = "VebgenAI_Agents"

# Import specific exceptions to avoid issues with mocking the keyring module in tests.
from keyring.errors import KeyringError, PasswordDeleteError


def store_credential(key: str, secret: str) -> None:
    """
    Stores a secret securely using the OS credential manager (keyring).

    Args:
        key: The identifier for the secret (e.g., "OPENROUTER_API_KEY_TARS").
        secret: The actual secret value to store.

    Raises:
        ValueError: If the key or secret is invalid (empty).
        RuntimeError: If keyring fails to store the credential (backend issue).
    """
    # Basic validation to prevent storing credentials with no identifier.
    if not isinstance(key, str) or not key:
        logger.error("Attempted to store credential with invalid key.")
        raise ValueError("Credential key cannot be empty.")
    # Ensure the secret is a string, as keyring expects strings.
    if not isinstance(secret, str):
        logger.error("Attempted to store non-string credential secret.")
        raise ValueError("Credential secret must be a string.")

    secret_stripped = secret.strip()
    # Avoid storing empty or whitespace-only strings as secrets.
    if not secret_stripped:
        logger.error("Attempted to store empty credential secret after stripping.")
        raise ValueError("Credential secret cannot be empty after stripping.")

    try:
        # Use keyring to set the password (secret) for the given service and key.
        keyring.set_password(SERVICE_NAME, key, secret_stripped)
        logger.info(f"Stored credential for key '{key}' securely.")
    except KeyringError as e:
        # This error typically means the keyring backend is not installed or configured.
        # We raise a RuntimeError because the app cannot function without secure storage.
        logger.exception(f"Failed to store credential securely for key '{key}'. Keyring backend might be misconfigured or unavailable.")
        raise RuntimeError(f"Secure storage unavailable: {e}") from e
    except Exception as e:
        logger.exception(f"Unexpected error storing credential for key '{key}'.")
        raise RuntimeError(f"Failed to store credential: {e}") from e


def retrieve_credential(key: str) -> Optional[str]:
    """
    Retrieves a secret from the OS credential manager (keyring).

    Args:
        key: The identifier for the secret to retrieve.

    Returns:
        The retrieved secret string, or None if not found or an error occurred.

    Raises:
        ValueError: If the key is invalid (empty).
    """
    # Basic validation for the key.
    if not isinstance(key, str) or not key:
        logger.error("Attempted to retrieve credential with invalid key.")
        raise ValueError("Credential key cannot be empty.")

    try:
        # Use keyring to get the password (secret).
        secret = keyring.get_password(SERVICE_NAME, key)
        if secret:
            secret_stripped = secret.strip()
            if secret_stripped:
                # Return the secret if found and not just whitespace.
                logger.debug(f"Retrieved credential for key '{key}' securely.")
                return secret_stripped
            else:
                # Log if a stored credential was empty after stripping.
                logger.warning(f"Credential retrieved for key '{key}' was empty after stripping. Treating as not found.")
                return None
        else:
            # This is a normal, expected case if the user hasn't entered the key yet.
            logger.debug(f"No credential found for key '{key}' in secure storage.")
            return None
    except KeyringError as e:
        # Don't raise an exception here. Not finding a key is an expected state
        # that the application handles by prompting the user. We just log the warning.
        logger.warning(f"Failed to retrieve credential securely for key '{key}'. Keyring backend might be misconfigured or unavailable.", exc_info=False) # Don't need full trace usually
        return None
    except Exception as e:
        # Log other unexpected errors during retrieval.
        logger.exception(f"Unexpected error retrieving credential for key '{key}'.")
        return None

def delete_credential(key: str) -> bool:
    """
    Deletes a secret from the OS credential manager (keyring).

    Args:
        key: The identifier for the secret to delete.

    Returns:
        True if the deletion was successful or the key didn't exist, False on error.

    Raises:
        ValueError: If the key is invalid (empty).
    """
    # Basic validation for the key.
    if not isinstance(key, str) or not key:
        logger.error("Attempted to delete credential with invalid key.")
        raise ValueError("Credential key cannot be empty.")

    try:
        # Use keyring to delete the password.
        keyring.delete_password(SERVICE_NAME, key)
        logger.info(f"Deleted credential for key '{key}' from secure storage (or it didn't exist).")
        return True
    except PasswordDeleteError:
        # This specific error means the password wasn't found, which is fine for a delete operation.
        # We can consider the goal (the key being gone) achieved.
        logger.warning(f"Credential for key '{key}' not found during deletion attempt (or backend doesn't support delete). Treating as success.")
        return True # Treat as success in terms of the key being gone
    except KeyringError as e:
        # This indicates a more serious problem with the storage backend itself.
        logger.error(f"Failed to delete credential securely for key '{key}'. Keyring backend error.", exc_info=True)
        return False # Indicate failure
    except Exception as e:
        logger.exception(f"Unexpected error deleting credential for key '{key}'.")
        return False # Indicate failure

def check_keyring_backend():
    """
    Checks if the keyring backend is accessible and functional by performing
    a quick set/get/delete test operation.

    Logs information about the backend or potential issues.

    Returns:
        True if the backend seems okay, False otherwise.
    """
    try:
        # Get the currently configured keyring backend (e.g., WindowsCredentialManager, Keyrings.cryptfile).
        backend = keyring.get_keyring()
        logger.info(f"Keyring backend initialized: {backend.__class__.__name__}")

        # Define a unique key for testing that's unlikely to clash.
        test_key = "vebgen_keyring_test_credential"
        test_pw = "dummy_password_123!_for_test"

        try:
            # Perform a quick set, get, and delete operation to test functionality.
            store_credential(test_key, test_pw)
            retrieved = retrieve_credential(test_key) # type: ignore

            # Verify that the value we got back is the one we stored.
            if retrieved != test_pw:
                logger.error(f"Keyring backend test failed: Retrieved password ('{retrieved}') did not match expected.")
                return False

            logger.info("Keyring backend test successful (set/get).")
            return True
        except (RuntimeError, ValueError, KeyringError) as cred_op_error:
            logger.error(f"Keyring backend test failed during set/get operation: {cred_op_error}")
            return False
        finally:
            # Always attempt to clean up the test credential.
            logger.debug("Running keyring backend test cleanup.")
            if not delete_credential(test_key):
                logger.warning("Failed to clean up test credential after backend check. Manual removal may be needed.")

    except Exception as e:
        # This block catches errors if keyring itself fails to initialize.
        logger.error(f"Keyring backend check failed: {e}", exc_info=True)
        logger.error(
            "Secure storage (keyring) may not function correctly. "
            "Ensure a suitable backend is installed and configured "
            "(e.g., 'pip install keyrings.cryptfile' or OS integration like Windows Credential Manager, macOS Keychain, GNOME Keyring). "
            "See keyring documentation for details."
        )
        return False