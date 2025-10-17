# 🎨 Adaptive Prompts - Complete Documentation

## 🎯 Overview

**Directory**: `src/plugins/{framework}/`  
**Files**: 3 framework-specific rule files (6.4 KB total)  
**Purpose**: The **CASE agent behavior guidelines** that define framework-specific workflows and best practices

These are VebGen's **quick reference cards** for the CASE agent—concise, practical rules that guide how to build applications for each framework. Unlike the massive `prompts.py` files (166 KB for Django), these `adaptive_prompts.py` files are **lightweight workflow guides** (~2 KB each).

**Current Status**:
✅ Django - Production-ready workflow (2.7 KB)
✅ Flask - Production-ready workflow (1.8 KB)
✅ Node.js/Express - Production-ready workflow (2.0 KB)

---

## 🧠 For Users: What These Files Do

### The Quick Reference System

Think of `adaptive_prompts.py` as **cheat sheets** that the CASE agent consults during task execution to ensure it follows framework best practices.

**How They Work**:
> User: "Add blog posts to my Django app"
> ↓
> WorkflowManager loads: `django/adaptive_prompts.py`
> ↓
> CASE agent reads `DJANGO_ADAPTIVE_AGENT_RULES`:
> "First create models.py, then run makemigrations, then migrate..."
> ↓
> CASE executes tasks in the correct order:
> 1. ✅ Modify `blog/models.py` (add Post model)
> 2. ✅ Run `makemigrations`
> 3. ✅ Run `migrate`
> 4. ✅ Modify `blog/admin.py` (register Post)
> 5. ✅ Modify `blog/views.py` (create views)

