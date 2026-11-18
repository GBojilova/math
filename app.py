import io
import os
import sqlite3
from flask import Flask, jsonify, render_template, request
from pypdf import PdfReader

app = Flask(__name__)

# Пътека към базата данни в същата папка, където е app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "tasks.db")


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Таблица за настройки и парола
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute(
        "SELECT value FROM settings WHERE key = 'admin_password'"
    )
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO settings (key, value) VALUES ('admin_password', 'admin123')"
        )

    # Таблица за класове и теми
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grade TEXT NOT NULL,
            topic TEXT NOT NULL
        )
    """)

    # Таблица за задачите
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grade TEXT NOT NULL,
            topic TEXT NOT NULL,
            question TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            explanation TEXT NOT NULL
        )
    """)

    # Начални примерни данни при първо стартиране
    cursor.execute("SELECT COUNT(*) FROM tasks")
    if cursor.fetchone()[0] == 0:
        sample_categories = [
            ("1. клас", "Действия с числа до 20"),
            ("5. клас", "Обикновени дроби"),
            ("6. клас", "Уравнения"),
        ]
        cursor.executemany(
            "INSERT INTO categories (grade, topic) VALUES (?, ?)",
            sample_categories,
        )

        sample_tasks = [
            (
                "1. клас",
                "Действия с числа до 20",
                "Колко е 8 + 7?",
                "15",
                "Разделяме 7 на 2 и 5. Първо 8 + 2 = 10, след това 10 + 5 = 15.",
            ),
            (
                "5. клас",
                "Обикновени дроби",
                "Пресметнете: $$\\frac{1}{2} + \\frac{1}{4}$$ (въведете като десетична дроб)",
                "0.75",
                "$$\\frac{1}{2} = 0.50$$ и $$\\frac{1}{4} = 0.25$$. Сборът им е $$0.75$$.",
            ),
            (
                "6. клас",
                "Уравнения",
                "Решете уравнението: $$2x + 6 = 14$$",
                "4",
                "$$2x = 14 - 6 \\Rightarrow 2x = 8 \\Rightarrow x = 4$$",
            ),
        ]
        cursor.executemany(
            "INSERT INTO tasks (grade, topic, question, correct_answer, explanation) VALUES (?, ?, ?, ?, ?)",
            sample_tasks,
        )

    conn.commit()
    conn.close()


# Инициализираме базата при зареждане на приложението
init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin")
def admin():
    return render_template("admin.html")


# --- АДМИН ВХОД И ПАРОЛА ---
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.json or {}
    entered_password = data.get("password", "")

    conn = get_db_connection()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'admin_password'"
    ).fetchone()
    conn.close()

    current_password = row["value"] if row else "admin123"

    if entered_password == current_password:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Грешна парола!"}), 401


@app.route("/api/admin/change-password", methods=["POST"])
def change_password():
    data = request.json or {}
    old_pass = data.get("old_password", "")
    new_pass = data.get("new_password", "")

    if not old_pass or not new_pass:
        return jsonify({"error": "Моля, попълнете и двете полета!"}), 400

    conn = get_db_connection()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'admin_password'"
    ).fetchone()
    current_password = row["value"] if row else "admin123"

    if old_pass != current_password:
        conn.close()
        return jsonify({"error": "Старата парола е грешна!"}), 400

    conn.execute(
        "UPDATE settings SET value = ? WHERE key = 'admin_password'",
        (new_pass,),
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Паролата е сменена успешно!"})


# --- API ЗА УЧЕНИЦИТЕ ---
@app.route("/api/categories", methods=["GET"])
def get_categories():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT DISTINCT grade, topic FROM categories ORDER BY grade, topic"
    ).fetchall()
    conn.close()

    categories = {}
    for row in rows:
        grade = row["grade"]
        topic = row["topic"]
        if grade not in categories:
            categories[grade] = []
        if topic not in categories[grade]:
            categories[grade].append(topic)

    return jsonify(categories)


@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    grade = request.args.get("grade")
    topic = request.args.get("topic")

    conn = get_db_connection()
    if grade and topic:
        rows = conn.execute(
            "SELECT id, grade, topic, question FROM tasks WHERE grade = ? AND topic = ?",
            (grade, topic),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, grade, topic, question FROM tasks"
        ).fetchall()

    tasks = [dict(row) for row in rows]
    conn.close()
    return jsonify(tasks)


