# backend/src/utils/check_model.py
import sys
import importlib
import inspect
import logging
import os

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_model_exists(app_label: str, model_name: str) -> bool:
    """
    Checks if a model class with the given name exists within the specified app's models.py.
    Uses dynamic imports. Assumes the app is importable in the current environment.
    """
    try:
        import django
        from django.db import models # Import models for inheritance check
        from django.core.exceptions import ImproperlyConfigured

        # Ensure Django settings are configured and the app registry is ready.
        if not os.environ.get("DJANGO_SETTINGS_MODULE"):
            logger.error("DJANGO_SETTINGS_MODULE environment variable is not set. Cannot check model.")
            return False
        try:
            django.setup() # Initialize Django
        except ImproperlyConfigured as e:
            logger.error(f"Django setup failed: {e}. Ensure settings are correct. Cannot check model.")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during Django setup: {e}. Cannot check model.")
            return False

        # Construct the module path (e.g., 'myapp.models')
        module_path = f"{app_label}.models"
        logger.debug(f"Attempting to import module: {module_path}")

        # Dynamically import the models module
        models_module = importlib.import_module(module_path) # type: ignore
        logger.debug(f"Successfully imported {module_path}.")

        # Inspect the module for classes
        for name, obj in inspect.getmembers(models_module):
            # Check if it's a class and inherits from django.db.models.Model
            if inspect.isclass(obj) and name == model_name and issubclass(obj, models.Model):
                logger.debug(f"Found class '{name}' and it is a Django model.")
                return True # Found the class

        logger.debug(f"Class '{model_name}' not found in {module_path}.")
        return False # Class not found

    except ImportError:
        logger.error(f"Failed to import Django modules. Is Django installed? (pip install vebgen[django])")
        return False
    except Exception as e:
        logger.exception(f"An unexpected error occurred while checking model '{app_label}.{model_name}': {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python check_model.py <app_label> <ModelName>", file=sys.stderr)
        sys.exit(2) # Indicate incorrect usage

    app_label_arg = sys.argv[1]
    model_name_arg = sys.argv[2]
    logger.info(f"Checking for model: '{app_label_arg}.{model_name_arg}'...")

    if check_model_exists(app_label_arg, model_name_arg):
        print(f"Success: Model '{model_name_arg}' found in app '{app_label_arg}'.")
        sys.exit(0) # Exit code 0 for success (found)
    else:
        print(f"Failure: Model '{model_name_arg}' not found in app '{app_label_arg}' or error occurred.", file=sys.stderr)
        sys.exit(1) # Exit code 1 for failure (not found or error)
