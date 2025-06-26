# utils.py
import sqlite3

def get_db_connection():
    conn = sqlite3.connect('tasks.db')  # Use consistent database name
    conn.row_factory = sqlite3.Row
    return conn