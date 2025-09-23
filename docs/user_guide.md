# Vebgen User Guide: Your Personal AI Software Developer

Welcome to Vebgen! This guide will walk you through using the app to turn your ideas into working software, even if you're not a professional developer.

## 1. What is Vebgen?

Imagine you have an idea for a website or a small application, but you don't know how to code. Vebgen is like having a personal AI software developer that you can talk to. You describe what you want in plain English, and the AI does the hard work of writing the code for you.

## 2. Getting Started: The Main Window

When you first open Vebgen, you'll see the main window. It's divided into two main parts:

*   **The Sidebar (on the left):** This is your control panel. Here, you'll set up your project and choose your AI assistant.
*   **The Main Area (on the right):** This is where you'll interact with the AI and see the progress of your project.



## 3. Your First Project

Before the AI can start working, you need to set up your project.

### Step 1: Select a Project Directory

This is the folder on your computer where Vebgen will save all the files for your project.

1.  Click the **"📂 Select Project Directory..."** button in the sidebar.
2.  Choose an **empty folder** for your new project, or an existing Vebgen project folder if you're continuing your work.


### Step 2: Choose a Framework

A "framework" is like a toolkit that helps build software faster. Vebgen uses these toolkits to create your project.

*   From the **Framework** dropdown menu, select **Django**. (More frameworks will be supported in the future!)

### Step 3: New Project or Existing?

*   **New Project:** If you are starting from scratch in an empty folder, make sure the **"New Project"** checkbox is checked. This tells Vebgen to do the initial setup for you.
*   **Existing Project:** If you are opening a project you previously worked on with Vebgen, uncheck this box.


## 4. Talking to the AI

Now for the fun part! This is where you tell the AI what you want to build.

### Step 1: Write Your Prompt

In the big text box at the top of the main area, type a description of your project. Be as clear as you can.

*   **Good Example:** "I want to build a simple blog website where I can write and publish articles. It should have a homepage to list all articles and a separate page for each article."
*   **Bad Example:** "blog"

The more detail you give, the better the AI can understand your vision.

### Step 2: Choose Your AI

In the sidebar, under **AI Model Settings**, you can choose which "brain" the AI uses.

1.  **API Provider:** Select a service like "OpenAI" or "Google".
2.  **LLM Model:** Choose a specific model from the list. Newer models (like GPT-4o or Gemini 2.5) are generally smarter.

> **Note on API Keys:** The first time you select a model from a new provider, Vebgen may pop up a dialog asking for your API Key. See the "A Quick Word on API Keys" section below for more details.

### Step 3: Start the Magic!

Once you've written your prompt and selected your AI, click the big **"▶️ Start"** button.

Vebgen will now start working. You'll see its progress in the "Updates / Logs" tab.

## 5. Understanding the UI While it Works

### The "Updates / Logs" Tab

This tab is like a detailed diary of what the AI is doing. You'll see a stream of updates and logs, including messages about:
*   The agent's current status (e.g., "Planning feature...", "Generating code...").
*   Creating files and directories.
*   Writing or modifying code.
*   Running commands to build, test, or set up your project.
*   The output from those commands, including any successes or errors.

This gives you a real-time view of your project being built.

### The "Conversation" Tab

This tab shows your chat history with the AI. You can see your original prompt and any messages the AI sends you.


## 6. A Quick Word on API Keys

To use AI providers like OpenAI or Google, you need an "API Key". Think of it like a password that gives Vebgen permission to use their AI services on your behalf.

*   **How to get one:** You'll need to sign up for an account on the provider's website (e.g., platform.openai.com). **For free access to many powerful models, we recommend getting a free API key from [OpenRouter.ai](https://openrouter.ai/).** Other providers will give you a free or paid API key.
*   **How to use it:** The first time you use a provider, Vebgen will pop up a dialog asking for your API key. Just paste it in.
*   **Is it safe?** Yes. Vebgen uses your operating system's secure storage (like Windows Credential Manager or macOS Keychain) to store your keys. They are never stored in plain text.

## 7. What's Next?

Sit back and watch as Vebgen builds your project! If it runs into any problems, it will try to fix them on its own. When it's finished, all the code for your new application will be in the project folder you selected.

Happy building!
