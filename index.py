import io
import time
import json
import sqlite3
import secrets
import logging
import smtplib
import random
import string
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps
import requests
from study_plan import generate_study_plan, study_plan_bp
from flask import (
    Flask,
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session,
    flash,
    abort,
    send_file,
    send_from_directory,
)
from werkzeug.security import generate_password_hash, check_password_hash

from email.mime.text import MIMEText
from PIL import Image, ImageDraw, ImageFont
from markdown2 import markdown
import logging
from schedule import ScheduleGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


# Local modules (placeholders, replace with actual implementations if available)
def generate_study_plan(user_input):
    return [], [], 0

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'  # Or 'redis' if you're using Redis
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['SESSION_COOKIE_SECURE'] = True  # For HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'zip', 'txt', 'doc'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure UPLOAD_FOLDER exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.jinja_env.filters['markdown'] = markdown
index_bp = Blueprint('index', __name__)
app.register_blueprint(study_plan_bp, url_prefix='/')

# Email configuration (replace with your SMTP settings)
EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender_email': 'your_email@gmail.com',
    'sender_password': 'your_app_password'
}



logging.basicConfig(level=logging.DEBUG)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_db_connection():
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            skills TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            join_code TEXT UNIQUE NOT NULL,
            invite_password TEXT,
            created_by INTEGER NOT NULL,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS team_members (
            team_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            is_manager INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (team_id, user_id),
            FOREIGN KEY (team_id) REFERENCES teams(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            user_id INTEGER NOT NULL,
            team_id INTEGER,
            deadline TEXT,
            priority TEXT,
            status TEXT DEFAULT 'pending',
            progress INTEGER DEFAULT 0,
            visibility TEXT DEFAULT 'team',
            checklist TEXT,
            approved_by INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (team_id) REFERENCES teams(id),
            FOREIGN KEY (approved_by) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS task_files (
            task_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            uploaded_by INTEGER,
            PRIMARY KEY (task_id),
            FOREIGN KEY (task_id) REFERENCES tasks(id),
            FOREIGN KEY (uploaded_by) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS gamification (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0,
            badges TEXT DEFAULT '[]',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
    CREATE TABLE IF NOT EXISTS badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        badge_name TEXT NOT NULL,
        awarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            type TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS task_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS time_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration INTEGER,
            FOREIGN KEY (task_id) REFERENCES tasks(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS standup_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS task_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            update_type TEXT NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    # Ensure 'created_at' column exists in tasks table
    try:
        conn.execute("SELECT created_at FROM tasks LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, so add it
        conn.execute("ALTER TABLE tasks ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    conn.commit()
    conn.close()

init_db()

def rate_limit(max_requests=100, window_seconds=3600):
    request_counts = defaultdict(list)
    def decorator(f):
        @wraps(f)
        def wrapped_function(*args, **kwargs):
            if 'user_id' in session:
                user_id = session['user_id']
                now = time.time()
                request_counts[user_id] = [t for t in request_counts[user_id] if now - t < window_seconds]
                if len(request_counts[user_id]) >= max_requests:
                    flash('Too many requests, please try again later', 'error')
                    logging.warning(f"Rate limit exceeded for user {user_id}")
                    return redirect(url_for('teams'))
                request_counts[user_id].append(now)
            return f(*args, **kwargs)
        return wrapped_function
    return decorator

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # Don't show the message if we're already on the login page
            if request.endpoint != 'login':
                flash('Please log in to continue', 'info')  # Changed from 'error' to 'info'
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def current_user_is_manager():
    if 'user_id' not in session:
        return False
    conn = get_db_connection()
    user_id = session['user_id']
    team = conn.execute('SELECT created_by FROM teams JOIN team_members ON teams.id = team_members.team_id WHERE team_members.user_id = ?', (user_id,)).fetchone()
    conn.close()
    return team and team['created_by'] == user_id

def send_email(to_email, subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_CONFIG['sender_email']
    msg['To'] = to_email
    try:
        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
            server.send_message(msg)
    except Exception as e:
        logging.error(f"Email sending failed: {e}")

def add_notification(user_id, message, type):
    conn = get_db_connection()
    conn.execute('INSERT INTO notifications (user_id, message, type) VALUES (?, ?, ?)',
                 (user_id, message, type))
    conn.commit()
    user = conn.execute('SELECT email FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        send_email(user['email'], f"New Notification: {type}", message)

def update_gamification(user_id, points=0, badge=None):
    conn = get_db_connection()
    gamification = conn.execute('SELECT * FROM gamification WHERE user_id = ?', (user_id,)).fetchone()
    if not gamification:
        conn.execute('INSERT INTO gamification (user_id, points, badges) VALUES (?, ?, ?)',
                     (user_id, points, json.dumps([badge] if badge else [])))
    else:
        badges = json.loads(gamification['badges'])
        if badge and badge not in badges:
            badges.append(badge)
        conn.execute('UPDATE gamification SET points = points + ?, badges = ? WHERE user_id = ?',
                     (points, json.dumps(badges), user_id))
    conn.commit()
    conn.close()

@app.route('/avatar/<username>', methods=['GET'])
@login_required
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

@app.route('/')
@login_required
def home():
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in, redirect to index
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Please enter both username and password', 'error')
            return redirect(url_for('login'))
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session.modified = True
            
            # Redirect to next URL if it exists
            next_url = request.args.get('next') or url_for('index')
            return redirect(next_url)
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
@rate_limit(max_requests=10, window_seconds=3600)
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('register.html')
        
        if not (username and email and password):
            flash('All fields are required', 'error')
            return render_template('register.html')
        
        password_hash = generate_password_hash(password)
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                         (username, email, password_hash))
            user_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            conn.execute('INSERT INTO gamification (user_id) VALUES (?)', (user_id,))
            conn.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists', 'error')
            return render_template('register.html')
        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'error')
            return render_template('register.html')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/logout', methods=['POST'])
def logout():
    logging.info(f"Session before clearing: {session}")
    session.clear()
    logging.info(f"Session after clearing: {session}")
    response = redirect(url_for('login'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    response.set_cookie('session', '', expires=0)
    response.set_cookie('remember_token', '', expires=0)
    flash('You have been logged out successfully.', 'success')
    return response


@app.route('/index')
@login_required
def index():
    user_id = session['user_id']
    username = session['username']
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    conn = get_db_connection()
    
    today_tasks = conn.execute('''SELECT * FROM tasks 
                                WHERE user_id = ? AND deadline = ? AND status = 'pending' 
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
                                   WHERE user_id = ? AND deadline = ? AND status = 'pending' 
                                   ORDER BY 
                                       CASE priority 
                                           WHEN 'High' THEN 1 
                                           WHEN 'Medium' THEN 2 
                                           WHEN 'Low' THEN 3 
                                       END, 
                                       deadline ASC''', 
                                 (user_id, tomorrow.strftime('%Y-%m-%d'))).fetchall()
    
    future_tasks = conn.execute('''SELECT * FROM tasks 
                                 WHERE user_id = ? AND deadline > ? AND status = 'pending' 
                                 ORDER BY 
                                     CASE priority 
                                         WHEN 'High' THEN 1 
                                         WHEN 'Medium' THEN 2 
                                         WHEN 'Low' THEN 3 
                                     END, 
                                     deadline ASC''', 
                               (user_id, tomorrow.strftime('%Y-%m-%d'))).fetchall()
    
    completed_tasks = conn.execute('''SELECT * FROM tasks 
                                    WHERE user_id = ? AND status = 'completed' 
                                    ORDER BY deadline DESC''', 
                                  (user_id,)).fetchall()
    
    priority_counts = {
        'high': conn.execute('''SELECT COUNT(*) FROM tasks 
                              WHERE user_id = ? AND priority = 'High' AND status != 'completed' AND status != 'deleted' ''', 
                            (user_id,)).fetchone()[0] or 0,
        'medium': conn.execute('''SELECT COUNT(*) FROM tasks 
                                WHERE user_id = ? AND priority = 'Medium' AND status != 'completed' AND status != 'deleted' ''', 
                              (user_id,)).fetchone()[0] or 0,
        'low': conn.execute('''SELECT COUNT(*) FROM tasks 
                             WHERE user_id = ? AND priority = 'Low' AND status != 'completed' AND status != 'deleted' ''', 
                           (user_id,)).fetchone()[0] or 0
    }
    
    max_priority_count = max(priority_counts.values()) or 1
    
    total_tasks_today = len(today_tasks)
    completed_today = len([task for task in completed_tasks if task['deadline'] == today.strftime('%Y-%m-%d')])
    today_progress = (completed_today / total_tasks_today * 100) if total_tasks_today else 0

    notifications = conn.execute('SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 10', (user_id,)).fetchall()
    unread_count = conn.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0', (user_id,)).fetchone()[0]
    
    gamification = conn.execute('SELECT * FROM gamification WHERE user_id = ?', (user_id,)).fetchone()

    conn.close()
   
   

    return render_template('index.html',
                         today_tasks=today_tasks,
                         tomorrow_tasks=tomorrow_tasks,
                         future_tasks=future_tasks,
                         completed_tasks=completed_tasks,
                         priority_counts=priority_counts,
                         max_priority_count=max_priority_count,
                         today=today.strftime('%Y-%m-%d'),
                         username=username,
                         today_progress=today_progress,
                         notifications=notifications,
                         unread_count=unread_count,
                         gamification=gamification)

@app.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for('index'))


@app.route('/tasks')
@login_required
def tasks_dashboard():
    user_id = session['user_id']
    username = session['username']
    today = datetime.now().date()
    last_month = today - timedelta(days=30)
    today_str = today.strftime('%Y-%m-%d')

    conn = get_db_connection()

    # Task counts
    total_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE user_id = ?', (user_id,)).fetchone()[0]
    last_month_total = conn.execute(
        'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND created_at >= ?', 
        (user_id, last_month)).fetchone()[0]

    completed_tasks = conn.execute(
        'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "completed"', 
        (user_id,)).fetchone()[0]
    last_month_completed = conn.execute(
        'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "completed" AND created_at >= ?', 
        (user_id, last_month)).fetchone()[0]

    in_progress_tasks = conn.execute(
        'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "inprogress"', 
        (user_id,)).fetchone()[0]
    last_month_in_progress = conn.execute(
        'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "inprogress" AND created_at >= ?', 
        (user_id, last_month)).fetchone()[0]

    todo_tasks = conn.execute(
        'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "pending"', 
        (user_id,)).fetchone()[0]
    last_month_todos = conn.execute(
        'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = "pending" AND created_at >= ?', 
        (user_id, last_month)).fetchone()[0]

    # Priority chart data (excluding completed/deleted tasks)
    priority_counts = {
        'high': conn.execute(
            'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND priority = "High" AND status NOT IN ("completed", "deleted")', 
            (user_id,)).fetchone()[0],
        'medium': conn.execute(
            'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND priority = "Medium" AND status NOT IN ("completed", "deleted")', 
            (user_id,)).fetchone()[0],
        'low': conn.execute(
            'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND priority = "Low" AND status NOT IN ("completed", "deleted")', 
            (user_id,)).fetchone()[0]
    }

    max_priority_count = max(priority_counts.values()) or 1

    # Today's task stats
    today_tasks = conn.execute(
        'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND deadline = ? AND status IN ("pending", "inprogress", "completed")', 
        (user_id, today_str)).fetchone()[0]
    today_completed = conn.execute(
        'SELECT COUNT(*) FROM tasks WHERE user_id = ? AND deadline = ? AND status = "completed"', 
        (user_id, today_str)).fetchone()[0]
    today_progress = (today_completed / today_tasks * 100) if today_tasks > 0 else 0

    # Streak
    streak_data = load_streak()
    current_streak = streak_data.get('streak', 0)

    # Notifications
    notifications = conn.execute(
        'SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 10', 
        (user_id,)).fetchall()
    unread_count = conn.execute(
        'SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0', 
        (user_id,)).fetchone()[0]

    conn.close()

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
                           max_priority_count=max_priority_count,
                           today_progress=today_progress,
                           streak=current_streak,
                           username=username,
                           notifications=notifications,
                           unread_count=unread_count)


@app.route('/inprogress')
@login_required
def inprogress_tasks():
    user_id = session['user_id']
    conn = get_db_connection()
    tasks = conn.execute('''
        SELECT t.*, tf.filename, tf.version 
        FROM tasks t 
        LEFT JOIN task_files tf ON t.id = tf.task_id 
        WHERE t.user_id = ? AND t.status = 'inprogress'
        ORDER BY t.deadline ASC
    ''', (user_id,)).fetchall()
    conn.close()
    task_dicts = [dict(task) for task in tasks]
    for task in task_dicts:
        task['checklist'] = json.loads(task['checklist'] or '{}')
    return render_template('inprogress.html', 
                         tasks=task_dicts,
                         show_empty=not task_dicts)

@app.route('/todo')
@login_required
def todo_tasks():
    conn = get_db_connection()
    tasks = conn.execute('''
        SELECT t.*, tf.filename, tf.version 
        FROM tasks t 
        LEFT JOIN task_files tf ON t.id = tf.task_id 
        WHERE t.user_id = ? AND t.status = 'pending'
        ORDER BY 
            CASE priority 
                WHEN 'High' THEN 1 
                WHEN 'Medium' THEN 2 
                WHEN 'Low' THEN 3 
            END,
            deadline ASC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    task_dicts = [dict(task) for task in tasks]
    for task in task_dicts:
        task['checklist'] = json.loads(task['checklist'] or '{}')
    return render_template('todo.html', 
                         tasks=task_dicts,
                         current_time=datetime.now().strftime('%Y-%m-%d'))

@app.route('/completedo')
@login_required
def completed_tasks():
    user_id = session['user_id']
    conn = get_db_connection()
    tasks = conn.execute('''
        SELECT t.*, tf.filename, tf.version 
        FROM tasks t 
        LEFT JOIN task_files tf ON t.id = tf.task_id 
        WHERE t.user_id = ? AND t.status = 'completed'
        ORDER BY t.deadline DESC
    ''', (user_id,)).fetchall()
    conn.close()
    task_dicts = [dict(task) for task in tasks]
    for task in task_dicts:
        task['checklist'] = json.loads(task['checklist'] or '{}')
    return render_template('completed.html', tasks=task_dicts)


@app.route("/calender")
@login_required
def calender():
    user_id = session["user_id"]
    conn = get_db_connection()

    events = conn.execute("""
        SELECT title, deadline as date, priority FROM tasks
        WHERE user_id = ? AND deadline >= date('now') AND status != 'completed'
        ORDER BY deadline ASC
    """, (user_id,)).fetchall()

    conn.close()
    return render_template("calender.html", events=events)


@app.route('/deleted')
@login_required
def deleted_tasks():
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

@app.route('/permanent-delete/<int:task_id>', methods=['POST'])
@login_required
def permanent_delete_task(task_id):
    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Task deleted permanently"})

@app.route('/restore/<int:task_id>', methods=['POST'])
@login_required
def restore_task(task_id):
    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute("UPDATE tasks SET status = 'pending' WHERE id = ? AND user_id = ?", 
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

@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    conn = get_db_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    
    if not task:
        conn.close()
        flash('Task not found', 'error')
        return redirect(url_for('teams'))
    
    if request.method == 'POST':
        title = request.form['title']
        description = request.form.get('description', '')
        deadline = request.form['deadline']
        priority = request.form['priority']
        visibility = request.form['visibility']
        
        # Handle file uploads
        uploaded_files = request.files.getlist('files')
        file_names = []
        
        # Get existing files from task_files
        existing_files = conn.execute('SELECT filename FROM task_files WHERE task_id = ?', (task_id,)).fetchall()
        existing_filenames = [f['filename'] for f in existing_files]
        
        # Process files to delete
        files_to_delete = request.form.getlist('delete_files')
        remaining_filenames = [f for f in existing_filenames if f not in files_to_delete]
        
        # Delete files marked for removal
        for file in files_to_delete:
            conn.execute('DELETE FROM task_files WHERE task_id = ? AND filename = ?', (task_id, file))
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file)
            if os.path.exists(file_path):
                os.remove(file_path)
        
        # Save new files
        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                remaining_filenames.append(filename)
                # Insert new file into task_files
                conn.execute('INSERT INTO task_files (task_id, filename, uploaded_by) VALUES (?, ?, ?)',
             (task_id, filename, session['user_id']))

        
        # Update task in database
        conn.execute('''
            UPDATE tasks 
            SET title = ?, description = ?, deadline = ?, priority = ?, visibility = ?
            WHERE id = ?
        ''', (title, description, deadline, priority, visibility, task_id))
        conn.commit()
        
        # Check if we should update streak
        today = datetime.now().date()
        if deadline == today.strftime('%Y-%m-%d'):
            # Call the streak update endpoint
            response = requests.post(url_for('update_streak', _external=True), 
                                   data={}, 
                                   cookies=request.cookies)
            
            if response.json().get('streak_updated'):
                flash(f'Streak updated! Current streak: {response.json().get("streak")} days', 'success')
        
        flash('Task updated successfully', 'success')
        conn.close()
        return redirect(url_for('teams'))
    
    # For GET request, render the edit form
    files = conn.execute('SELECT filename FROM task_files WHERE task_id = ?', (task_id,)).fetchall()
    attachments = [f['filename'] for f in files]
    
    if task['deadline']:
        try:
            task = dict(task)  # convert Row to dict so we can update
            task['deadline'] = datetime.strptime(task['deadline'], '%Y-%m-%d')
        except ValueError:
            task['deadline'] = None

    conn.close()
    return render_template('edit_task.html', task=task, attachments=attachments, today=datetime.today().date().isoformat())

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

@app.route('/start_task/<int:task_id>', methods=['POST'])
@login_required
def start_task(task_id):
    conn = get_db_connection()
    conn.execute("UPDATE tasks SET status = 'inprogress' WHERE id = ? AND user_id = ?",
                 (task_id, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/team')
@login_required
def teams():
    user_id = session['user_id']
    conn = get_db_connection()

    # Get the team the user is in
    team = conn.execute(
        'SELECT teams.* FROM team_members JOIN teams ON team_members.team_id = teams.id WHERE team_members.user_id = ?',
        (user_id,)
    ).fetchone()

    # Get manager name
    manager_name = conn.execute(
        'SELECT username FROM users WHERE id = (SELECT created_by FROM teams WHERE id = ?)',
        (team['id'],) if team else (None,)
    ).fetchone()
    manager_name = manager_name['username'] if manager_name else 'Unknown'

    # Get current user's skills
    skills_row = conn.execute('SELECT skills FROM users WHERE id = ?', (user_id,)).fetchone()
    raw_skills = skills_row['skills'] if skills_row and skills_row['skills'] else ''
    current_user_skills = [s.strip() for s in raw_skills.split(',') if s.strip()]
    print(">>> Raw skills from DB:", repr(raw_skills))

    members_with_tasks = []

    if team:
        team_id = team['id']
        members = conn.execute('''
            SELECT u.id, u.username, u.skills, tm.is_manager
            FROM team_members tm
            JOIN users u ON tm.user_id = u.id
            WHERE tm.team_id = ?
            ORDER BY tm.is_manager DESC, u.username ASC
        ''', (team_id,)).fetchall()

        for member in members:
            tasks = conn.execute('''
                SELECT t.*, tf.filename, tf.version 
                FROM tasks t 
                LEFT JOIN task_files tf ON t.id = tf.task_id 
                WHERE t.user_id = ? AND t.team_id = ?
                ORDER BY 
                    CASE status
                        WHEN 'pending' THEN 1
                        WHEN 'inprogress' THEN 2
                        WHEN 'completed' THEN 3
                    END,
                    deadline ASC
            ''', (member['id'], team_id)).fetchall()

            task_dicts = [dict(task) for task in tasks]
            for task in task_dicts:
                task['checklist'] = json.loads(task['checklist'] or '{}')
                comments = conn.execute(
                    'SELECT tc.*, u.username FROM task_comments tc JOIN users u ON tc.user_id = u.id WHERE tc.task_id = ?',
                    (task['id'],)
                ).fetchall()
                task['comments'] = [dict(comment) for comment in comments]

            # Handle member skills as comma-separated string
            try:
                member_skills = json.loads(member['skills']) if member['skills'] else []
                if not isinstance(member_skills, list):
                    member_skills = [str(member_skills)]
            except json.JSONDecodeError:
                    # Fallback if it's plain string like "java"
                    member_skills = [s.strip() for s in member['skills'].split(',')] if member['skills'] else []



            members_with_tasks.append({
                'id': member['id'],
                'username': member['username'],
                'is_manager': member['is_manager'],
                'skills': member_skills,
                'tasks': task_dicts
            })

    notifications = conn.execute(
        'SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 10',
        (user_id,)
    ).fetchall()
    unread_count = conn.execute(
        'SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0',
        (user_id,)
    ).fetchone()[0]

    conn.close()
    return render_template(
        'teams.html',
        team=team,
        members_with_tasks=members_with_tasks,
        notifications=notifications,
        unread_count=unread_count,
        current_user_is_manager=current_user_is_manager(),
        manager_name=manager_name,
        current_user_skills=current_user_skills,member=member
    )


@app.route('/team_members')
@login_required
def team_members():
    conn = get_db_connection()
    members = conn.execute('''
        SELECT u.id, u.username, u.skills, tm.joined_at,
               (tm.user_id = t.created_by) as is_manager
        FROM team_members tm
        JOIN users u ON tm.user_id = u.id
        JOIN teams t ON tm.team_id = t.id
        WHERE tm.team_id = (
            SELECT team_id FROM team_members WHERE user_id = ?
        )
        ORDER BY is_manager DESC, tm.joined_at ASC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return jsonify([{
        'id': member['id'],
        'username': member['username'],
        'skills': json.loads(member['skills'] if 'skills' in member else '{}'),
        'is_manager': member['is_manager'],
        'joined_at': member['joined_at']
    } for member in members])

@app.route('/chart-data')
@login_required
def chart_data():
    user_id = session['user_id']
    conn = get_db_connection()
    completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'completed'", (user_id,)).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ?", (user_id,)).fetchone()[0]
    remaining = total - completed
    conn.close()
    return jsonify({
        "labels": ["Completed", "Remaining"],
        "data": [completed, remaining]
    })

@app.route('/create_team', methods=['POST'])
@login_required
def create_team():
    team_name = request.form['team_name']
    invite_password = request.form.get('invite_password')
    join_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    user_id = session['user_id']
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO teams (name, join_code, invite_password, created_by) VALUES (?, ?, ?, ?)',
                     (team_name, join_code, invite_password or None, user_id))
        team_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.execute('INSERT INTO team_members (team_id, user_id, is_manager) VALUES (?, ?, 1)',
                     (team_id, user_id))
        conn.commit()
        flash('Team created successfully', 'success')
        return redirect(url_for('teams'))
    except sqlite3.IntegrityError:
        flash('Team name already exists', 'error')
        return redirect(url_for('teams'))
    except Exception as e:
        flash(f'Failed to create team: {str(e)}', 'error')
        return redirect(url_for('teams'))
    finally:
        conn.close()

@app.route('/join_team', methods=['POST'])
@login_required
def join_team():
    join_code = request.form['join_code']
    invite_password = request.form.get('invite_password')
    user_id = session['user_id']
    conn = get_db_connection()
    try:
        team = conn.execute('SELECT * FROM teams WHERE join_code = ?', (join_code,)).fetchone()
        if not team:
            flash('Invalid join code', 'error')
            return redirect(url_for('teams'))
        if team['invite_password'] and team['invite_password'] != invite_password:
            flash('Incorrect invite password', 'error')
            return redirect(url_for('teams'))
        existing_member = conn.execute('SELECT * FROM team_members WHERE team_id = ? AND user_id = ?', (team['id'], user_id)).fetchone()
        if existing_member:
            flash('You are already a member of this team', 'error')
            return redirect(url_for('teams'))
        conn.execute('INSERT INTO team_members (team_id, user_id, is_manager) VALUES (?, ?, 0)',
                     (team['id'], user_id))
        conn.commit()
        flash('Successfully joined the team', 'success')
        return redirect(url_for('teams'))
    except Exception as e:
        flash(f'Failed to join team: {str(e)}', 'error')
        return redirect(url_for('teams'))
    finally:
        conn.close()

@app.route('/assign_team_task', methods=['POST'])
@login_required
def assign_team_task():
    if not current_user_is_manager():
        flash('Only the team creator can assign tasks', 'error')
        return redirect(url_for('teams'))
    title = request.form['title']
    assign_to = request.form['assign_to']
    description = request.form.get('description')
    deadline = request.form['deadline']
    priority = request.form['priority']
    visibility = request.form['visibility']
    checklist = json.dumps({item: False for item in request.form.getlist('checklist[]')}) if request.form.getlist('checklist[]') else '{}'
    file = request.files.get('file')
    filename = None
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
    user_id = session['user_id']
    conn = get_db_connection()
    team_id = conn.execute('SELECT id FROM teams WHERE created_by = ?', (user_id,)).fetchone()['id']
    conn.execute('''INSERT INTO tasks (title, description, user_id, team_id, deadline, priority, status, visibility, checklist) 
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)''',
                 (title, description, assign_to, team_id, deadline, priority, visibility, checklist))
    task_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    if filename:
        conn.execute('INSERT INTO task_files (task_id, filename, uploaded_by) VALUES (?, ?, ?)',
                     (task_id, filename, user_id))
    conn.commit()
    conn.close()
    add_notification(assign_to, f"You have been assigned a new task: {title}", "task_assignment")
    flash('Task assigned successfully', 'success')
    return redirect(url_for('teams'))

@app.route('/leave_team', methods=['POST'])
@login_required
def leave_team():
    user_id = session['user_id']
    conn = get_db_connection()
    team_id = conn.execute('SELECT team_id FROM team_members WHERE user_id = ?', (user_id,)).fetchone()
    if not team_id:
        flash('You are not part of any team', 'error')
        return redirect(url_for('teams'))
    team_id = team_id['team_id']
    is_manager = conn.execute('SELECT is_manager FROM team_members WHERE team_id = ? AND user_id = ?', 
                             (team_id, user_id)).fetchone()['is_manager']
    if is_manager:
        flash('Team creator cannot leave the team', 'error')
        return redirect(url_for('teams'))
    conn.execute('DELETE FROM team_members WHERE team_id = ? AND user_id = ?', (team_id, user_id))
    conn.commit()
    conn.close()
    flash('You have left the team', 'success')
    return redirect(url_for('teams'))

@app.route('/delete_team', methods=['POST'])
@login_required
def delete_team():
    if not current_user_is_manager():
        flash('Only the team creator can delete the team', 'error')
        return redirect(url_for('teams'))
    user_id = session['user_id']
    conn = get_db_connection()
    team_id = conn.execute('SELECT id FROM teams WHERE created_by = ?', (user_id,)).fetchone()
    if not team_id:
        flash('No team found to delete', 'error')
        return redirect(url_for('teams'))
    team_id = team_id['id']
    conn.execute('DELETE FROM team_members WHERE team_id = ?', (team_id,))
    conn.execute('DELETE FROM tasks WHERE team_id = ?', (team_id,))
    conn.execute('DELETE FROM teams WHERE id = ?', (team_id,))
    conn.commit()
    conn.close()
    flash('Team deleted successfully', 'success')
    return redirect(url_for('teams'))

@app.route('/update_skills', methods=['POST'])
@login_required
def update_skills():
    skill = request.form['skills'].strip()
    user_id = session['user_id']
    conn = get_db_connection()
    current_skills = json.loads(
        conn.execute('SELECT skills FROM users WHERE id = ?', (user_id,)).fetchone()['skills'] or '[]'
    )
    if skill not in current_skills:
        current_skills.append(skill)
        conn.execute('UPDATE users SET skills = ? WHERE id = ?', (json.dumps(current_skills), user_id))
        conn.commit()
    conn.close()
    flash('Skill updated successfully', 'success')
    return redirect(url_for('teams'))

@app.route('/mark_notification_read/<int:notif_id>', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute('UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?', (notif_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/download_task_file/<int:task_id>')
@login_required
def download_task_file(task_id):
    user_id = session['user_id']
    conn = get_db_connection()
    file_record = conn.execute('SELECT filename FROM task_files WHERE task_id = ?', (task_id,)).fetchone()
    conn.close()
    if not file_record or not file_record['filename']:
        flash('File not found', 'error')
        return redirect(url_for('teams'))
    filename = file_record['filename']
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(file_path):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    flash('File not found', 'error')
    return redirect(url_for('teams'))

@app.route('/upload_task_file/<int:task_id>', methods=['POST'])
@login_required
def upload_task_file(task_id):
    user_id = session['user_id']
    file = request.files.get('file')
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        conn = get_db_connection()
        existing_version = conn.execute('SELECT version FROM task_files WHERE task_id = ?', (task_id,)).fetchone()
        version = (existing_version['version'] + 1) if existing_version else 1
        conn.execute('INSERT OR REPLACE INTO task_files (task_id, filename, version, uploaded_by) VALUES (?, ?, ?, ?)',
                     (task_id, filename, version, user_id))
        conn.commit()
        conn.close()
        flash('File uploaded successfully', 'success')
    else:
        flash('Invalid file type', 'error')
    return redirect(url_for('teams'))

@app.route('/add_task_comment/<int:task_id>', methods=['POST'])
@login_required
def add_task_comment(task_id):
    content = request.form['content']
    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute('INSERT INTO task_comments (task_id, user_id, content) VALUES (?, ?, ?)',
                 (task_id, user_id, content))
    conn.commit()
    conn.close()
    flash('Comment added successfully', 'success')
    return redirect(url_for('teams'))

@app.route('/message_manager/<int:task_id>', methods=['POST'])
@login_required
def message_manager(task_id):
    content = request.form['content']
    user_id = session['user_id']
    conn = get_db_connection()
    team_id = conn.execute(('SELECT team_id FROM tasks WHERE id = ?', (task_id,)).fetchone()['team_id'])
    manager_id = conn.execute(('SELECT created_by FROM teams WHERE id = ?', (team_id,)).fetchone()['created_by'])
    message = f"Message from {session['username']}: {content}"
    add_notification(manager_id, message, "message")
    conn.close()
    flash('Message sent to manager', 'success')
    return redirect(url_for('teams'))

@app.route('/approve_task/<int:task_id>', methods=['POST'])
@login_required
def approve_task(task_id):
    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute("UPDATE tasks SET status = 'inprogress', approved_by = ? WHERE id = ? AND user_id = ?",
                 (user_id, task_id, user_id))
    conn.commit()
    conn.close()
    flash('Task approved and started', 'success')
    return redirect(url_for('teams'))

@app.route('/start_timer/<int:task_id>', methods=['POST'])
@login_required
def start_timer(task_id):
    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute("INSERT INTO time_tracking (task_id, user_id, start_time) VALUES (?, ?, ?)",
                 (task_id, user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/stop_timer/<int:task_id>', methods=['POST'])
@login_required
def stop_timer(task_id):
    user_id = session['user_id']
    conn = get_db_connection()
    tracking = conn.execute("SELECT id, start_time FROM time_tracking WHERE task_id = ? AND user_id = ? AND end_time IS NULL",
                           (task_id, user_id)).fetchone()
    if tracking:
        start_time = datetime.strptime(tracking['start_time'], '%Y-%m-%d %H:%M:%S')
        end_time = datetime.now()
        duration = int((end_time - start_time).total_seconds() / 60)  # Duration in minutes
        conn.execute("UPDATE time_tracking SET end_time = ?, duration = ? WHERE id = ?",
                     (end_time.strftime('%Y-%m-%d %H:%M:%S'), duration, tracking['id']))
        conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/standup', methods=['POST'])
@login_required
def standup():
    content = request.form['content']
    user_id = session['user_id']
    date = datetime.now().date().strftime('%Y-%m-%d')
    conn = get_db_connection()
    conn.execute("INSERT INTO standup_logs (user_id, content, date) VALUES (?, ?, ?)",
                 (user_id, content, date))
    conn.commit()
    conn.close()
    flash('Standup log submitted', 'success')
    return redirect(url_for('teams'))

@app.route("/analytics")
@login_required
def analytics():
    user_id = session["user_id"]
    conn = get_db_connection()

    total_time = conn.execute((("SELECT SUM(duration) FROM tasks WHERE user_id = ?", (user_id,)).fetchone()[0] or 0))
    total_completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'completed'", (user_id,)).fetchone()[0]
    total_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ?", (user_id,)).fetchone()[0] or 1

    completion_rate = (total_completed / total_tasks) * 100

    user_tasks = conn.execute("""
        SELECT status, COUNT(*) as count FROM tasks
        WHERE user_id = ?
        GROUP BY status
    """, (user_id,)).fetchall()

    team_stats = conn.execute("""
        SELECT u.username, COUNT(t.id) as task_count,
               SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) * 100.0 / COUNT(t.id) as avg_progress
        FROM users u
        JOIN tasks t ON u.id = t.user_id
        GROUP BY u.id
    """).fetchall()

    conn.close()
    return render_template("analytics.html", total_time=total_time, completion_rate=completion_rate,
                           user_tasks=user_tasks, team_stats=team_stats)


@app.route("/leaderboard")
@login_required
def leaderboard():
    conn = get_db_connection()
    leaderboard = conn.execute("""
        SELECT u.username, u.streak, COUNT(t.id) AS completed_tasks
        FROM users u
        LEFT JOIN tasks t ON u.id = t.user_id AND t.status = 'completed'
        GROUP BY u.id
        ORDER BY completed_tasks DESC, u.streak DESC
    """).fetchall()
    conn.close()
    return render_template("leaderboard.html", leaderboard=leaderboard)
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session["user_id"]
    conn = get_db_connection()
    print(">>> /profile route called")

    if request.method == "POST":
        skills = request.form.get("skills", "")
        conn.execute("UPDATE users SET skills = ? WHERE id = ?", (skills, user_id))
        conn.commit()
        flash("Skills updated successfully", "success")

    row = conn.execute("SELECT username, streak, skills FROM users WHERE id = ?", (user_id,)).fetchone()
    badges = conn.execute("SELECT badge_name FROM badges WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()

    # Ensure `skills` is always a list
    skills_list = [s.strip() for s in (row["skills"] or "").split(",") if s.strip()]

    user = {
        "username": row["username"],
        "streak": row["streak"],
        "skills": skills_list
    }

    return render_template("profile.html", user=user, badges=[b["badge_name"] for b in badges])

@app.route('/schedule')
@login_required
def schedule():
    try:
        user_id = session['user_id']  # Now this will be defined
        generator = ScheduleGenerator(user_id)
        result = generator.generate_schedule()

        if result["error"]:
            return render_template("schedule.html", schedule={})
        else:
            schedule_data = json.loads(result["data"])
            return render_template("schedule.html", schedule=schedule_data)

    except Exception as e:
        logging.error("Route Error in /schedule: " + str(e))
        return render_template("schedule.html", schedule={})




@app.route('/search', methods=['GET'])
@login_required
def search_tasks():
    user_id = session['user_id']
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({"tasks": []})
    tasks = conn.execute('''
    SELECT * FROM tasks
    WHERE user_id = ?
      AND (title LIKE ? OR description LIKE ?)
      AND status != 'deleted'
    ORDER BY 
      CASE priority
        WHEN 'High' THEN 1
        WHEN 'Medium' THEN 2
        WHEN 'Low' THEN 3
        ELSE 4
      END,
      deadline''', (user_id, query, query)).fetchall()
    conn.close()
    tasks = [{
        'id': task['id'],
        'title': task['title'],
        'description': task['description'],
        'deadline': task['deadline'],
        'priority': task['priority'],
        'status': task['status'],
        'progress': task['progress'],
        'checklist': json.loads(task['checklist'] or '{}')
    } for task in results]
    return jsonify({"tasks": tasks})

@app.route('/add', methods=['POST'])
@login_required
def add_task():
    user_id = session['user_id']
    title = request.form['title']
    description = request.form.get('description', '')
    deadline = request.form['deadline'] or datetime.now().strftime('%Y-%m-%d')
    priority = request.form.get('priority', 'Medium')
    visibility = request.form.get('visibility', 'team')
    checklist_items = request.form.getlist('checklist[]')
    checklist = {item: False for item in checklist_items} if checklist_items else {}
    conn = get_db_connection()
    conn.execute('''INSERT INTO tasks (user_id, title, description, deadline, priority, status, visibility, checklist) 
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)'''
                 ,(user_id, title, description, deadline, priority, visibility, json.dumps(checklist)))
    task_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    flash('Task added successfully', 'success')
    update_gamification(user_id, points=5)
    return redirect(url_for('index'))

@app.route('/status/<int:task_id>/<string:new_status>', methods=['POST'])
@login_required
def update_status(task_id, new_status):
    user_id = session['user_id']
    conn = get_db_connection()
    task = conn.execute("SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)).fetchone()
    if not task:
        conn.close()
        return jsonify({"success": False, "message": "Task not found"}), 404
    if new_status == 'inprogress' and task['needs_approval'] and not task['approved_by']:
        conn.close()
        return jsonify({"success": False, "message": "Approval required"}), 403
    conn.execute("UPDATE tasks SET status = ? WHERE id = ? AND user_id = ?", 
                (new_status, task_id, user_id))
    conn.commit()
    conn.close()
    if new_status == 'completed':
        update_gamification(user_id, points=50, badge='Task Slayer')
    return jsonify({"success": True, "message": f"Task status updated to {new_status}"})

@app.route('/update_task_priority/<int:task_id>', methods=['POST'])
@login_required
def update_task_priority(task_id):
    new_priority = request.json.get('priority')
    if new_priority not in ['High', 'Medium', 'Low']:
        return jsonify({'success': False, 'error': 'Invalid priority'}), 400
    conn = get_db_connection()
    conn.execute('UPDATE tasks SET priority = ? WHERE id = ? AND user_id = ?',
                 (new_priority, task_id, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/update_progress/<int:task_id>', methods=['POST'])
@login_required
def update_progress(task_id):
    progress = request.json.get('progress')
    user_id = session['user_id']
    conn = get_db_connection()
    
    # Verify the task belongs to the user
    task = conn.execute('SELECT * FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id)).fetchone()
    if not task:
        conn.close()
        return jsonify({"success": False, "message": "Task not found"}), 404
    
    # Update progress
    conn.execute('UPDATE tasks SET progress = ? WHERE id = ?', (progress, task_id))
    
    # If progress is 100%, mark as completed
    if int(progress) == 100:
        conn.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
        update_gamification(user_id, points=50, badge='Task Slayer')
    
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Progress updated"})

@app.route('/quick_add_task', methods=['POST'])
@login_required
def quick_add_task():
    title = request.form.get('title')
    if not title:
        flash('Task title cannot be empty', 'error')
        return redirect(url_for('todo_tasks'))
    conn = get_db_connection()
    conn.execute("INSERT INTO tasks (user_id, title, status, priority) VALUES (?, ?, 'pending', 'Medium')",
                 (session['user_id'], title))
    conn.commit()
    conn.close()
    flash('Task added successfully', 'success')
    update_gamification(session['user_id'], points=5)
    return redirect(url_for('todo_tasks'))

@app.route('/task_updates', methods=['POST'])
@login_required
def add_task_update():
    user_id = session['user_id']
    task_id = request.json.get('task_id')
    notes = request.json.get('notes', '')
    conn = get_db_connection()
    conn.execute("INSERT INTO task_updates (task_id, user_id, update_type, notes) VALUES (?, ?, 'progress', ?)",
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
        new_priority = data.get('priority')
        data.get('priority', 'Medium')
        new_visibility = data.get('visibility')
        data.get('visibility', 'team')
        
        return jsonify({
            "success": True,
            "message": "Task updated successfully",
            "task": {
                "id": task_id,
                "title": new_title,
                "description": new_description,
                "deadline": deadline_new,
                "priority": new_priority,
                "visibility": visibility_new
            }
        })

    
    else:
        new_title = request.form['title']
        new_description = request.form.get('description', '')
        new_deadline = request.form['deadline']
        new_priority = request.form.get('priority', 'Medium')
        new_visibility = request.form.get('visibility', 'team')
    conn = get_db_connection()
    conn.execute('''UPDATE tasks SET title = ?, description = ?, deadline = ?, priority = ?, visibility = ? 
                    WHERE id = ? AND user_id = ?''', 
                 (new_title, new_description, new_deadline, new_priority, new_visibility, 
                  task_id, user_id))
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
            "priority": new_priority,
            "visibility": new_visibility
        }
    })

STREAK_FILE = 'streak.json'
if not os.path.exists(STREAK_FILE):
    with open(STREAK_FILE, 'w') as f:
        json.dump({'streak': 0, 'last_updated': None}, f)


def load_streak():
    try:
        if os.path.exists(STREAK_FILE):
            with open(STREAK_FILE, 'r') as f:
                return json.load(f)
        return {'streak': 0, 'last_updated': None}
    except:
        return {'streak': 0, 'last_updated': None}

def save_streak(data):
    with open(STREAK_FILE, 'w') as f:
        json.dump(data, f)


# âœ… Define all routes here BEFORE registering the blueprint
# @index_bp.route('/study_plan/', methods=['GET', 'POST'])
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



@app.route('/update_checklist/<int:task_id>', methods=['POST'])
@login_required
def update_checklist(task_id):
    item = request.json.get('item')
    checked = request.json.get('checked')
    user_id = session['user_id']
    
    conn = get_db_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id)).fetchone()
    if not task:
        conn.close()
        return jsonify({"success": False, "message": "Task not found"}), 404
    
    # Update checklist
    checklist = json.loads(task['checklist'] or '{}')
    checklist[item] = checked
    conn.execute('UPDATE tasks SET checklist = ? WHERE id = ?', (json.dumps(checklist), task_id))
    
    # Calculate new progress based on completed checklist items
    total_items = len(checklist)
    if total_items > 0:
        completed_items = sum(1 for item, checked in checklist.items() if checked)
        new_progress = int((completed_items / total_items) * 100)
        conn.execute('UPDATE tasks SET progress = ? WHERE id = ?', (new_progress, task_id))
        
        # If all checklist items are checked, mark as completed
        if new_progress == 100 and task['status'] != 'completed':
            conn.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
            update_gamification(user_id, points=50, badge='Task Slayer')
    
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Checklist updated"})

@app.route('/update_streak', methods=['POST'])
@login_required
def update_streak():
    user_id = session['user_id']
    conn = get_db_connection()
    today = datetime.now().date()
    
    # Get all tasks for today (pending or completed)
    today_tasks = conn.execute('''
        SELECT COUNT(*) FROM tasks 
        WHERE user_id = ? AND deadline = ? AND status IN ("pending", "completed")
    ''', (user_id, today.strftime('%Y-%m-%d'))).fetchone()[0]
    
    # Get completed tasks for today
    completed_tasks = conn.execute('''
        SELECT COUNT(*) FROM tasks 
        WHERE user_id = ? AND deadline = ? AND status = "completed"
    ''', (user_id, today.strftime('%Y-%m-%d'))).fetchone()[0]
    
    conn.close()
    
    today_progress = (completed_tasks / today_tasks * 100) if today_tasks > 0 else 0
    streak_data = load_streak()
    
    # Initialize streak_data if empty
    if not streak_data:
        streak_data = {'streak': 0, 'last_updated': None}
    
    last_updated = datetime.strptime(streak_data['last_updated'], '%Y-%m-%d').date() if streak_data['last_updated'] else None
    
    streak_updated = False
    
    if today_progress == 100:
        if last_updated is None:
            # First time completing all tasks
            streak_data['streak'] = 1
            streak_updated = True
        elif last_updated == today - timedelta(days=1):
            # Consecutive day
            streak_data['streak'] += 1
            streak_updated = True
        elif last_updated == today:
            # Already updated today
            pass
        else:
            # Broken streak, start over
            streak_data['streak'] = 1
            streak_updated = True
            
        streak_data['last_updated'] = today.strftime('%Y-%m-%d')
        save_streak(streak_data)
        
        if streak_updated:
            update_gamification(user_id, points=20, badge='Streak Master')
    
    elif last_updated and last_updated < today - timedelta(days=1):
        # Streak broken (missed a day)
        streak_data['streak'] = 0
        streak_data['last_updated'] = None
        save_streak(streak_data)
    
    return jsonify({
        'success': True,
        'streak': streak_data['streak'],
        'today_progress': today_progress,
        'streak_updated': streak_updated
    })




@app.route('/remove_skill/<skill>', methods=['POST'])
@login_required
def remove_skill(skill):
    user_id = session['user_id']
    conn = get_db_connection()
    
    try:
        # Get current skills
        user = conn.execute("SELECT skills FROM users WHERE id = ?", (user_id,)).fetchone()
        if user and user['skills']:
            skills = json.loads(user['skills'])
            # Remove the skill (case insensitive)
            skills = [s for s in skills if s.lower() != skill.lower()]
            
            # Update the database
            conn.execute("UPDATE users SET skills = ? WHERE id = ?", 
                        (json.dumps(skills), user_id))
            conn.commit()
            flash(f"Skill '{skill}' removed successfully", "success")
        else:
            flash("No skills found to remove", "warning")
    except Exception as e:
        conn.rollback()
        flash(f"Error removing skill: {str(e)}", "error")
    finally:
        conn.close()
    
    return redirect(url_for('teams'))

    conn.close()
    return redirect(url_for('team'))
@app.route('/complete_task/<int:task_id>', methods=['POST'])
@login_required
def complete_task(task_id):
    user_id = session['user_id']
    conn = None
    try:
        conn = get_db_connection()
        
        # Verify the task exists and belongs to the user or their team
        task = conn.execute('''
            SELECT t.* FROM tasks t
            LEFT JOIN team_members tm ON t.team_id = tm.team_id
            WHERE t.id = ? AND (t.user_id = ? OR tm.user_id = ?)
        ''', (task_id, user_id, user_id)).fetchone()
        
        if not task:
            return jsonify({"success": False, "message": "Task not found or unauthorized"}), 404
        
        # Update the task
        conn.execute('''
            UPDATE tasks 
            SET status = 'completed', progress = 100 
            WHERE id = ?
        ''', (task_id,))
        
        # Add a task update record
        conn.execute('''
            INSERT INTO task_updates (task_id, user_id, update_type, notes)
            VALUES (?, ?, 'completed', 'Marked as complete')
        ''', (task_id, user_id))
        
        conn.commit()
        update_gamification(user_id, points=50, badge='Task Slayer')
        return jsonify({'success': True, 'message': 'Task marked as complete'})
        
    except sqlite3.OperationalError as e:
        if conn:
            conn.rollback()
        logging.error(f"Database error: {str(e)}")
        return jsonify({'success': False, 'message': 'Database error. Please try again.'}), 500
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Error completing task: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/complete/<int:task_id>', methods=['POST'])
@login_required
def complete_task_alias(task_id):
    return complete_task(task_id)


import sqlite3

def generate_task_summary(task):
    return f"ðŸ“Œ {task['title']} (Due: {task['deadline']}) - Priority: {task['priority']}, Status: {task['status']}"

def show_tasks_as_text(user_id):
    conn = sqlite3.connect("tasks.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    tasks = cursor.execute("""
        SELECT id, title, deadline, priority, description, status
FROM tasks
WHERE user_id = ? AND status != 'deleted'
ORDER BY deadline ASC
""", (user_id,)).fetchall()

    conn.close()

    if not tasks:
        return "No tasks found."

    summary = "Your Tasks:\n\n"
    for task in tasks:
        summary += generate_task_summary(task) + "\n"

    return summary

@app.route('/tasks_text')
@login_required
def tasks_text():
    user_id = session['user_id']
    summary = show_tasks_as_text(user_id)
    return render_template('tasks_text.html', summary=summary)
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5005)