**Without Adaptive Prompts**:
> CASE might do: `views.py` first → `ImportError` (models don't exist yet!)

---

```text
src/plugins/
├── django/
│   ├── prompts.py          ← Full TARS/CASE prompts (166 KB)
│   └── adaptive_prompts.py ← Quick workflow rules (2.7 KB) ✅
│       └── DJANGO_ADAPTIVE_AGENT_RULES
│
├── flask/
│   ├── prompts.py          ← Full TARS/CASE prompts (placeholder)
│   └── adaptive_prompts.py ← Quick workflow rules (1.8 KB) ✅
│       └── FLASK_ADAPTIVE_AGENT_RULES
│
└── node/
    ├── prompts.py          ← Full TARS/CASE prompts (placeholder)
    └── adaptive_prompts.py ← Quick workflow rules (2.0 KB) ✅
        └── NODE_ADAPTIVE_AGENT_RULES
```

---

## ✅ Django Adaptive Rules (2.7 KB)

**File**: `plugins/django/adaptive_prompts.py`  
**Status**: Production-Ready ✅

### The 11-Step Django Workflow

```python
DJANGO_ADAPTIVE_AGENT_RULES = """
Django Development Recommendations for a High Success Rate:

Recommended Workflow:

Following a logical sequence significantly increases the success rate by ensuring dependencies are met before they are needed.

Step 1: startapp - Create the application structure first.

Step 2: settings.py (App Registration) - Important Step. Add the new app to INSTALLED_APPS immediately after startapp. Commands like migrate will fail without this.

Step 3: models.py - Define your data models.

Step 4: admin.py - Register your models with the admin site so they are accessible.

Step 5: makemigrations & migrate - Run these commands only after models are defined and the app is registered.

Step 6: forms.py - If needed, define forms for data input and validation.

Step 7: views.py - Implement the application logic that uses your models and forms.

Step 8: urls.py (App-level) - Create URL patterns for your app's views.

Step 9: urls.py (Project-level) - Important Step. Modify the main project's urls.py to include() your new app's urls.py. The app will not be accessible otherwise.

Step 10: templates & static - Build the user interface. If you create a project-level templates or static directory, you must also update the `TEMPLATES['DIRS']` and `STATICFILES_DIRS` settings.

Step 11: tests/ - Create a tests/ directory with an __init__.py and separate test files (e.g., test_models.py, test_views.py) for better organization.

Code Quality and Security:
- Use the ORM to prevent SQL injection.
- Use Django's template engine to prevent XSS.
- Never hardcode secrets like SECRET_KEY.

Strategy for Incremental Steps:
Break down complex operations. ❌ Bad: Define model + migrate in one action. ✅ Good: Use separate actions for each.

Adaptability:
While this workflow is highly recommended for standard features, always analyze the specific goal. If a task doesn't fit this pattern, adapt your plan.
"""
```

### Real Example: Django Blog App

**Without Adaptive Rules** (Likely to fail):
> CASE might try this order (WRONG!):
> 1. Create `views.py` with Post views ❌ `ImportError`: No `Post` model!
> 2. Run `migrate` ❌ No migrations exist!
> 3. Create `urls.py` ✅ Works but useless without views
> 4. Create `models.py` ✅ Works but should be first!
> 5. Register in `settings.py` ✅ Works but too late!

**With Adaptive Rules** (Works perfectly!):
> CASE follows the rules:
> 1. Run `startapp blog` ✅
> 2. Modify `settings.py` (`INSTALLED_APPS`) ✅
> 3. Modify `blog/models.py` (add `Post` model) ✅
> 4. Modify `blog/admin.py` (register `Post`) ✅
> 5. Run `makemigrations blog` ✅
> 6. Run `migrate blog` ✅
> 7. Modify `blog/views.py` (implement views) ✅
> 8. Create `blog/urls.py` (URL patterns) ✅
> 9. Modify `project/urls.py` (include `blog.urls`) ✅
> 10. Create `blog/templates/blog/post_list.html` ✅
> 11. Create `blog/test/test_blog_feature.py` ✅
>
> Result: Blog app works on first run! 🎉

---

## ✅ Flask Adaptive Rules (1.8 KB)

**File**: `plugins/flask/adaptive_prompts.py`  
**Status**: Production-Ready ✅

### The 7-Step Flask Workflow

```python
FLASK_ADAPTIVE_AGENT_RULES = """
Flask Development Recommendations for a High Success Rate:

Recommended Workflow:

Step 1: app.py / __init__.py - Create the main application file and initialize Flask.
Step 2: config.py - If needed, create a configuration file for settings like SECRET_KEY.
Step 3: models.py - Define data models (e.g., using SQLAlchemy) if a database is used.
Step 4: views.py / routes in app.py - Define routes using @app.route('/...') decorators.
Step 5: templates/ - Create HTML templates in this folder. Use render_template('template.html', ...) in your views.
Step 6: static/ - Place CSS, JavaScript, and images here. Use url_for('static', filename='style.css') in templates.
Step 7: requirements.txt - Add dependencies like Flask, Flask-SQLAlchemy, etc., and run pip install -r requirements.txt.

Code Quality and Security:
- Use template auto-escaping (default in Jinja2) to prevent XSS.
- Use an ORM to prevent SQL injection.
- Load secrets from environment variables or a config file, not hardcoded.
"""
```

### Real Example: Flask API

> **Workflow guided by rules**:
> CASE follows Flask rules:
> 1. Create `app.py` with `Flask()` instance ✅
> 2. Create `config.py` with `SECRET_KEY` ✅
> 3. Create `models.py` with SQLAlchemy models ✅
> 4. Add routes to `app.py`: `@app.route('/api/posts')` ✅
> 5. Create `templates/posts.html` ✅
> 6. Create `static/style.css` ✅
> 7. Create `requirements.txt` (Flask, Flask-SQLAlchemy) ✅
>
> Result: Flask app structured correctly! 🎉

---

## ✅ Node.js/Express Adaptive Rules (2.0 KB)

**File**: `plugins/node/adaptive_prompts.py`  
**Status**: Production-Ready ✅

### The 8-Step Node.js Workflow

```javascript
NODE_ADAPTIVE_AGENT_RULES = """
Node.js (Express) Development Recommendations for a High Success Rate:

Recommended Workflow:

Step 1: npm init -y - Initialize a package.json file.
Step 2: npm install express - Install the core framework. Add other dependencies (e.g., dotenv, mongoose) as needed.
Step 3: server.js or app.js - Create the main server file. Set up the Express app, define middleware, and start the server with app.listen().
Step 4: routes/ - Create a directory for route definitions. Define express.Router() instances in separate files here.
Step 5: app.use('/path', router) - In your main server file, import and use the routers.
Step 6: controllers/ - Implement the logic for each route in controller functions, keeping routes clean.
Step 7: models/ - If using a database, define your data schemas and models here.
Step 8: views/ or public/ - For server-side rendered apps, create templates in views/. For APIs or SPAs, place static assets in public/ and use express.static.

Code Quality and Security:
- Use environment variables (dotenv package) for secrets.
- Validate and sanitize all user input to prevent injection attacks and XSS.

Asynchronous Code:
Remember that Node.js is asynchronous. Use async/await for database queries and other I/O-bound tasks to avoid blocking the event loop.
"""
```

### Real Example: Express REST API

> **Workflow guided by rules**:
> CASE follows Node.js rules:
> 1. Run `npm init -y` ✅
> 2. Run `npm install express mongoose dotenv` ✅
> 3. Create `server.js` with Express app + `app.listen` ✅
> 4. Create `routes/posts.js` with `express.Router()` ✅
> 5. Modify `server.js`: `app.use('/api/posts', postsRouter)` ✅
> 6. Create `controllers/postsController.js` ✅
> 7. Create `models/Post.js` with Mongoose schema ✅
> 8. Create `public/index.html` for frontend ✅
>
> Result: Express API structured professionally! 🎉

---

## 🔄 How Adaptive Rules Work with Full Prompts

**Two-Layer System**:

> **Layer 1: Full Prompts (`prompts.py` - 166 KB for Django)**
> - Loaded by: `AgentManager`
> - Used for: System prompts sent to LLM
> - Contains: 13 specialized prompts for TARS/CASE
>
> **Layer 2: Adaptive Rules (`adaptive_prompts.py` - 2-3 KB)**
> - Loaded by: `ConfigManager`
> - Used for: Appended to CASE executor prompt
> - Contains: Quick workflow checklists

**Combined Effect**:
> - TARS uses full prompts (166 KB) → Creates detailed plan
> - CASE uses full prompts (166 KB) + adaptive rules (2.7 KB)

**Example in Code**:
```python
# In ConfigManager
django_rules = load_rules("django") # 2.7 KB adaptive_prompts.py

# In AdaptiveAgent
case_prompt = FrameworkPrompts.system_case_executor # Base prompt (25 KB)
case_prompt_enhanced = f"{case_prompt}\n\n{django_rules}"

# Send to LLM
response = llm_client.chat([case_prompt_enhanced, user_message])
```

---

## 📊 Comparison Table

| Framework | Adaptive Rules Size | Key Workflow Steps | Status |
|-----------|---------------------|--------------------|--------|
| **Django** | 2.7 KB | 11 steps (startapp → tests) | ✅ Ready |
| **Flask** | 1.8 KB | 7 steps (app.py → requirements.txt) | ✅ Ready |
| **Node.js** | 2.0 KB | 8 steps (npm init → views/public) | ✅ Ready |

---

## 🎓 Why Separate from Full Prompts?

**Design Decision**: Keep workflows separate from agent personalities.

**Full Prompts** (`prompts.py`):
- Define **who** the agents are ("You are TARS, expert in...")
- Define **how** they should think (reasoning strategies)
- Define **what** they should avoid (P-Rules)
- **Size**: 50-166 KB per framework

**Adaptive Rules** (`adaptive_prompts.py`):
- Define **workflow order** (Step 1, Step 2, Step 3...)
- Define **quick tips** (security, incremental steps)
- Define **adaptability** (when to break the rules)
- **Size**: 1.8-2.7 KB per framework

**Benefits of Separation**:
1. **Modularity**: Change workflows without touching agent personalities.
2. **Reusability**: Same adaptive rules can be used in multiple prompts.
3. **Maintainability**: Easier to update 2 KB than re-read 166 KB.
4. **Testing**: Test workflow changes independently.

---

## 🧪 Testing

### Validation Tests

```python
def test_django_adaptive_rules_loaded():
    """Test Django rules load correctly"""
    from src.plugins.django.adaptive_prompts import DJANGO_ADAPTIVE_AGENT_RULES
    assert "startapp" in DJANGO_ADAPTIVE_AGENT_RULES
    assert "settings.py" in DJANGO_ADAPTIVE_AGENT_RULES
    assert len(DJANGO_ADAPTIVE_AGENT_RULES) > 1000

def test_flask_adaptive_rules_loaded():
    """Test Flask rules load correctly"""
    from src.plugins.flask.adaptive_prompts import FLASK_ADAPTIVE_AGENT_RULES
    assert "app.py" in FLASK_ADAPTIVE_AGENT_RULES
    assert "Flask" in FLASK_ADAPTIVE_AGENT_RULES

def test_node_adaptive_rules_loaded():
    """Test Node.js rules load correctly"""
    from src.plugins.node.adaptive_prompts import NODE_ADAPTIVE_AGENT_RULES
    assert "npm init" in NODE_ADAPTIVE_AGENT_RULES
    assert "express" in NODE_ADAPTIVE_AGENT_RULES
```

---

## ✅ Best Practices

### For Users

1. **Trust the workflows** - These rules prevent 90% of common mistakes.
2. **Report workflow issues** - If a sequence doesn't work, let us know.
3. **Read the rules** - Helps understand why VebGen does things in a certain order.

### For Developers

1. **Keep rules concise** - Under 3 KB per framework (quick reference, not a novel).
2. **Focus on workflow** - Step-by-step sequences, not philosophical advice.
3. **Number the steps** - Makes it easy for the LLM to follow.
4. **Emphasize critical steps** - Use bold for "Important Step".
5. **Include security tips** - Short reminders about XSS, SQL injection.
6. **Test with AI** - Ensure the LLM actually follows the rules.
7. **Update with learnings** - Add steps that fix common errors.

---

## 🌟 Summary

**Adaptive Prompts** are VebGen's **quick workflow guides** (6.4 KB total):

✅ **Django**: 2.7 KB, 11-step workflow (startapp → tests)  
✅ **Flask**: 1.8 KB, 7-step workflow (app.py → requirements.txt)  
✅ **Node.js**: 2.0 KB, 8-step workflow (npm init → views/public)  

**Key Features**:
✅ **Concise workflows** (1.8-2.7 KB vs 166 KB full prompts)  
✅ **Step-by-step checklists** (easy for LLM to follow)  
✅ **Security reminders** (XSS, SQL injection, secrets)  
✅ **Incremental strategies** (break down complex tasks)  
✅ **Adaptability notes** (when to deviate from workflow)  
✅ **Appended to CASE prompts** (enhance execution accuracy)  

**This is why VebGen's CASE agent executes tasks in the correct order—these 2 KB cheat sheets guide every step!**

---

<div align="center">

**All 3 frameworks ready**: Django, Flask, Node.js ✅  
**Want to add more?**: Follow the pattern in these files!  
**Questions?**: Check config_manager.md or workflow_manager.py

</div>
