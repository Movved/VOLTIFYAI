import sqlite3
import hashlib
import os

# Database configurations
MYSQL_HOST = '127.0.0.1'
MYSQL_USER = 'root'
MYSQL_PASSWORD = ''
MYSQL_DB = 'voltifyai'
SQLITE_DB = 'data/voltifyai.db'

# Active database mode ('mysql' or 'sqlite')
db_mode = None

def hash_password(password):
    """Simple SHA-256 hashing for user passwords."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def get_connection():
    """
    Attempts to connect to MySQL (XAMPP).
    If MySQL is not available or SQLite was selected, falls back to SQLite.
    """
    global db_mode
    
    if db_mode == 'sqlite':
        os.makedirs(os.path.dirname(SQLITE_DB), exist_ok=True)
        conn = sqlite3.connect(SQLITE_DB)
        conn.row_factory = sqlite3.Row
        return conn
        
    try:
        import pymysql
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            autocommit=True
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {MYSQL_DB}")
        cursor.close()
        
        conn.select_db(MYSQL_DB)
        db_mode = 'mysql'
        return conn
    except Exception as e:
        print(f"[VoltifyAI DB] MySQL connection failed, falling back to SQLite. Error: {e}")
        db_mode = 'sqlite'
        os.makedirs(os.path.dirname(SQLITE_DB), exist_ok=True)
        conn = sqlite3.connect(SQLITE_DB)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    """
    Initializes the database schema and seeds the default administrator
    credentials. Gracefully handles query failures and falls back to SQLite.
    """
    global db_mode
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        print(f"[VoltifyAI DB] Initializing database in {db_mode.upper()} mode...")
        
        if db_mode == 'mysql':
            try:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        password VARCHAR(255) NOT NULL,
                        role VARCHAR(20) DEFAULT 'operator'
                    )
                """)
                cursor.execute("SELECT id FROM users WHERE username = %s", ('admin',))
                admin_exists = cursor.fetchone()
                
                if not admin_exists:
                    hashed_pwd = hash_password('admin')
                    cursor.execute(
                        "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                        ('admin', hashed_pwd, 'admin')
                    )
                    print("[VoltifyAI DB] Seeded default administrator user (admin/admin) into MySQL")
                conn.close()
                return
            except Exception as mysql_err:
                print(f"[VoltifyAI DB] MySQL query failed during init. Forcing SQLite fallback. Error: {mysql_err}")
                conn.close()
                db_mode = 'sqlite'
                
        # SQLite Fallback Initializer
        os.makedirs(os.path.dirname(SQLITE_DB), exist_ok=True)
        conn = sqlite3.connect(SQLITE_DB)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'operator'
            )
        """)
        conn.commit()
        
        cursor.execute("SELECT id FROM users WHERE username = ?", ('admin',))
        admin_exists = cursor.fetchone()
        
        if not admin_exists:
            hashed_pwd = hash_password('admin')
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                ('admin', hashed_pwd, 'admin')
            )
            conn.commit()
            print("[VoltifyAI DB] Seeded default administrator user (admin/admin) into SQLite")
        conn.close()
        
    except Exception as e:
        print("[VoltifyAI DB] Fatal error initializing database:", e)

def verify_user(username, password):
    """
    Verifies user credentials.
    Supports fault-tolerant fallback from MySQL to SQLite.
    """
    global db_mode
    hashed_pwd = hash_password(password)
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        if db_mode == 'mysql':
            cursor.execute(
                "SELECT id, username, role FROM users WHERE username = %s AND password = %s",
                (username, hashed_pwd)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return {'id': row[0], 'username': row[1], 'role': row[2]}
        else:
            cursor.execute(
                "SELECT id, username, role FROM users WHERE username = ? AND password = ?",
                (username, hashed_pwd)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return {'id': row[0], 'username': row[1], 'role': row[2]}
    except Exception as e:
        print(f"[VoltifyAI DB] Error during verification, attempting SQLite fallback: {e}")
        if db_mode == 'mysql':
            db_mode = 'sqlite'
            try:
                os.makedirs(os.path.dirname(SQLITE_DB), exist_ok=True)
                conn = sqlite3.connect(SQLITE_DB)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, username, role FROM users WHERE username = ? AND password = ?",
                    (username, hashed_pwd)
                )
                row = cursor.fetchone()
                conn.close()
                if row:
                    return {'id': row[0], 'username': row[1], 'role': row[2]}
            except Exception as sqlite_err:
                print(f"[VoltifyAI DB] SQLite fallback verification failed: {sqlite_err}")
                
    return None
