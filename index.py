from flask import Flask, Blueprint, render_template, request, jsonify, redirect, url_for, session, flash, abort, send_file
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import secrets
import re
from study_plan import generate_study_plan, study_plan_bp
from schedule import ScheduleGenerator
from utils import get_db_connection
from PIL import Image, ImageDraw, ImageFont
import io
import json
import os
import sqlite3
import matplotlib.pyplot as plt
import numpy as np
from io import BytesIO
import base64
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "your_secret_key"

app.register_blueprint(study_plan_bp)

app.secret_key = 'your-very-secure-secret-key-here'  # Change this to a real secret key
app.config['SESSION_TYPE'] = 'filesystem'  # Or 'redis', 'memcached', etc.
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)  # Session expires after 1 day
app.config['UPLOAD_FOLDER'] = 'uploads'  # Folder for file uploads

username = None
import logging
logging.basicConfig(level=logging.DEBUG)

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
# Add custom filter

# Add this custom filter
@app.template_filter('from_json')
def from_json_filter(data):
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return []
    return data or []

@app.route('/avatar/<username>', methods=['GET'])
def generate_avatar(username):
    img_size = (128, 128)
    bg_color = "#2d89ef"
    text_color = "#ffffff"
    font_size = 60
    initial = username[0].upper()
    img = Image.new("RGB", img_size, bg_color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    text_width, text_height = draw.textsize(initial, font=font)
    position = ((img_size[0] - text_width) / 2, (img_size[1] - text_height) / 2)
    draw.text(position, initial, font=font, fill=text_color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")

def get_db_connection():
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        profile_pic TEXT DEFAULT 'default.png'
                    )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS teams (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        join_code TEXT UNIQUE NOT NULL,
                        created_by INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (created_by) REFERENCES users(id)
                    )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS team_members (
                        team_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        is_manager BOOLEAN DEFAULT FALSE,
                        role TEXT DEFAULT 'Member',
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (team_id, user_id),
                        FOREIGN KEY (team_id) REFERENCES teams(id),
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT,
                        deadline TEXT,
                        priority TEXT CHECK(priority IN ('High', 'Medium', 'Low')) DEFAULT 'Medium',
                        status TEXT CHECK(status IN ('todo', 'inprogress', 'completed', 'deleted', 'pending')) DEFAULT 'todo',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        team_id INTEGER,
                        progress INTEGER DEFAULT 0,
                        resources TEXT,
                        needs_approval BOOLEAN DEFAULT FALSE,
                        approved_by INTEGER,
                        FOREIGN KEY (user_id) REFERENCES users (id),
                        FOREIGN KEY (team_id) REFERENCES teams (id)
                    )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS task_updates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        update_type TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (task_id) REFERENCES tasks(id),
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )''')

        try:
            conn.execute('ALTER TABLE team_members ADD COLUMN role TEXT DEFAULT "Member"')
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute('ALTER TABLE tasks ADD COLUMN description TEXT')
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute('ALTER TABLE tasks ADD COLUMN priority TEXT CHECK(priority IN ("High", "Medium", "Low")) DEFAULT "Medium"')
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute('ALTER TABLE tasks ADD COLUMN team_id INTEGER')
            conn.execute('ALTER TABLE tasks ADD FOREIGN KEY (team_id) REFERENCES teams(id)')
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute('ALTER TABLE tasks ADD COLUMN progress INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute('ALTER TABLE tasks ADD COLUMN resources TEXT')
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute('ALTER TABLE tasks ADD COLUMN needs_approval BOOLEAN DEFAULT FALSE')
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute('ALTER TABLE tasks ADD COLUMN approved_by INTEGER')
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute('ALTER TABLE tasks RENAME TO temp_tasks')
            conn.execute('''CREATE TABLE tasks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            title TEXT NOT NULL,
                            description TEXT,
                            deadline TEXT,
                            priority TEXT CHECK(priority IN ('High', 'Medium', 'Low')) DEFAULT 'Medium',
                            status TEXT CHECK(status IN ('todo', 'inprogress', 'completed', 'deleted', 'pending')) DEFAULT 'todo',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            team_id INTEGER,
                            progress INTEGER DEFAULT 0,
                            resources TEXT,
                            needs_approval BOOLEAN DEFAULT FALSE,
                            approved_by INTEGER,
                            FOREIGN KEY (user_id) REFERENCES users (id),
                            FOREIGN KEY (team_id) REFERENCES teams (id)
                        )''')
            conn.execute('INSERT INTO tasks SELECT * FROM temp_tasks')
            conn.execute('DROP TABLE temp_tasks')
        except sqlite3.OperationalError:
            pass

        conn.commit()

init_db()

def current_user_is_manager():
    if 'user_id' not in session:
        return False
    conn = get_db_connection()
    is_manager = conn.execute('''
        SELECT is_manager FROM team_members
        WHERE user_id = ? AND team_id = (
            SELECT team_id FROM team_members WHERE user_id = ?
        )
    ''', (session['user_id'], session['user_id'])).fetchone()
    conn.close()
    return is_manager and is_manager['is_manager']

def current_user_has_approval_permission():
    return current_user_is_manager()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('register'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Invalid username or password")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        password_hash = generate_password_hash(password)
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                         (username, email, password_hash))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return render_template('register.html', error="Username or email already exists")
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

# In index.py, update the /add route

# ... (other imports and setup remain unchanged)
bp = Blueprint('tasks', __name__)

@bp.route('/add', methods=['POST'])
@login_required
def add_task():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"success": False, "error": "User not authenticated"}), 401

    logging.debug(f"Incoming request data: {request.form} or {request.get_json() if request.is_json else 'No JSON'}")

    # Handle form data (default for HTML form submission)
    title = request.form.get('title')
    description = request.form.get('description', '')
    deadline = request.form.get('deadline')
    priority = request.form.get('priority', 'Medium')

    # Fallback to JSON data if form data is not present
    if not title and request.is_json:
        data = request.get_json()
        title = data.get('title')
        description = data.get('description', '')
        deadline = data.get('deadline')
        priority = data.get('priority', 'Medium')

    # Validate required fields
    if not title:
        return jsonify({"success": False, "error": "Title is required"}), 400

    # Validate deadline format
    if deadline and not re.match(r'^\d{4}-\d{2}-\d{2}$', deadline):
        return jsonify({"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}), 400

    if not deadline or not re.match(r'^\d{4}-\d{2}-\d{2}$', deadline):
        deadline = datetime.now().strftime('%Y-%m-%d')

    # Validate priority
    valid_priorities = {'High', 'Medium', 'Low'}
    if priority not in valid_priorities:
        priority = 'Medium'

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO tasks (user_id, title, description, deadline, priority, status) 
            VALUES (?, ?, ?, ?, ?, 'todo')
        """, (user_id, title, description, deadline, priority))
        conn.commit()
        
        task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        new_task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        
        return jsonify({
            "success": True,
            "message": "Task created successfully",
            "task": dict(new_task)
        }), 201
    except sqlite3.IntegrityError as e:
        conn.rollback()
        return jsonify({"success": False, "error": "Database integrity error: " + str(e)}), 400
    except Exception as e:
        conn.rollback()
        logging.error(f"Error in add_task: {str(e)}")
        return jsonify({"success": False, "error": "An error occurred: " + str(e)}), 500
    finally:
        conn.close()


app.register_blueprint(bp, url_prefix='/tasks') 
@app.route('/index')
@login_required
def index():
    user_id = session['user_id']
    username = session['username']
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    conn = get_db_connection()
    today_tasks = conn.execute('''SELECT * FROM tasks 
                                WHERE user_id = ? AND deadline = ? AND status = 'todo' 
                                ORDER BY 
                                    CASE priority 
                                        WHEN 'High' THEN 1 
                                        WHEN 'Medium' THEN 2 
                                        WHEN 'Low' THEN 3 
                                        ELSE 4 
                                    END, 
                                    deadline ASC''', 
                              (user_id, today.strftime('%Y-%m-%d'))).fetchall()
    tomorrow_tasks = conn.execute('''SELECT * FROM tasks 
                                   WHERE user_id = ? AND deadline = ? AND status = 'todo' 
                                   ORDER BY 
                                       CASE priority 
                                           WHEN 'High' THEN 1 
                                           WHEN 'Medium' THEN 2 
                                           WHEN 'Low' THEN 3 
                                           ELSE 4 
                                       END, 
                                       deadline ASC''', 
                                 (user_id, tomorrow.strftime('%Y-%m-%d'))).fetchall()
    future_tasks = conn.execute('''SELECT * FROM tasks 
                                 WHERE user_id = ? AND deadline > ? AND status = 'todo' 
                                 ORDER BY 
                                     CASE priority 
                                         WHEN 'High' THEN 1 
                                         WHEN 'Medium' THEN 2 
                                         WHEN 'Low' THEN 3 
                                         ELSE 4 
                                     END, 
                                     deadline ASC''', 
                               (user_id, tomorrow.strftime('%Y-%m-%d'))).fetchall()
    completed_tasks = conn.execute('''SELECT * FROM tasks 
                                    WHERE user_id = ? AND status = 'completed' 
                                    ORDER BY deadline DESC''', 
                                  (user_id,)).fetchall()
    conn.close()
    app.logger.debug('Rendering index with %d today, %d tomorrow, %d future, %d completed tasks', 
                     len(today_tasks), len(tomorrow_tasks), len(future_tasks), len(completed_tasks))
    return render_template('index.html', 
                         today_tasks=today_tasks, 
                         tomorrow_tasks=tomorrow_tasks, 
                         future_tasks=future_tasks, 
                         completed_tasks=completed_tasks,
                         today=today.strftime('%Y-%m-%d'), 
                         username=username)

# ... (rest of index.py remains unchanged)

@app.route('/search', methods=['GET'])
@login_required
def search_tasks():
    user_id = session['user_id']
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({"tasks": []})
    conn = get_db_connection()
    results = conn.execute('''SELECT * FROM tasks 
                            WHERE user_id = ? 
                            AND (title LIKE ? OR description LIKE ?) 
                            AND status != 'deleted'
                            ORDER BY 
                                CASE priority 
                                    WHEN 'High' THEN 1 
                                    WHEN 'Medium' THEN 2 
                                    WHEN 'Low' THEN 3 
                                END,
                            deadline ASC''', 
                         (user_id, f'%{query}%', f'%{query}%')).fetchall()
    conn.close()
    tasks = []
    for task in results:
        tasks.append({
            'id': task['id'],
            'title': task['title'],
            'description': task['description'],
            'deadline': task['deadline'],
            'priority': task['priority'],
            'status': task['status']
        })
    return jsonify({"tasks": tasks})


@app.route('/status/<int:task_id>/<string:new_status>', methods=['POST'])
@login_required
def update_status(task_id, new_status):
    user_id = session['user_id']
    conn = get_db_connection()
    
    task = conn.execute("SELECT * FROM tasks WHERE id = ? AND user_id = ?", 
                       (task_id, user_id)).fetchone()
    
    if not task:
        conn.close()
        return jsonify({"success": False, "message": "Task not found"}), 404
    
    if new_status == 'inprogress' and task['needs_approval'] and not task['approved_by']:
        conn.close()
        return jsonify({
            "success": False,
            "message": "Approval required before moving to inprogress"
        }), 403
    
    conn.execute("UPDATE tasks SET status = ? WHERE id = ? AND user_id = ?", 
                (new_status, task_id, user_id))
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "message": f"Task status updated to {new_status}"
    })

@app.route('/update_task_priority/<int:task_id>', methods=['POST'])
@login_required
def update_task_priority(task_id):
    new_priority = request.json.get('priority')
    if new_priority not in ['High', 'Medium', 'Low']:
        return jsonify({'success': False, 'error': 'Invalid priority'}), 400
    
    conn = get_db_connection()
    conn.execute('''
        UPDATE tasks 
        SET priority = ? 
        WHERE id = ? AND user_id = ?
    ''', (new_priority, task_id, session['user_id']))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/quick_add_task', methods=['POST'])
@login_required
def quick_add_task():
    title = request.form.get('title')
    if not title:
        flash('Task title cannot be empty', 'error')
        return redirect(url_for('todo_tasks'))
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO tasks (user_id, title, status, priority)
        VALUES (?, ?, 'todo', 'Medium')
    ''', (session['user_id'], title))
    conn.commit()
    conn.close()
    
    flash('Task added successfully', 'success')
    return redirect(url_for('todo_tasks'))

