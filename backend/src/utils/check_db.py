# backend/src/utils/check_db.py
import os
import sys
import logging

# --- Configure Logging ---
# Basic configuration in case this script is run standalone
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_table_exists(table_name: str) -> bool:
    """
    Checks if a specific table exists in the default database using Django's introspection API.
    Assumes Django settings are configured via environment variables or django.setup().
    """
    try:
        # These imports require Django settings to be configured.
        import django
        from django.db import connection
        from django.core.exceptions import ImproperlyConfigured

        # Ensure Django settings are configured. DJANGO_SETTINGS_MODULE must be set.
        if not os.environ.get("DJANGO_SETTINGS_MODULE"):
            logger.error("DJANGO_SETTINGS_MODULE environment variable is not set.")
            return False
        try:
            django.setup() # Initialize Django
        except ImproperlyConfigured as e:
            logger.error(f"Django setup failed: {e}. Ensure settings are correct.")
            return False

        all_tables = connection.introspection.table_names()
        logger.debug(f"Tables found in database: {all_tables}")
        return table_name in all_tables

    except ImportError as e:
        logger.error(f"Failed to import Django modules: {e}. Is Django installed? (pip install vebgen[django])")
        return False
    except Exception as e:
        logger.exception(f"An unexpected error occurred while checking table '{table_name}': {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python check_db.py <table_name>", file=sys.stderr)
        sys.exit(2) # Indicate incorrect usage

    target_table = sys.argv[1]
    logger.info(f"Checking for table: '{target_table}'...")

    if check_table_exists(target_table):
        print(f"Success: Table '{target_table}' found.")
        sys.exit(0) # Exit code 0 for success (found)
    else:
        print(f"Failure: Table '{target_table}' not found or error occurred.", file=sys.stderr)
        sys.exit(1) # Exit code 1 for failure (not found or error)