@app.route("/api/check", methods=["POST"])
def check_answer():
    data = request.json or {}
    task_id = data.get("task_id")
    
    # Почистваме отговора на ученика
    user_raw = str(data.get("answer", "")).strip().lower().replace(",", ".")
    user_answer = user_raw.replace("$", "").strip()

    conn = get_db_connection()
    task = conn.execute(
        "SELECT correct_answer, explanation FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    conn.close()

    if not task:
        return jsonify({"error": "Задачата не е намерена"}), 404

    # Почистваме и верния отговор от базата данни
    correct_raw = str(task["correct_answer"]).strip().lower().replace(",", ".")
    correct_answer = correct_raw.replace("$", "").strip()

    # Умна проверка: Опитваме се да ги сравним като числа (за да е еднакво 5 и 5.0)
    is_correct = False
    try:
        if float(user_answer) == float(correct_answer):
            is_correct = True
    except ValueError:
        # Ако не са числа, правим текстово сравнение
        is_correct = user_answer == correct_answer

    # Ето това липсваше в предишния отговор и даваше undefined:
    return jsonify({
        "is_correct": is_correct,
        "explanation": task["explanation"]
    })


# --- API ЗА АДМИН ПАНЕЛА ---
@app.route("/api/admin/categories", methods=["GET", "POST", "DELETE"])
def manage_categories():
    conn = get_db_connection()

    if request.method == "GET":
        rows = conn.execute(
            "SELECT * FROM categories ORDER BY grade, topic"
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    elif request.method == "POST":
        data = request.json or {}
        grade = data.get("grade", "").strip()
        topic = data.get("topic", "").strip()
        if not grade or not topic:
            conn.close()
            return jsonify({"error": "Всички полета са задължителни!"}), 400

        conn.execute(
            "INSERT INTO categories (grade, topic) VALUES (?, ?)",
            (grade, topic),
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Категорията е добавена!"})

    elif request.method == "DELETE":
        cat_id = request.args.get("id")
        conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
        conn.commit()
        conn.close()
        return jsonify({"message": "Категорията е изтрита!"})


@app.route("/api/admin/tasks", methods=["GET", "DELETE"])
def manage_tasks():
    conn = get_db_connection()

    if request.method == "GET":
        rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    elif request.method == "DELETE":
        task_id = request.args.get("id")
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        return jsonify({"message": "Задачата е изтрита!"})


@app.route("/api/admin/tasks/bulk", methods=["POST"])
def add_tasks_bulk():
    data = request.json or {}
    tasks_list = data.get("tasks", [])

    if not tasks_list:
        return jsonify({"error": "Няма подадени задачи за запис!"}), 400

    conn = get_db_connection()
    try:
        for t in tasks_list:
            grade = t.get("grade", "").strip()
            topic = t.get("topic", "").strip()
            question = t.get("question", "").strip()
            correct_answer = t.get("correct_answer", "").strip()
            explanation = t.get("explanation", "").strip()

            if not all([grade, topic, question, correct_answer]):
                continue

            conn.execute(
                """
                INSERT INTO tasks (grade, topic, question, correct_answer, explanation)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    grade,
                    topic,
                    question,
                    correct_answer,
                    explanation or "Няма въведено обяснение.",
                ),
            )

        conn.commit()
        conn.close()
        return jsonify({"message": "Задачите бяха добавени успешно!"})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/import-pdf", methods=["POST"])
def import_pdf():
    if "pdf_file" not in request.files:
        return jsonify({"error": "Няма качен PDF файл!"}), 400

    file = request.files["pdf_file"]
    grade = request.form.get("grade", "1. клас").strip()
    topic = request.form.get("topic", "Обща тема").strip()

    try:
        pdf_reader = PdfReader(io.BytesIO(file.read()))
        extracted_text = ""
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text:
                extracted_text += text + "\n"

        lines = [
            line.strip() for line in extracted_text.split("\n") if line.strip()
        ]

        conn = get_db_connection()

        # Добавяме категорията автоматично, ако не съществува
        existing_cat = conn.execute(
            "SELECT id FROM categories WHERE grade = ? AND topic = ?",
            (grade, topic),
        ).fetchone()
        if not existing_cat:
            conn.execute(
                "INSERT INTO categories (grade, topic) VALUES (?, ?)",
                (grade, topic),
            )

        count = 0
        for line in lines:
            # Формат 1 (Нов): Условие | Верен отговор | Обяснение (по желание)
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 2 and parts[0] and parts[1]:
                    question = parts[0].replace("___", "?").replace("__", "?")
                    correct_answer = parts[1]
                    explanation = (
                        parts[2]
                        if len(parts) >= 3 and parts[2]
                        else "Няма въведено обяснение."
                    )

                    conn.execute(
                        """
                        INSERT INTO tasks (grade, topic, question, correct_answer, explanation)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (grade, topic, question, correct_answer, explanation),
                    )
                    count += 1

            # Формат 2 (Резервен): Само условие със знак '=' (слага '0' за отговор)
            elif "=" in line or (
                len(line) > 3 and line[0].isdigit() and "." in line[:4]
            ):
                clean_question = line.replace("___", "?").replace("__", "?")
                conn.execute(
                    """
                    INSERT INTO tasks (grade, topic, question, correct_answer, explanation)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        grade,
                        topic,
                        clean_question,
                        "0",
                        "Импортирано без отговор (моля, редактирайте).",
                    ),
                )
                count += 1

        conn.commit()
        conn.close()

        if count == 0:
            return jsonify(
                {
                    "error": "Не бяха открити задачи в този PDF файл (уверете се, че не е сканирана снимка)."
                }
            ), 400

        return jsonify({"message": f"Успешно импортирани {count} задачи!"})
    except Exception as e:
        return jsonify({"error": f"Грешка при четене на PDF: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
