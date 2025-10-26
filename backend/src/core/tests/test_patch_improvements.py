# backend/src/core/tests/test_patch_improvements.py
import sys

from src.core.file_system_manager import FileSystemManager
import tempfile
import os

def test_fuzzy_patch():
    """Test the new fuzzy patch functionality"""
    
    # Create test file
    with tempfile.TemporaryDirectory() as temp_dir:
        fsm = FileSystemManager(temp_dir)
        
        # Create a test Django settings file
        settings_content = '''
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
]
'''
        
        fsm.write_file('settings.py', settings_content)
        
        # Test patch that would normally fail (wrong line numbers)
        bad_patch = """--- a/settings.py
+++ b/settings.py
@@ -10,6 +10,7 @@
 'django.contrib.sessions',
 'django.contrib.messages',
 'django.contrib.staticfiles',
+'calculator',
 ]
 
 MIDDLEWARE = ["""
        
        try:
            fsm.apply_patch('settings.py', bad_patch)
            print("✅ Fuzzy patch succeeded!")
            
            # Verify result
            result = fsm.read_file('settings.py')
            if "'calculator'," in result:
                print("✅ Calculator app was added correctly!")
            else:
                print("❌ Calculator app not found in result")
                
        except Exception as e:
            print(f"❌ Patch failed: {e}")

if __name__ == "__main__":
    test_fuzzy_patch()