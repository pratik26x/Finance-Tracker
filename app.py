from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime, timedelta
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
load_dotenv()

# Set template folder to current directory (root)
app = Flask(__name__, template_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# Database connection using environment variable
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db():
    """Get database connection with dict cursor"""
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = RealDictCursor
    return conn

def init_db():
    """Initialize database tables"""
    conn = get_db()
    c = conn.cursor()
    
    # Transactions table
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id SERIAL PRIMARY KEY,
                  type TEXT NOT NULL,
                  category TEXT NOT NULL,
                  amount REAL NOT NULL,
                  description TEXT,
                  date TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Budgets table
    c.execute('''CREATE TABLE IF NOT EXISTS budgets
                 (id SERIAL PRIMARY KEY,
                  category TEXT NOT NULL UNIQUE,
                  amount REAL NOT NULL,
                  month TEXT NOT NULL)''')
    
    # Savings goals table
    c.execute('''CREATE TABLE IF NOT EXISTS savings_goals
                 (id SERIAL PRIMARY KEY,
                  name TEXT NOT NULL,
                  target_amount REAL NOT NULL,
                  current_amount REAL DEFAULT 0,
                  deadline TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = get_db()
    c = conn.cursor()
    
    # Get current month transactions
    current_month = datetime.now().strftime('%Y-%m')
    
    # Calculate total income and expenses
    c.execute("SELECT SUM(amount) as total FROM transactions WHERE type='income' AND date LIKE %s", 
              (current_month + '%',))
    result = c.fetchone()
    total_income = result['total'] or 0
    
    c.execute("SELECT SUM(amount) as total FROM transactions WHERE type='expense' AND date LIKE %s", 
              (current_month + '%',))
    result = c.fetchone()
    total_expenses = result['total'] or 0
    
    # Get recent transactions
    c.execute("SELECT * FROM transactions ORDER BY date DESC, id DESC LIMIT 10")
    recent_transactions = c.fetchall()
    
    # Get expense by category for current month
    c.execute("""SELECT category, SUM(amount) as total 
                 FROM transactions 
                 WHERE type='expense' AND date LIKE %s
                 GROUP BY category""", (current_month + '%',))
    expense_by_category = c.fetchall()
    
    # Get savings goals
    c.execute("SELECT * FROM savings_goals")
    savings_goals = c.fetchall()
    
    conn.close()
    
    balance = total_income - total_expenses
    
    return render_template('index.html', 
                         total_income=total_income,
                         total_expenses=total_expenses,
                         balance=balance,
                         recent_transactions=recent_transactions,
                         expense_by_category=expense_by_category,
                         savings_goals=savings_goals)

@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    trans_type = request.form['type']
    category = request.form['category']
    amount = float(request.form['amount'])
    description = request.form.get('description', '')
    date = request.form['date']
    
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO transactions (type, category, amount, description, date) VALUES (%s, %s, %s, %s, %s)",
              (trans_type, category, amount, description, date))
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))

@app.route('/transactions')
def transactions():
    conn = get_db()
    c = conn.cursor()
    
    # Get filter parameters
    filter_type = request.args.get('type', 'all')
    filter_category = request.args.get('category', 'all')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []
    
    if filter_type != 'all':
        query += " AND type = %s"
        params.append(filter_type)
    
    if filter_category != 'all':
        query += " AND category = %s"
        params.append(filter_category)
    
    if start_date:
        query += " AND date >= %s"
        params.append(start_date)
    
    if end_date:
        query += " AND date <= %s"
        params.append(end_date)
    
    query += " ORDER BY date DESC, id DESC"
    
    c.execute(query, params)
    all_transactions = c.fetchall()
    
    # Get unique categories
    c.execute("SELECT DISTINCT category FROM transactions ORDER BY category")
    categories = c.fetchall()
    
    conn.close()
    
    return render_template('transactions.html', 
                         transactions=all_transactions,
                         categories=categories,
                         filter_type=filter_type,
                         filter_category=filter_category,
                         start_date=start_date,
                         end_date=end_date)

@app.route('/delete_transaction/<int:id>')
def delete_transaction(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('transactions'))

@app.route('/budgets')
def budgets():
    conn = get_db()
    c = conn.cursor()
    
    current_month = datetime.now().strftime('%Y-%m')
    
    # Get budgets for current month
    c.execute("SELECT * FROM budgets WHERE month = %s", (current_month,))
    budget_list = c.fetchall()
    
    # Get actual spending by category for current month
    budget_data = []
    for budget in budget_list:
        c.execute("""SELECT SUM(amount) as spent FROM transactions 
                     WHERE type='expense' AND category=%s AND date LIKE %s""",
                  (budget['category'], current_month + '%'))
        result = c.fetchone()
        spent = result['spent'] or 0
        budget_data.append({
            'id': budget['id'],
            'category': budget['category'],
            'budget': budget['amount'],
            'spent': spent,
            'remaining': budget['amount'] - spent,
            'percentage': (spent / budget['amount'] * 100) if budget['amount'] > 0 else 0
        })
    
    conn.close()
    
    return render_template('budgets.html', budgets=budget_data, current_month=current_month)

@app.route('/add_budget', methods=['POST'])
def add_budget():
    category = request.form['category']
    amount = float(request.form['amount'])
    month = request.form.get('month', datetime.now().strftime('%Y-%m'))
    
    conn = get_db()
    c = conn.cursor()
    
    # Check if budget already exists for this category and month
    c.execute("SELECT id FROM budgets WHERE category=%s AND month=%s", (category, month))
    existing = c.fetchone()
    
    if existing:
        c.execute("UPDATE budgets SET amount=%s WHERE category=%s AND month=%s",
                  (amount, category, month))
    else:
        c.execute("INSERT INTO budgets (category, amount, month) VALUES (%s, %s, %s)",
                  (category, amount, month))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('budgets'))

@app.route('/savings')
def savings():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM savings_goals ORDER BY deadline")
    goals = c.fetchall()
    conn.close()
    
    return render_template('savings.html', goals=goals)

@app.route('/add_savings_goal', methods=['POST'])
def add_savings_goal():
    name = request.form['name']
    target_amount = float(request.form['target_amount'])
    current_amount = float(request.form.get('current_amount', 0))
    deadline = request.form.get('deadline', '')
    
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO savings_goals (name, target_amount, current_amount, deadline) VALUES (%s, %s, %s, %s)",
              (name, target_amount, current_amount, deadline))
    conn.commit()
    conn.close()
    
    return redirect(url_for('savings'))

@app.route('/update_savings/<int:id>', methods=['POST'])
def update_savings(id):
    amount = float(request.form['amount'])
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE savings_goals SET current_amount = current_amount + %s WHERE id = %s",
              (amount, id))
    conn.commit()
    conn.close()
    
    return redirect(url_for('savings'))

@app.route('/delete_savings/<int:id>')
def delete_savings(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM savings_goals WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('savings'))

@app.route('/reports')
def reports():
    conn = get_db()
    c = conn.cursor()
    
    # Get monthly income and expense trends (last 6 months)
    monthly_data = []
    for i in range(5, -1, -1):
        month = (datetime.now() - timedelta(days=30*i)).strftime('%Y-%m')
        
        c.execute("SELECT SUM(amount) as income FROM transactions WHERE type='income' AND date LIKE %s",
                  (month + '%',))
        result = c.fetchone()
        income = result['income'] or 0
        
        c.execute("SELECT SUM(amount) as expense FROM transactions WHERE type='expense' AND date LIKE %s",
                  (month + '%',))
        result = c.fetchone()
        expense = result['expense'] or 0
        
        monthly_data.append({
            'month': month,
            'income': income,
            'expense': expense,
            'savings': income - expense
        })
    
    # Get category-wise spending (current month)
    current_month = datetime.now().strftime('%Y-%m')
    c.execute("""SELECT category, SUM(amount) as total 
                 FROM transactions 
                 WHERE type='expense' AND date LIKE %s
                 GROUP BY category
                 ORDER BY total DESC""", (current_month + '%',))
    category_spending = c.fetchall()
    
    conn.close()
    
    return render_template('reports.html', 
                         monthly_data=monthly_data,
                         category_spending=category_spending)

# Initialize database on first run (only if DATABASE_URL is set)
if DATABASE_URL:
    try:
        init_db()
    except Exception as e:
        print(f"Database initialization error: {e}")

# For Vercel - this is critical!
app.debug = False

# Vercel will look for 'app' variable
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
