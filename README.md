# UI Navigator Agent System

An AI-powered system that automatically navigates web applications and captures screenshots to demonstrate how to perform tasks.

## Overview

This system uses AI to generate navigation plans and Playwright to execute them, making it generalizable to any web application without hardcoding.

**Components:**
- **Agent B**: Generates structured UI navigation plans from natural language tasks
- **Playwright Executor**: Automates browser navigation and captures screenshots
- **Screenshot Capture**: Records UI states at each step

## Features

- Works with any web app and task
- Automatic screenshot capture at each UI state
- Handles both logged-in and logged-out states
- AI-generated navigation plans (no hardcoding required)

## Setup

### Prerequisites

- Python 3.8+
- OpenAI API key

### Installation

1. Clone this repository

2. Install dependencies:
```bash
pip install -r requirements.txt
playwright install chromium
```

Note: The system uses Google Chrome (not Chromium). Make sure you have Google Chrome installed on your system. Playwright will automatically detect and use it.

3. Create a `.env` file:
```bash
OPENAI_API_KEY=your_key_here
```

Get your OpenAI API key from: https://platform.openai.com/api-keys

## Quick Start

Run any task from the command line:

```bash
# Public website (URL auto-detected)
python main.py "How do I search on Google?"

# With login credentials (URL auto-detected)
python main.py "How do I create a project in Linear?" "email@example.com" "password"

# Specify URL manually
python main.py "How do I filter a database?" "https://www.notion.so"
```

**What happens:**
1. System auto-detects the website URL from your task description
2. AI generates a navigation plan
3. Browser automatically navigates and performs the task
4. Screenshots are captured at each step
5. Results saved to `screenshots/` directory

## Usage

### Command Line

```bash
# Basic usage (URL auto-detected)
python main.py "task description" [email] [password]

# With explicit URL
python main.py "task description" "https://url.com" [email] [password]
```

**Examples:**
```bash
python main.py "How do I search on Google?"
python main.py "How do I create a project in Linear?" "your@email.com" "password"
python main.py "How do I filter a database?" "https://www.notion.so"
```

### Viewing Results

Screenshots are saved in the `screenshots/` directory, organized by run timestamp. Each execution creates a new folder:

```
screenshots/
├── run_20240101_120000_123/
│   ├── step_01_open_the_application.png
│   ├── step_02_navigate_to_projects.png
│   └── ...
├── run_20240101_120530_456/
│   ├── step_01_open_the_application.png
│   └── ...
```

Each run folder contains all screenshots from that execution, making it easy to track results from different runs.

## How It Works

1. **Task Input**: You provide a natural language task (e.g., "How do I create a project in Linear?")

2. **Plan Generation**: Agent B (ChatGPT) generates a structured JSON navigation plan with:
   - Application URL (auto-detected from task description)
   - Task understanding and assumptions
   - High-level plan
   - Detailed UI navigation steps with Playwright actions

3. **Execution**: The Playwright executor:
   - Opens the browser
   - Executes each step in the plan
   - Captures screenshots at each UI state
   - Handles conditional logic (e.g., login detection, element existence checks)

4. **Output**: Screenshots are saved in organized directories for review

## Supported Actions

The system supports various Playwright actions:

- `open_page('url')` - Navigate to a URL
- `wait_for('selector')` - Wait for element to appear
- `wait_for_page_ready()` - Wait for page to fully load
- `click('selector')` or `click('text=Button Text')` - Click element
- `type('selector', 'text')` - Type into input field
- `if_element_exists('selector', proceed_to_step=N)` - Conditional check
- `if_url_contains('pattern', proceed_to_step=N)` - URL-based conditional
- `wait_for_url_change()` - Wait for URL to change
- `press('key')` or `press_key('key')` - Press keyboard key

## Troubleshooting

- **OpenAI API errors**: Check your API key and quota
- **Playwright errors**: Ensure browsers are installed (`playwright install chromium`) and Google Chrome is installed on your system
- **Selector not found**: The AI-generated selectors may need adjustment for specific apps
- **Login issues**: Verify credentials are provided correctly
- **Python version**: Ensure you're using Python 3.8 or higher

## License

MIT
