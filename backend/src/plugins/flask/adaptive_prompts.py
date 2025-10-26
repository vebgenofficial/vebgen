# backend/src/plugins/flask/adaptive_prompts.py

FLASK_ADAPTIVE_AGENT_RULES = """
**Flask Development Recommendations for a High Success Rate:**

1.  **Recommended Workflow**:
    For Flask projects, a logical sequence helps ensure success. The recommended order is:
    -   `app.py` / `__init__.py`: Create the main application file and initialize the Flask app instance.
    -   `config.py`: If needed, create a configuration file for settings like `SECRET_KEY`.
    -   `models.py`: Define data models (e.g., using SQLAlchemy) if a database is required.
    -   `views.py` / routes in `app.py`: Define routes using `@app.route('/...')` decorators.
    -   `templates/`: Create HTML templates in this folder. Use `render_template('template.html', ...)` in your views.
    -   `static/`: Place CSS, JavaScript, and images here. Use `url_for('static', filename='style.css')` in templates.
    -   `requirements.txt`: Add dependencies like `Flask`, `Flask-SQLAlchemy`, etc., and run `pip install -r requirements.txt`.

2.  **Code Quality and Security**: For best results, write clean and secure Flask code. Use template auto-escaping (default in Jinja2) to prevent XSS, use an ORM to prevent SQL injection, and load secrets from environment variables or a config file, not hardcoded.

3.  **Strategy for Incremental Steps**: Your chance of success is highest when you take small, logical steps. For example, create a simple "Hello World" route first, then add a template, then add database logic. This isolates potential errors.

4.  **Adaptability**: For larger applications, consider using Flask Blueprints to organize your code. This involves creating separate directories for different parts of your application and registering them with the main app instance.
"""

