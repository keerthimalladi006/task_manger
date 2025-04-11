import os
import requests
from flask import Blueprint, request, render_template, redirect, url_for, session, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv
from utils import get_db_connection  # Import from utils.py
from functools import wraps
import sqlite3

# Load environment variables from .env
load_dotenv()

# Load Hugging Face API Key
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
if not HUGGINGFACE_API_KEY:
    raise ValueError("Missing Hugging Face API Key! Set it in a .env file.")

# Hugging Face API details
HUGGINGFACE_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
API_URL = f"https://api-inference.huggingface.co/models/{HUGGINGFACE_MODEL}"
HEADERS = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}", "Content-Type": "application/json"}

# Define Flask Blueprint
study_plan_bp = Blueprint('study_plan', __name__)

# Database connection
def get_db_connection():
    conn = sqlite3.connect('tasks.db')
    conn.row_factory = sqlite3.Row
    return conn

# Generate study plan with priorities and deadlines using Hugging Face API
def generate_study_plan(user_input):
    # Default duration for basic-level learning if not specified
    default_days = 10
    
    # Check if user specifies a duration like "in X days"
    if "in" in user_input.lower() and "days" in user_input.lower():
        try:
            days = int(user_input.split("in")[1].split("days")[0].strip())
        except (IndexError, ValueError):
            days = default_days  # Fallback to default if parsing fails
        topic = user_input.split("in")[0].strip()  # Extract topic before "in"
    else:
        days = default_days  # Use default if no days specified
        topic = user_input.strip()  # Use full input as topic

    # Construct a dynamic prompt with priorities and deadlines
    prompt = (
        f"Generate a study plan to learn '{topic}' in {days} days. "
        f"Provide a list of tasks to learn this topic effectively over {days} days. "
        "For each task, include a priority (High, Medium, Low) and a deadline (e.g., Day 1, Day 2). "
        "Format each task as: 'Task Name (Priority: X, Deadline: Day Y)'."
    )
    
    payload = {"inputs": prompt}
    response = requests.post(API_URL, headers=HEADERS, json=payload)
    
    if response.status_code == 200:
        data = response.json()
        if isinstance(data, list) and len(data) > 0 and 'generated_text' in data[0]:
            raw_plan = data[0]['generated_text'].strip()
            # Parse the response into full tasks (with priorities and deadlines) and cleaned tasks
            full_tasks = []
            cleaned_tasks = []
            for line in raw_plan.split("\n"):
                line = line.strip()
                # Skip unwanted lines
                if line and not any(keyword in line.lower() for keyword in ["generate", "here", "plan", "based", "input", "task"]):
                    # Store the full task with priority and deadline
                    full_tasks.append(line)
                    # Clean the task name by removing priority, deadline, and "Day :" prefix
                    task_name = line.split("(Priority:")[0].strip()
                    task_name = task_name.replace("Day : ", "").strip()  # Remove "Day : " prefix
                    task_name = ''.join(char for char in task_name if not char.isdigit() and char not in "-*[]().").strip()
                    if task_name:
                        cleaned_tasks.append(task_name)
            return full_tasks, cleaned_tasks, days
        else:
            print(f"API Response Error: {data}")
            return ["API permission error (Priority: High, Deadline: Day 1)"], ["API permission error"], default_days
    else:
        print(f"API Request Failed - Status: {response.status_code}, Response: {response.text}")
        return ["Failed to contact API (Priority: High, Deadline: Day 1)"], ["Failed to contact API"], default_days

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Route to generate and display study plan
@study_plan_bp.route('/generate_study_plan', methods=['POST'])
@login_required
def generate_study_plan_route():
    user_input = request.form.get('user_input', '')  # Get input from form
    full_tasks, cleaned_tasks, total_days = generate_study_plan(user_input)
    
    # Distribute cleaned tasks across days
    tasks_per_day = max(1, len(cleaned_tasks) // total_days)  # Ensure at least 1 task per day
    today_tasks = cleaned_tasks[:tasks_per_day]  # Tasks for today
    tomorrow_tasks = cleaned_tasks[tasks_per_day:tasks_per_day * 2]  # Tasks for tomorrow
    future_tasks = cleaned_tasks[tasks_per_day * 2:]  # Remaining tasks for future
    
    # Prepare JSON response with only cleaned task names
    study_plan = {
        "today": today_tasks,
        "tomorrow": tomorrow_tasks,
        "future": future_tasks,
        "total_days": total_days
    }
    
    # Store full tasks (with priorities and deadlines) in session for later use (e.g., saving to DB)
    session['full_study_plan'] = full_tasks
    
    return jsonify(study_plan)  # Return cleaned tasks as JSON

# Route to confirm and save study plan
@study_plan_bp.route('/confirm_study_plan', methods=['POST'])
@login_required
def confirm_study_plan():
    # Use full tasks from session (with priorities and deadlines) for database storage
    full_tasks = session.get('full_study_plan', [])
    today = datetime.now().date()
    user_id = session['user_id']

    try:
        conn = get_db_connection()
        for i, full_task in enumerate(full_tasks):
            # Extract task name, priority, and deadline from full_task
            task_name = full_task.split("(Priority:")[0].strip()
            priority = full_task.split("Priority:")[1].split(",")[0].strip() if "Priority:" in full_task else "Medium"
            deadline_day = full_task.split("Deadline: Day")[1].strip(")") if "Deadline: Day" in full_task else str(i + 1)
            date = today + timedelta(days=int(deadline_day) - 1)  # Convert "Day X" to actual date
            
            conn.execute(
                "INSERT INTO tasks (user_id, title, priority, deadline, status) VALUES (?, ?, ?, ?, 'todo')", 
                (user_id, task_name, priority, date.strftime('%Y-%m-%d'))
            )
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"Database error: {e}")
        return "Database error occurred. Please try again later.", 500
    finally:
        conn.close()

    return redirect(url_for('index'))