@app.route('/task_updates', methods=['POST'])
@login_required
def add_task_update():
    user_id = session['user_id']
    task_id = request.json.get('task_id')
    notes = request.json.get('notes', '')
    
    conn = get_db_connection()
    conn.execute("INSERT INTO task_updates (task_id, user_id, update_type) VALUES (?, ?, ?)",
                (task_id, user_id, notes))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "Progress update added"})

@app.route('/update/<int:task_id>', methods=['POST'])
@login_required
def update_task(task_id):
    user_id = session['user_id']
    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json()
        new_title = data.get('title')
        new_description = data.get('description', '')
        new_deadline = data.get('deadline')
        new_priority = data.get('priority', 'Medium')
    else:
        new_title = request.form['title']
        new_description = request.form.get('description', '')
        new_deadline = request.form['deadline']
        new_priority = request.form.get('priority', 'Medium')
    conn = get_db_connection()
    conn.execute("UPDATE tasks SET title = ?, description = ?, deadline = ?, priority = ? WHERE id = ? AND user_id = ?", 
                (new_title, new_description, new_deadline, new_priority, task_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({
        "success": True, 
        "message": "Task updated successfully",
        "task": {
            "id": task_id,
            "title": new_title,
            "description": new_description,
            "deadline": new_deadline,
            "priority": new_priority
        }
    })

def get_team_id():
    if 'user_id' not in session:
        return None
    conn = get_db_connection()
    try:
        team = conn.execute('''
            SELECT team_id FROM team_members
            WHERE user_id = ?
        ''', (session['user_id'],)).fetchone()
        return team['team_id'] if team else None
    finally:
        conn.close()

STREAK_FILE = 'streak.json'
if not os.path.exists(STREAK_FILE):
    with open(STREAK_FILE, 'w') as f:
        json.dump({'streak': 0, 'last_updated': None}, f)

def load_streak():
    with open(STREAK_FILE, 'r') as f:
        return json.load(f)

def save_streak(data):
    with open(STREAK_FILE, 'w') as f:
        json.dump(data, f)

@app.route('/update_streak', methods=['POST'])
@login_required
def update_streak():
    user_id = session['user_id']
    conn = get_db_connection()
    today = datetime.now().date()
    today_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND deadline = ? AND status IN ("todo", "completed")', 
                              (user_id, today.strftime('%Y-%m-%d'))).fetchone()[0]
    completed_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND deadline = ? AND status = "completed"', 
                                  (user_id, today.strftime('%Y-%m-%d'))).fetchone()[0]
    conn.close()
    today_progress = (completed_tasks / today_tasks * 100) if today_tasks > 0 else 0
    streak_data = load_streak()
    last_updated = datetime.strptime(streak_data['last_updated'], '%Y-%m-%d').date() if streak_data['last_updated'] else None
    if today_progress == 100:
        if last_updated == today - timedelta(days=1):
            streak_data['streak'] += 1
        else:
            streak_data['streak'] = 1
        streak_data['last_updated'] = today.strftime('%Y-%m-%d')
        save_streak(streak_data)
    elif last_updated and last_updated < today - timedelta(days=1):
        streak_data['streak'] = 0
        streak_data['last_updated'] = None
        save_streak(streak_data)
    return jsonify({'success': True, 'streak': streak_data['streak'], 'today_progress': today_progress})

