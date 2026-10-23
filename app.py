
from flask import Flask, render_template, request, jsonify
import mysql.connector
from datetime import datetime, date, timedelta
import calendar
import os

app = Flask(__name__)


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database="expense_tracker"
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, expense_date, expense_time, subject, price
            FROM expenses
            WHERE expense_date >= CURDATE() - INTERVAL 44 DAY
            ORDER BY expense_date DESC, expense_time DESC
        """)

        rows = cursor.fetchall()

        for row in rows:
            row["expense_date"] = row["expense_date"].isoformat()
            row["expense_time"] = str(row["expense_time"])[:5]
            row["price"] = float(row["price"])

        return jsonify(rows)

    except mysql.connector.Error:
        return jsonify({"error": "Could not connect to the database. Check MySQL settings."}), 500

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@app.route("/api/expenses", methods=["POST"])
def add_expense():
    data = request.get_json(silent=True) or {}
    subject = str(data.get("subject", "")).strip()

    try:
        price = float(data.get("price", 0))

        if not subject or len(subject) > 100 or not (0 < price <= 99999999):
            raise ValueError

    except (ValueError, TypeError):
        return jsonify({
            "error": "Enter a subject and a valid amount greater than zero."
        }), 400

    now = datetime.now()
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO expenses
            (expense_date, expense_time, subject, price)
            VALUES (%s, %s, %s, %s)
            """,
            (now.date(), now.time().replace(microsecond=0), subject, price)
        )

        conn.commit()

        return jsonify({"message": "Expense added successfully."}), 201

    except mysql.connector.Error:
        return jsonify({
            "error": "Could not save the expense. Check the MySQL connection."
        }), 500

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@app.route("/api/monthly-report")
def monthly_report():
    today = date.today()
    first_day_this_month = today.replace(day=1)
    last_day_previous_month = first_day_this_month - timedelta(days=1)
    first_day_previous_month = last_day_previous_month.replace(day=1)

    days_in_month = calendar.monthrange(
        first_day_previous_month.year,
        first_day_previous_month.month
    )[1]

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                COALESCE(SUM(price), 0) AS total,
                COUNT(*) AS expense_count
            FROM expenses
            WHERE expense_date >= %s
              AND expense_date < %s
        """, (first_day_previous_month, first_day_this_month))

        summary = cursor.fetchone()
        total = float(summary["total"])
        count = int(summary["expense_count"])

        cursor.execute("""
            SELECT
                DAY(expense_date) AS day,
                SUM(price) AS total
            FROM expenses
            WHERE expense_date >= %s
              AND expense_date < %s
            GROUP BY expense_date
            ORDER BY expense_date
        """, (first_day_previous_month, first_day_this_month))

        daily_rows = cursor.fetchall()

        daily = [
            {"day": int(row["day"]), "total": float(row["total"])}
            for row in daily_rows
        ]

        highest_day = None

        if daily:
            highest = max(daily, key=lambda row: row["total"])
            highest_date = date(
                first_day_previous_month.year,
                first_day_previous_month.month,
                highest["day"]
            )
            highest_day = highest_date.strftime("%d %b")

        return jsonify({
            "month": first_day_previous_month.strftime("%B %Y"),
            "total": total,
            "count": count,
            "daily_average": round(total / days_in_month, 2),
            "highest_day": highest_day,
            "daily": daily
        })

    except mysql.connector.Error:
        return jsonify({"error": "Could not generate the monthly report."}), 500

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


if __name__ == "__main__":
    app.run(debug=True)
