# backend/src/plugins/django/adaptive_prompts.py

DJANGO_ADAPTIVE_AGENT_RULES = """
**Django Development Recommendations for a High Success Rate:**

1.  **Recommended Workflow**:
    Following a logical sequence significantly increases the success rate by ensuring dependencies are met before they are needed. The recommended order is:
    -   `startapp`: Create the application structure first.
    -   `settings.py` (App Registration): **Important Step.** It's highly recommended to `WRITE_FILE` to add the new app to `INSTALLED_APPS` immediately after `startapp`. Commands like `migrate` will fail without this.
    -   `models.py`: Define Django models (class MyModel(models.Model)) for 
     database persistence. NOT standalone classes - must inherit from 
     models.Model.
    -   `admin.py`: Register your models with the admin site so they are accessible.
    -   `makemigrations` & `migrate`: It's best to run these commands only *after* models are defined and the app is registered.
    -   `forms.py`: If needed, define forms for data input and validation.
    -   `views.py`: Implement the application logic that uses your models and forms.
    -   `urls.py` (App-level): Create URL patterns for your app's views.
    -   `urls.py` (Project-level): **Important Step.** Remember to `WRITE_FILE` to modify the main project's `urls.py` to `include()` your new app's `urls.py`. The app will not be accessible otherwise.
    -   `templates` & `static`: Build the user interface. If you create a project-level `templates` or `static` directory, you must also update the `TEMPLATES['DIRS']` and `STATICFILES_DIRS` settings in `settings.py`.
    -   `tests/`: Create a `tests/` directory with an `__init__.py` and separate test files (e.g., `test_models.py`, `test_views.py`) for better organization. Write tests to ensure everything works as expected.

2.  **Code Quality and Security**: For best results, write production-ready, secure Django code. Use the ORM to prevent SQL injection, use Django's template engine to prevent XSS, and never hardcode secrets like `SECRET_KEY`.

3.  **Strategy for Incremental Steps**: Your chance of success is highest when you take small, logical steps. For example, instead of trying to define a model and migrate in one action, break it down: first `WRITE_FILE` for the model, then `RUN_COMMAND` for `makemigrations`, then `RUN_COMMAND` for `migrate`. This isolates potential errors and makes debugging easier.

4.  **Adaptability**: While this workflow is highly recommended for standard features, always analyze the specific goal. If a task (e.g., a simple utility script) doesn't fit this pattern, adapt your plan. The primary objective is to successfully implement the feature, and these recommendations are your main tool to achieve that.
"""