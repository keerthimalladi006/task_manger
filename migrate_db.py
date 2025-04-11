import sqlite3

conn = sqlite3.connect('tasks.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Add role column to team_members
try:
    cursor.execute('ALTER TABLE team_members ADD COLUMN role TEXT DEFAULT "Member"')
    print("Added role column to team_members")
except sqlite3.OperationalError as e:
    print(f"Role column already exists: {e}")

# Add missing columns to tasks
try:
    cursor.execute('ALTER TABLE tasks ADD COLUMN description TEXT')
    print("Added description column to tasks")
except sqlite3.OperationalError:
    pass

try:
    cursor.execute('ALTER TABLE tasks ADD COLUMN priority TEXT CHECK(priority IN ("High", "Medium", "Low")) DEFAULT "Medium"')
    print("Added priority column to tasks")
except sqlite3.OperationalError:
    pass

try:
    cursor.execute('ALTER TABLE tasks ADD COLUMN team_id INTEGER')
    cursor.execute('ALTER TABLE tasks ADD FOREIGN KEY (team_id) REFERENCES teams(id)')
    print("Added team_id column to tasks")
except sqlite3.OperationalError:
    pass

try:
    cursor.execute('ALTER TABLE tasks ADD COLUMN progress INTEGER DEFAULT 0')
    print("Added progress column to tasks")
except sqlite3.OperationalError:
    pass

try:
    cursor.execute('ALTER TABLE tasks ADD COLUMN resources TEXT')
    print("Added resources column to tasks")
except sqlite3.OperationalError:
    pass

try:
    cursor.execute('ALTER TABLE tasks ADD COLUMN needs_approval BOOLEAN DEFAULT FALSE')
    print("Added needs_approval column to tasks")
except sqlite3.OperationalError:
    pass

try:
    cursor.execute('ALTER TABLE tasks ADD COLUMN approved_by INTEGER')
    print("Added approved_by column to tasks")
except sqlite3.OperationalError:
    pass

# Update status constraint to include 'pending'
try:
    cursor.execute('ALTER TABLE tasks RENAME TO temp_tasks')
    cursor.execute('''CREATE TABLE tasks (
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
    cursor.execute('INSERT INTO tasks SELECT * FROM temp_tasks')
    cursor.execute('DROP TABLE temp_tasks')
    print("Updated tasks table schema to include 'pending' status")
except sqlite3.OperationalError:
    pass

conn.commit()
conn.close()
print("Database migration completed")