@app.route('/tasks')
@login_required
def tasks_dashboard():
    user_id = session['user_id']
    username = session['username']
    today = datetime.now().date()
    last_month = today - timedelta(days=30)
    conn = get_db_connection()
    total_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ?', (user_id,)).fetchone()[0]
    last_month_total = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND created_at >= ?', 
                                   (user_id, last_month)).fetchone()[0]
    completed_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "completed"', 
                                  (user_id,)).fetchone()[0]
    last_month_completed = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "completed" AND created_at >= ?', 
                                       (user_id, last_month)).fetchone()[0]
    in_progress_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "inprogress"', 
                                    (user_id,)).fetchone()[0]
    last_month_in_progress = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "inprogress" AND created_at >= ?', 
                                         (user_id, last_month)).fetchone()[0]
    todo_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "todo"', 
                             (user_id,)).fetchone()[0]
    last_month_todos = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "todo" AND created_at >= ?', 
                                   (user_id, last_month)).fetchone()[0]
    priority_counts = {
        'high': conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND priority = "High"', 
                             (user_id,)).fetchone()[0],
        'medium': conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND priority = "Medium"', 
                               (user_id,)).fetchone()[0],
        'low': conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND priority = "Low"', 
                            (user_id,)).fetchone()[0]
    }

    today_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND deadline = ? AND status IN ("todo", "completed")', 
                              (user_id, today.strftime('%Y-%m-%d'))).fetchone()[0]
    today_completed = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ? AND deadline = ? AND status = "completed"', 
                                  (user_id, today.strftime('%Y-%m-%d'))).fetchone()[0]
    today_progress = (today_completed / today_tasks * 100) if today_tasks > 0 else 0
    streak_data = load_streak()
    return render_template('tasks.html',
                         total_tasks=total_tasks,
                         last_month_tasks=last_month_total,
                         completed_tasks=completed_tasks,
                         last_month_completed=last_month_completed,
                         in_progress_tasks=in_progress_tasks,
                         last_month_in_progress=last_month_in_progress,
                         todo_tasks=todo_tasks,
                         last_month_todos=last_month_todos,
                         priority_counts=priority_counts,
                         today_progress=today_progress,
                         streak=streak_data['streak'],
                         username=username)

