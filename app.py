from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
import time
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder='templates')
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'finalcafe.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        ''')
        conn.commit()
        _migrate_legacy_menu(conn)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL DEFAULT 0,
                category_id INTEGER,
                image_path TEXT,
                FOREIGN KEY(category_id) REFERENCES categories(id)
            )
        ''')
        # เพิ่มตารางหลังร้าน
        conn.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                customer_name TEXT,
                order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                total REAL DEFAULT 0,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY(employee_id) REFERENCES employees(id)
            )
        ''')
        conn.commit()


def allowed_file(filename):
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


def save_image(file):
    if not file or file.filename == '':
        return None
    if not allowed_file(file.filename):
        return None
    filename = secure_filename(file.filename)
    timestamp = str(int(time.time()))
    safe_name = f"{timestamp}_{filename}"
    destination = os.path.join(UPLOAD_FOLDER, safe_name)
    file.save(destination)
    return os.path.join('uploads', safe_name).replace('\\', '/')


def _migrate_legacy_menu(conn):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(menu)")]
    if not columns:
        return
    if 'image_path' in columns:
        return
    if 'category_id' in columns:
        conn.execute('ALTER TABLE menu ADD COLUMN image_path TEXT')
        conn.commit()
        return
    if 'category' not in columns:
        return

    existing_categories = {row['name']: row['id'] for row in conn.execute('SELECT id, name FROM categories')}
    rows = conn.execute('SELECT menu_id, name, price, category FROM menu').fetchall()

    conn.execute('''
        CREATE TABLE IF NOT EXISTS menu_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL DEFAULT 0,
            category_id INTEGER,
            image_path TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        )
    ''')

    for row in rows:
        category_name = row['category']
        category_id = None
        if category_name:
            category_key = category_name.strip()
            if category_key:
                category_id = existing_categories.get(category_key)
                if category_id is None:
                    cursor = conn.execute('INSERT INTO categories (name) VALUES (?)', (category_key,))
                    category_id = cursor.lastrowid
                    existing_categories[category_key] = category_id

        conn.execute(
            'INSERT INTO menu_new (name, description, price, category_id, image_path) VALUES (?, ?, ?, ?, ?)',
            (row['name'], '', row['price'], category_id, None)
        )

    conn.execute('DROP TABLE menu')
    conn.execute('ALTER TABLE menu_new RENAME TO menu')
    conn.commit()


@app.route('/')
def home():
    init_db()
    conn = get_db()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    menu = conn.execute('''
        SELECT menu.*, categories.name AS category_name
        FROM menu
        LEFT JOIN categories ON menu.category_id = categories.id
        ORDER BY menu.name
    ''').fetchall()
    conn.close()
    return render_template('index.html', page='home', categories=categories, menu=menu)


@app.route('/category/<int:category_id>')
def view_category(category_id):
    init_db()
    conn = get_db()
    category = conn.execute('SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()
    if not category:
        conn.close()
        return redirect(url_for('home'))
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    menu = conn.execute('''
        SELECT menu.*, categories.name AS category_name
        FROM menu
        LEFT JOIN categories ON menu.category_id = categories.id
        WHERE menu.category_id = ?
        ORDER BY menu.name
    ''', (category_id,)).fetchall()
    conn.close()
    return render_template('index.html', page='category', category=category, categories=categories, menu=menu)


@app.route('/add_category', methods=['GET', 'POST'])
def add_category():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            conn = get_db()
            conn.execute('INSERT INTO categories (name) VALUES (?)', (name,))
            conn.commit()
            conn.close()
        return redirect(url_for('home'))
    return render_template('index.html', page='add_category')


@app.route('/edit_category/<int:id>', methods=['GET', 'POST'])
def edit_category(id):
    conn = get_db()
    category = conn.execute('SELECT * FROM categories WHERE id = ?', (id,)).fetchone()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            conn.execute('UPDATE categories SET name = ? WHERE id = ?', (name, id))
            conn.commit()
        conn.close()
        return redirect(url_for('home'))
    conn.close()
    return render_template('index.html', page='edit_category', category=category)


@app.route('/delete_category/<int:id>')
def delete_category(id):
    conn = get_db()
    conn.execute('DELETE FROM categories WHERE id = ?', (id,))
    conn.execute('UPDATE menu SET category_id = NULL WHERE category_id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('home'))


@app.route('/add_menu', methods=['GET', 'POST'])
def add_menu():
    conn = get_db()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price = request.form.get('price', '0').strip() or '0'
        category_id = request.form.get('category_id')
        image = request.files.get('image')
        if name:
            image_path = save_image(image)
            conn.execute(
                'INSERT INTO menu (name, description, price, category_id, image_path) VALUES (?, ?, ?, ?, ?)',
                (name, description, float(price), category_id if category_id else None, image_path)
            )
            conn.commit()
            conn.close()
            return redirect(url_for('home'))
    conn.close()
    return render_template('index.html', page='add_menu', categories=categories)


@app.route('/edit_menu/<int:id>', methods=['GET', 'POST'])
def edit_menu(id):
    conn = get_db()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    menu_item = conn.execute('SELECT * FROM menu WHERE id = ?', (id,)).fetchone()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price = request.form.get('price', '0').strip() or '0'
        category_id = request.form.get('category_id')
        delete_image = request.form.get('delete_image')
        image = request.files.get('image')
        if name:
            image_path = menu_item['image_path'] if menu_item else None
            if delete_image:
                image_path = None
            new_image_path = save_image(image)
            if new_image_path:
                image_path = new_image_path
            conn.execute(
                'UPDATE menu SET name = ?, description = ?, price = ?, category_id = ?, image_path = ? WHERE id = ?',
                (name, description, float(price), category_id if category_id else None, image_path, id)
            )
            conn.commit()
            conn.close()
            return redirect(url_for('home'))
    conn.close()
    return render_template('index.html', page='edit_menu', menu_item=menu_item, categories=categories)


@app.route('/delete_menu/<int:id>')
def delete_menu(id):
    conn = get_db()
    conn.execute('DELETE FROM menu WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('home'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
