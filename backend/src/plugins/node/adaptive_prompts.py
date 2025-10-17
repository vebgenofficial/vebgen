# src/plugins/node/adaptive_prompts.py

NODE_ADAPTIVE_AGENT_RULES = """
**Node.js (Express) Development Recommendations for a High Success Rate:**

1.  **Recommended Workflow**:
    Following a logical sequence for Express.js projects is key. The recommended order is:
    -   `npm init -y`: Initialize a `package.json` file.
    -   `npm install express`: Install the core framework. Add other dependencies (e.g., `dotenv`, `mongoose`) as needed.
    -   `server.js` or `app.js`: Create the main server file. Set up the Express app, define middleware, and start the server (`app.listen`).
    -   `routes/`: Create a directory for route definitions. Define `express.Router()` instances in separate files here.
    -   `app.use('/path', router)`: In your main server file, import and use the routers you defined.
    -   `controllers/`: Implement the logic for each route in controller functions, keeping route files clean.
    -   `models/`: If using a database, define your data schemas and models here.
    -   `views/` or `public/`: For server-side rendered apps, create templates in `views/` and set a view engine. For APIs or SPAs, place static assets (HTML, CSS, JS) in `public/` and use `express.static`.

2.  **Code Quality and Security**: For best results, write clean and secure Node.js code. Use environment variables (`dotenv` package is good for this) for secrets like database connection strings and API keys. Validate and sanitize all user input to prevent injection attacks and XSS.

3.  **Strategy for Incremental Steps**: Your chance of success is highest when you take small, logical steps. For example, create the server file, add one simple route, test it, then add another. This makes debugging much easier.

4.  **Asynchronous Code**: Remember that Node.js is asynchronous. Use `async/await` for database queries, file system operations, and other I/O-bound tasks to avoid blocking the event loop.
"""