@app.route('/inprogress')
@login_required
def inprogress_tasks():
    user_id = session['user_id']
    conn = get_db_connection()
    
    tasks = conn.execute('''
        SELECT * FROM tasks 
        WHERE user_id = ? AND status = 'inprogress'
        ORDER BY deadline ASC
    ''', (user_id,)).fetchall()
    
    conn.close()
    
    return render_template('inprogress.html', 
                         tasks=tasks,
                         show_empty=not tasks)

@app.route('/todo')
@login_required
def todo_tasks():
    conn = get_db_connection()
    
    tasks = conn.execute('''
        SELECT * FROM tasks 
        WHERE user_id = ? AND status = 'todo'
        ORDER BY 
            CASE priority 
                WHEN 'High' THEN 1 
                WHEN 'Medium' THEN 2 
                WHEN 'Low' THEN 3 
            END,
            deadline ASC
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    return render_template('todo.html', 
                         tasks=tasks,
                         current_time=datetime.now().strftime('%Y-%m-%d'))


@app.route('/create_team', methods=['POST'])
@login_required
def create_team():
    team_name = request.form.get('team_name')
    role = request.form.get('role', 'Manager')
    conn = get_db_connection()
    
    join_code = secrets.token_hex(4).upper()
    while conn.execute('SELECT 1 FROM teams WHERE join_code = ?', (join_code,)).fetchone():
        join_code = secrets.token_hex(4).upper()
    
    conn.execute('INSERT INTO teams (name, join_code, created_by) VALUES (?, ?, ?)',
                (team_name, join_code, session['user_id']))
    team_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    
    conn.execute('INSERT INTO team_members (team_id, user_id, is_manager, role) VALUES (?, ?, 1, ?)',
                (team_id, session['user_id'], role))
    conn.commit()
    conn.close()
    flash('Team created successfully!', 'success')
    return redirect(url_for('teams'))

@app.route('/join_team', methods=['POST'])
@login_required
def join_team():
    join_code = request.form.get('join_code', '').strip().upper()
    role = request.form.get('role', 'Member')
    
    if not join_code:
        flash('Please enter a join code', 'error')
        return redirect(url_for('teams'))

    conn = get_db_connection()
    try:
        team = conn.execute('SELECT * FROM teams WHERE join_code = ?', (join_code,)).fetchone()
        if not team:
            flash('Invalid join code', 'error')
            return redirect(url_for('teams'))
        
        # Check if user is already in the team
        existing = conn.execute('''
            SELECT 1 FROM team_members 
            WHERE team_id = ? AND user_id = ?
        ''', (team['id'], session['user_id'])).fetchone()
        
        if existing:
            flash('You are already a member of this team', 'info')
            return redirect(url_for('teams'))
        
        # Join the team
        conn.execute('''
            INSERT INTO team_members (team_id, user_id, role) 
            VALUES (?, ?, ?)
        ''', (team['id'], session['user_id'], role))
        conn.commit()
        
        flash('Successfully joined team!', 'success')
        return redirect(url_for('teams'))
        
    except Exception as e:
        conn.rollback()
        flash('Failed to join team: ' + str(e), 'error')
        return redirect(url_for('teams'))
    finally:
        conn.close()

@app.route('/leave_team', methods=['POST'])
@login_required
def leave_team():
    conn = get_db_connection()

    try:
        # Step 1: Get the user's team membership
        team_member = conn.execute('''
            SELECT team_id, is_manager FROM team_members
            WHERE user_id = ?
        ''', (session['user_id'],)).fetchone()

        if not team_member:
            flash('You are not in a team', 'error')
            return redirect(url_for('teams'))

        team_id = team_member['team_id']
        is_manager = team_member['is_manager']

        if is_manager:
            # Step 2: Get all user IDs in this team
            team_user_ids = [
                row['user_id'] for row in conn.execute(
                    'SELECT user_id FROM team_members WHERE team_id = ?', 
                    (team_id,)
                ).fetchall()
            ]

            print("Manager is deleting team_id:", team_id)
            print("Team user IDs to delete:", team_user_ids)

            if not team_user_ids:
                flash("No users found in the team!", "error")
                return redirect(url_for('teams'))

            # Step 3: Delete all tasks for these users
            conn.executemany(
                'DELETE FROM tasks WHERE user_id = ?',
                [(uid,) for uid in team_user_ids]
            )

            # Step 4: Delete all team memberships for these users
            conn.executemany(
                'DELETE FROM team_members WHERE user_id = ?',
                [(uid,) for uid in team_user_ids]
            )

            # Step 5: Delete the team itself
            conn.execute('DELETE FROM teams WHERE id = ?', (team_id,))

            # Step 6: Delete all users who were in this team
            conn.executemany(
                'DELETE FROM users WHERE id = ?',
                [(uid,) for uid in team_user_ids]
            )

            conn.commit()

            # Step 7: Clear session since user is deleted too
            session.clear()
            flash('Team, all associated data, and team members deleted. You have been logged out.', 'success')
            return redirect(url_for('login'))

        else:
            # If regular member, remove user from team and delete only their tasks
            conn.execute(
                'DELETE FROM tasks WHERE team_id = ? AND user_id = ?', 
                (team_id, session['user_id'])
            )
            conn.execute(
                'DELETE FROM team_members WHERE team_id = ? AND user_id = ?', 
                (team_id, session['user_id'])
            )

            conn.commit()
            flash('Left team successfully', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'Failed to leave/delete team: {str(e)}', 'error')
        print(f"[ERROR] leave_team: {e}")
    finally:
        conn.close()

    return redirect(url_for('teams'))


@app.route('/team_members')
@login_required
def team_members():
    conn = get_db_connection()
    
    members = conn.execute('''
        SELECT users.id, users.username, team_members.joined_at,
               team_members.is_manager, team_members.role
        FROM team_members
        JOIN users ON team_members.user_id = users.id
        WHERE team_members.team_id = (
            SELECT team_id FROM team_members WHERE user_id = ?
        )
        ORDER BY is_manager DESC, team_members.joined_at ASC
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    return jsonify([dict(member) for member in members])

@app.route('/create_team_task', methods=['POST'])
@login_required
def create_team_task():
    title = request.form.get('title')
    description = request.form.get('description')
    deadline = request.form.get('deadline')
    priority = request.form.get('priority', 'Medium')
    assign_to = request.form.get('assign_to')
    
    conn = get_db_connection()
    
    is_manager = conn.execute('''
        SELECT is_manager FROM team_members
        WHERE user_id = ? AND team_id = (
            SELECT team_id FROM team_members WHERE user_id = ?
        )
    ''', (session['user_id'], session['user_id'])).fetchone()
    
    if not is_manager or not is_manager['is_manager']:
        conn.close()
        flash('You do not have permission to assign tasks', 'error')
        return redirect(url_for('teams'))
    
    conn.execute('''
        INSERT INTO tasks (title, description, deadline, priority, status, user_id, team_id)
        VALUES (?, ?, ?, ?, 'todo', ?, ?)
    ''', (title, description, deadline, priority, assign_to, get_team_id()))
    conn.commit()
    conn.close()
    
    flash('Task created successfully', 'success')
    return redirect(url_for('teams'))

index_bp = Blueprint('index', __name__)

@index_bp.route('/study_plan', methods=['GET', 'POST'])
@login_required
def study_plan():
    user_id = session['user_id']
    plan = None
    if request.method == 'POST':
        user_input = request.form.get('user_input', '')
        if user_input:
            full_tasks, cleaned_tasks, total_days = generate_study_plan(user_input)
            session['full_study_plan'] = full_tasks
            plan = cleaned_tasks
            return render_template('study_plan.html', plan=plan)
    return render_template('study_plan.html', plan=None)

app.register_blueprint(index_bp)

@app.route('/schedule')
@login_required
def schedule():
    try:
        generator = ScheduleGenerator()
        result = generator.generate_schedule()
        
        if result["error"]:
            flash(result["message"], "error")
            logging.error(f"Schedule generation failed: {result['message']}")
        else:
            try:
                schedule_data = json.loads(result["data"])
                logging.debug(f"Generated schedule: {schedule_data}")
            except json.JSONDecodeError:
                flash("Invalid schedule data format", "error")
                logging.error("Failed to parse schedule data")
        
        return render_template('schedule.html', 
                            schedule=json.loads(result["data"]) if not result["error"] else {})
        
    except Exception as e:
        logging.error(f"Route Error: {str(e)}")
        flash("An error occurred", "error")
        return redirect(url_for('index'))

@app.route('/deleted')
@login_required
def deleted_tasks():
    try:
        user_id = session['user_id']
        today = datetime.now().date().strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        
        deleted_tasks = conn.execute('''SELECT * FROM tasks 
                                      WHERE user_id = ? AND status = 'deleted'
                                      ORDER BY deadline DESC''', 
                                   (user_id,)).fetchall()
        
        overdue_tasks = conn.execute('''SELECT * FROM tasks 
                                      WHERE user_id = ? AND deadline < ? AND status NOT IN ('completed', 'deleted')
                                      ORDER BY deadline ASC''', 
                                   (user_id, today)).fetchall()
        
        conn.close()
        return render_template('deleted.html', deleted_tasks=deleted_tasks, overdue_tasks=overdue_tasks)
    
    except KeyError:
        return "User not authenticated", 403
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "An error occurred while fetching tasks", 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return "An unexpected error occurred", 500

@app.route('/permanent-delete/<int:task_id>', methods=['POST'])
@login_required
def permanent_delete_task(task_id):
    try:
        user_id = session['user_id']
        conn = get_db_connection()
        conn.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        conn.commit()
        conn.close()
        return jsonify({"message": "Task deleted permanently"})
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Failed to delete task"}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/restore/<int:task_id>', methods=['POST'])
@login_required
def restore_task(task_id):
    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute("UPDATE tasks SET status = 'todo' WHERE id = ? AND user_id = ?", 
                 (task_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Task restored successfully"})

@app.route('/delete/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    user_id = session['user_id']
    conn = get_db_connection()
    task = conn.execute("SELECT * FROM tasks WHERE id = ? AND user_id = ?", 
                        (task_id, user_id)).fetchone()
    if not task:
        conn.close()
        return jsonify({"success": False, "message": "Task not found"}), 404
    conn.execute("UPDATE tasks SET status = 'deleted' WHERE id = ? AND user_id = ?", 
                 (task_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Task moved to deleted"})

@app.route('/empty-trash', methods=['POST'])
@login_required
def empty_trash():
    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute("DELETE FROM tasks WHERE user_id = ? AND status = 'deleted'", 
                 (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Trash emptied"})

@app.route('/completedo')
@login_required
def completed_tasks():
    user_id = session['user_id']
    conn = get_db_connection()
    tasks = conn.execute('''SELECT * FROM tasks 
                          WHERE user_id = ? AND status = 'completed'
                          ORDER BY deadline DESC''', 
                       (user_id,)).fetchall()
    conn.close()
    return render_template('completed.html', tasks=tasks)

@app.route('/start_task/<int:task_id>', methods=['POST'])
@login_required
def start_task(task_id):
    conn = get_db_connection()
    conn.execute('''
        UPDATE tasks SET status = 'inprogress' 
        WHERE id = ? AND user_id = ?
    ''', (task_id, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/complete_task/<int:task_id>', methods=['POST'])
@login_required
def complete_task(task_id):
    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE tasks SET status = 'completed', progress = 100 
            WHERE id = ? AND user_id = ?
        ''', (task_id, session['user_id']))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()

@app.route('/logout', methods=['GET'])
@login_required
def logout():
    user_id = session.get('user_id')
    app.logger.debug("Logout route accessed via %s for user_id: %s", request.method, user_id)

    if not session:
        app.logger.debug("Session is empty before logout")
    else:
        app.logger.debug("Session keys before clear: %s", list(session.keys()))
        session.clear()
        app.logger.debug("Session keys after clear: %s", list(session.keys()))

    flash('You have been logged out successfully.', 'success')
    
    response = redirect(url_for('login'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'

    return response

@app.route('/assign_team_task', methods=['POST'])
@login_required
def assign_team_task():
    if not current_user_is_manager():
        flash('Only managers can assign tasks', 'error')
        return redirect(url_for('teams'))
    
    title = request.form.get('title')
    description = request.form.get('description')
    deadline = request.form.get('deadline')
    priority = request.form.get('priority', 'Medium')
    assign_to = request.form.get('assign_to')
    
    if not (title and deadline and assign_to):
        flash('Missing required fields.', 'error')
        return redirect(url_for('teams'))

    conn = get_db_connection()
    team_id = get_team_id()
    
    if not team_id:
        conn.close()
        flash('You are not part of any team.', 'error')
        return redirect(url_for('teams'))

    resources = []
    if 'resources' in request.files:
        files = request.files.getlist('resources')
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                resources.append(filename)
    
    try:
        conn.execute('''
            INSERT INTO tasks (title, description, deadline, priority, user_id, team_id, status, progress, resources)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?)
        ''', (title, description, deadline, priority, assign_to, team_id, json.dumps(resources)))
        conn.commit()
        flash('Task assigned successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash('Failed to assign task.', 'error')
        print(e)
    finally:
        conn.close()

    return redirect(url_for('teams'))

@app.route('/approve_task/<int:task_id>', methods=['POST'])
@login_required
def approve_task(task_id):
    conn = get_db_connection()
    try:
        task = conn.execute('''
            SELECT id FROM tasks WHERE id = ? AND user_id = ? AND status = 'pending'
        ''', (task_id, session['user_id'])).fetchone()
        
        if task:
            conn.execute('''
                UPDATE tasks SET status = 'inprogress', progress = 0
                WHERE id = ?
            ''', (task_id,))
            conn.commit()
            flash('Task accepted and moved to in-progress!', 'success')
        else:
            flash('Invalid task or already approved', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('teams'))

@app.route('/update_task_status/<int:task_id>', methods=['POST'])
@login_required
def update_task_status(task_id):
    new_status = request.json.get('status')
    progress = request.json.get('progress', 0)
    
    if new_status not in ['inprogress', 'completed']:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400
    
    conn = get_db_connection()
    try:
        task = conn.execute('SELECT user_id FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if task['user_id'] != session['user_id']:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        conn.execute('''
            UPDATE tasks SET status = ?, progress = ?
            WHERE id = ?
        ''', (new_status, progress, task_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/upload_task_file/<int:task_id>', methods=['POST'])
@login_required
def upload_task_file(task_id):
    conn = get_db_connection()
    task = conn.execute('SELECT user_id, team_id, resources FROM tasks WHERE id = ?', (task_id,)).fetchone()
    
    if not task or (task['user_id'] != session['user_id'] and not current_user_is_manager()):
        conn.close()
        return "Unauthorized", 403
    
    resources = json.loads(task['resources'] or '[]')
    files = request.files.getlist('file')
    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            resources.append(filename)
    
    conn.execute('UPDATE tasks SET resources = ? WHERE id = ?', (json.dumps(resources), task_id))
    conn.commit()
    conn.close()
    flash('File uploaded successfully!', 'success')
    return redirect(url_for('teams'))

@app.route('/download_file/<int:task_id>/<filename>')
@login_required
def download_file(task_id, filename):
    conn = get_db_connection()
    try:
        task = conn.execute('''
            SELECT t.user_id, t.team_id, t.resources, tm.is_manager
            FROM tasks t
            LEFT JOIN team_members tm ON tm.team_id = t.team_id AND tm.user_id = ?
            WHERE t.id = ?
        ''', (session['user_id'], task_id)).fetchone()
        
        if not task:
            return "Task not found", 404
            
        # Check permissions
        if task['user_id'] != session['user_id'] and not task['is_manager']:
            return "Unauthorized", 403
            
        resources = json.loads(task['resources'] or '[]')
        if filename not in resources:
            return "File not found", 404
            
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(file_path):
            return "File not found on server", 404
            
        return send_file(file_path, as_attachment=True)
        
    except Exception as e:
        return str(e), 500
    finally:
        conn.close()

@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    if not current_user_is_manager():
        flash('Only managers can edit tasks', 'error')
        return redirect(url_for('teams'))
    
    conn = get_db_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    
    if not task:
        conn.close()
        flash('Task not found', 'error')
        return redirect(url_for('teams'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        deadline = request.form.get('deadline')
        priority = request.form.get('priority', 'Medium')
        
        resources = json.loads(task['resources'] or '[]')
        if 'resources' in request.files:
            files = request.files.getlist('resources')
            for file in files:
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    resources.append(filename)
        
        conn.execute('''
            UPDATE tasks SET title = ?, description = ?, deadline = ?, priority = ?, resources = ?
            WHERE id = ?
        ''', (title, description, deadline, priority, json.dumps(resources), task_id))
        conn.commit()
        conn.close()
        flash('Task updated successfully!', 'success')
        return redirect(url_for('teams'))
    
    conn.close()
    return render_template('edit_task.html', task=task)
# Add this new route for switching teams
@app.route('/switch_team', methods=['POST'])
@login_required
def switch_team():
    team_id = request.form.get('team_id')
    if not team_id:
        flash('No team specified', 'error')
        return redirect(url_for('teams'))
    
    conn = get_db_connection()
    try:
        # Verify user is member of this team
        is_member = conn.execute('''
            SELECT 1 FROM team_members 
            WHERE team_id = ? AND user_id = ?
        ''', (team_id, session['user_id'])).fetchone()
        
        if not is_member:
            flash('You are not a member of this team', 'error')
            return redirect(url_for('teams'))
        
        # Get team details
        team = conn.execute('SELECT * FROM teams WHERE id = ?', (team_id,)).fetchone()
        if not team:
            flash('Team not found', 'error')
            return redirect(url_for('teams'))
        
        # Update session or whatever you need to do to switch teams
        # (This depends on how you're handling multiple teams)
        flash(f'Switched to team: {team["name"]}', 'success')
        return redirect(url_for('teams'))
        
    except Exception as e:
        flash(f'Error switching teams: {str(e)}', 'error')
        return redirect(url_for('teams'))
    finally:
        conn.close()

# Update the teams route to include user's teams
@app.route('/team')
@login_required
def teams():
    user_id = session['user_id']
    conn = get_db_connection()
    
    # Get all teams the user belongs to
    user_teams = conn.execute('''
        SELECT teams.id, teams.name, teams.join_code, team_members.role, team_members.is_manager
        FROM team_members
        JOIN teams ON team_members.team_id = teams.id
        WHERE team_members.user_id = ?
    ''', (user_id,)).fetchall()
    
    # Get current team (if any)
    current_team = None
    members_with_tasks = []
    
    current_team = conn.execute('''
        SELECT teams.* FROM team_members
        JOIN teams ON team_members.team_id = teams.id
        WHERE team_members.user_id = ?
        LIMIT 1
    ''', (user_id,)).fetchone()
    
    if current_team:
        members = conn.execute('''
            SELECT users.id, users.username, team_members.is_manager, team_members.role
            FROM team_members
            JOIN users ON team_members.user_id = users.id
            WHERE team_members.team_id = ?
            ORDER BY is_manager DESC, users.username ASC
        ''', (current_team['id'],)).fetchall()
        
        for member in members:
            tasks = conn.execute('''
                SELECT * FROM tasks 
                WHERE team_id = ? AND user_id = ?
                ORDER BY 
                    CASE status
                        WHEN 'pending' THEN 1
                        WHEN 'inprogress' THEN 2
                        WHEN 'completed' THEN 3
                        ELSE 4
                    END,
                    deadline ASC
            ''', (current_team['id'], member['id'])).fetchall()
            
            has_active_task = conn.execute(
                'SELECT 1 FROM tasks WHERE user_id = ? AND status IN ("pending", "inprogress") AND team_id = ?',
                (member['id'], current_team['id'])
            ).fetchone() is not None
            
            members_with_tasks.append({
                'id': member['id'],
                'username': member['username'],
                'is_manager': member['is_manager'],
                'role': member['role'],
                'tasks': [dict(task) for task in tasks],
                'has_active_task': has_active_task
            })
    
    conn.close()
    
    return render_template('teams.html',
                         team=current_team,
                         members_with_tasks=members_with_tasks,
                         user_teams=user_teams,
                         current_user_is_manager=current_user_is_manager())
                         
if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(port=5011, debug=True)