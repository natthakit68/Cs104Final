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
        _migrate_legacy_employees(conn)
        _migrate_legacy_orders(conn)
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


def _migrate_legacy_employees(conn):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(employees)")]
    if not columns:
        return
    if 'id' in columns:
        return
    if 'employee_id' not in columns:
        return

    rows = conn.execute('SELECT employee_id, name, role FROM employees').fetchall()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS employees_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    for row in rows:
        conn.execute(
            'INSERT INTO employees_new (id, name, role) VALUES (?, ?, ?)',
            (row['employee_id'], row['name'], row['role'])
        )
    conn.execute('DROP TABLE employees')
    conn.execute('ALTER TABLE employees_new RENAME TO employees')
    conn.commit()


def _migrate_legacy_orders(conn):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(orders)")]
    if not columns:
        return
    if 'id' in columns and 'customer_name' in columns:
        return
    if 'order_id' not in columns:
        return

    rows = conn.execute('SELECT order_id, customer_id, employee_id, order_date FROM orders').fetchall()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS orders_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            customer_name TEXT,
            order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            total REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
    ''')
    for row in rows:
        customer_name = f"ลูกค้า #{row['customer_id']}" if row['customer_id'] is not None else ''
        conn.execute(
            'INSERT INTO orders_new (id, employee_id, customer_name, order_date, total, status) VALUES (?, ?, ?, ?, ?, ?)',
            (row['order_id'], row['employee_id'], customer_name, row['order_date'], 0.0, 'pending')
        )
    conn.execute('DROP TABLE orders')
    conn.execute('ALTER TABLE orders_new RENAME TO orders')
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


@app.route('/employees')
def employees():
    init_db()
    conn = get_db()
    employees = conn.execute('SELECT * FROM employees ORDER BY name').fetchall()
    conn.close()
    return render_template('index.html', page='employees', employees=employees)


@app.route('/add_employee', methods=['GET', 'POST'])
def add_employee():
    init_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()
        if name and role:
            conn = get_db()
            conn.execute('INSERT INTO employees (name, role) VALUES (?, ?)', (name, role))
            conn.commit()
            conn.close()
            return redirect(url_for('employees'))
    return render_template('index.html', page='add_employee')


@app.route('/edit_employee/<int:id>', methods=['GET', 'POST'])
def edit_employee(id):
    init_db()
    conn = get_db()
    employee = conn.execute('SELECT * FROM employees WHERE id = ?', (id,)).fetchone()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()
        if name and role:
            conn.execute('UPDATE employees SET name = ?, role = ? WHERE id = ?', (name, role, id))
            conn.commit()
            conn.close()
            return redirect(url_for('employees'))
    conn.close()
    return render_template('index.html', page='edit_employee', employee=employee)


@app.route('/delete_employee/<int:id>')
def delete_employee(id):
    init_db()
    conn = get_db()
    conn.execute('DELETE FROM employees WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('employees'))


@app.route('/orders')
def orders():
    init_db()
    conn = get_db()
    orders = conn.execute('''
        SELECT orders.*, employees.name AS employee_name
        FROM orders
        LEFT JOIN employees ON orders.employee_id = employees.id
        ORDER BY orders.order_date DESC
    ''').fetchall()
    conn.close()
    return render_template('index.html', page='orders', orders=orders)


@app.route('/add_order', methods=['GET', 'POST'])
def add_order():
    init_db()
    conn = get_db()
    employees = conn.execute('SELECT * FROM employees ORDER BY name').fetchall()
    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        employee_id = request.form.get('employee_id')
        total = request.form.get('total', '0').strip() or '0'
        if customer_name:
            conn.execute(
                'INSERT INTO orders (customer_name, employee_id, total, status) VALUES (?, ?, ?, ?)',
                (customer_name, employee_id if employee_id else None, float(total), 'pending')
            )
            conn.commit()
            conn.close()
            return redirect(url_for('orders'))
    conn.close()
    return render_template('index.html', page='add_order', employees=employees)


@app.route('/delete_order/<int:id>')
def delete_order(id):
    init_db()
    conn = get_db()
    conn.execute('DELETE FROM orders WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('orders'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
