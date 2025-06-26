import os
import requests
from flask import Blueprint, request, render_template, redirect, url_for, session, jsonify, flash
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sqlite3
import logging
from functools import wraps
import re

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Blueprint
study_plan_bp = Blueprint('study_plan', __name__, template_folder='templates')

# Configuration
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
if not COHERE_API_KEY:
    raise ValueError("Missing Cohere API Key! Set it in a .env file.")

COHERE_API_URL = "https://api.cohere.ai/v1/chat"

def get_db_connection():
    """Get a database connection with Row factory"""
    conn = sqlite3.connect('tasks.db')
    conn.row_factory = sqlite3.Row
    return conn

def login_required(f):
    """Decorator to ensure user is logged in"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def generate_study_plan(user_input):
    default_days = 10

    # Extract topic and days
    days = default_days
    topic = user_input.strip()
    if "in" in user_input.lower() and "days" in user_input.lower():
        try:
            days = int(user_input.lower().split("in")[1].split("days")[0].strip())
            topic = user_input.lower().split("in")[0].strip()
        except:
            pass

    prompt = (
        f"Generate a personalized and detailed {days}-day plan to achieve the goal: '{topic}'.\n"
        "Each day must be unique and should start with 'Day X:'.\n"
        "For every day, include:\n"
        "1. One specific task\n"
        "2. A priority (High, Medium, Low)\n"
        "Format:\n"
        "Day 1: [Task] (Priority: High)\n"
        "Avoid using vague terms like 'Self-study', 'Review', or 'Continue'. Be specific, actionable, and diverse."
    )

    headers = {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "message": prompt,
        "model": "command",  # You can try "command-nightly" for better results
        "temperature": 0.5,
    }

    try:
        response = requests.post(COHERE_API_URL, headers=headers, json=payload)
        data = response.json()

        # Safety check
        if 'text' not in data:
            print("Invalid response:", data)
            return None, None, days

        text = data['text']
        lines = [line.strip() for line in text.split('\n') if line.startswith("Day")]
        cleaned = [line.split(":", 1)[-1].split("(Priority:")[0].strip() for line in lines]

        # Retry if too few lines
        if len(lines) < int(days * 0.7):
            print("Too few tasks, retrying...")
            return generate_study_plan(user_input)  # Optional retry

        return lines, cleaned, days

    except Exception as e:
        print(f"Error in Cohere API: {e}")
        return None, None, days


@study_plan_bp.route('/study_plan/', methods=['GET', 'POST'])
@login_required
def study_plan():
    """Handle study plan generation and display"""
    if request.method == 'POST':
        user_input = request.form.get('user_input', '').strip()
        if not user_input:
            flash('Please enter what you want to study', 'error')
            return redirect(url_for('study_plan.study_plan'))
        
        full_tasks, cleaned_tasks, total_days = generate_study_plan(user_input)
        
        if not full_tasks or not cleaned_tasks:
            flash('Failed to generate study plan. Please try again.', 'error')
            return redirect(url_for('study_plan.study_plan'))
        
        session['full_study_plan'] = full_tasks
        return render_template('study_plan.html', plan=cleaned_tasks)
    
    return render_template('study_plan.html', plan=None)

@study_plan_bp.route('/confirm_study_plan', methods=['POST'])
@login_required
def confirm_study_plan():
    """Save the generated study plan to database"""
    if 'full_study_plan' not in session:
        flash('No study plan to save', 'error')
        return redirect(url_for('study_plan.study_plan'))
    
    full_tasks = session['full_study_plan']
    user_id = session['user_id']
    today = datetime.now().date()
    
    try:
        conn = get_db_connection()
        for full_task in full_tasks:
            try:
                # Parse task components
                day_part, rest = full_task.split(":", 1)
                day_num = int(day_part.replace("Day", "").strip())
                task_part = rest.split("(Priority:")[0].strip()


                match = re.match(r'(.+?)\s*\(Priority:\s*(High|Medium|Low)\)', rest)
                if match:
                    task_part = match.group(1).strip()
                    priority = match.group(2).strip()
                else:
                    task_part = rest.strip()
                    priority = "Medium"
               
                
                # Calculate deadline date
                deadline = today + timedelta(days=day_num - 1)
                
                # Insert into database
                conn.execute(
                    """INSERT INTO tasks 
                    (user_id, title, priority, deadline, status, created_at) 
                    VALUES (?, ?, ?, ?, 'pending', datetime('now'))""",
                    (user_id, task_part, priority, deadline.strftime('%Y-%m-%d'))
                )
            except (ValueError, IndexError) as e:
                logger.error(f"Error parsing task '{full_task}': {str(e)}")
                continue
        
        conn.commit()
        flash('Study plan saved successfully!', 'success')
    except sqlite3.Error as e:
        logger.error(f"Database error: {str(e)}")
        flash('Failed to save study plan to database', 'error')
    finally:
        conn.close()
        session.pop('full_study_plan', None)
    
    return redirect(url_for('index'))