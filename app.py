from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
import os
import uuid
import json
import secrets
import re
import threading
import smtplib
import requests
import psycopg2
import razorpay
import time
from flask import g
from psycopg2.extras import RealDictCursor
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from functools import wraps

# ===============================
# LOAD ENV VARIABLES
# ===============================
load_dotenv()

app = Flask(__name__)

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/")

        if session.get("user_role") != "admin":
            return redirect("/")

        return f(*args, **kwargs)
    return decorated

razorpay_client = razorpay.Client(auth=(
    os.getenv("RAZORPAY_KEY_ID"),
    os.getenv("RAZORPAY_SECRET")
))

# ===============================
# SECRET KEY
# ===============================
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "qualyjoyn_super_random_very_long_key_2026"
)

def get_db_connection():

    if "db_conn" not in g:
        g.db_conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            sslmode="require",
            cursor_factory=RealDictCursor
        )

    return g.db_conn
# ===============================
# EMAIL CONFIG
# ===============================
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

# ===============================
# DATABASE CONFIG (SUPABASE)
# ===============================


def send_email(to_email, subject, body):
    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "html"))  # 🔥 html instead of plain

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)


def send_email_async(to_email, subject, html_content):
    def task():
        print("SendGrid thread started")

        api_key = os.environ.get("SENDGRID_API_KEY")
        print("API KEY VALUE:", api_key)

        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "personalizations": [{
                    "to": [{"email": to_email}],
                    "subject": subject
                }],
                "from": {"email": "qualyjoyn@gmail.com"},
                "content": [{
                    "type": "text/html",
                    "value": html_content
                }]
            }

            response = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers=headers,
                json=data
            )

            print("SendGrid status:", response.status_code)
            print("SendGrid response:", response.text)

        except Exception as e:
            print("SendGrid Error:", str(e))

    threading.Thread(target=task).start()


@app.route("/")
def home():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    # CASE 1: Only ONE category → show its products
    if len(categories) == 1:
        category = categories[0]

        cursor.execute("""
            SELECT * FROM products
            WHERE category = %s
        """, (category["id"],))

        raw_products = cursor.fetchall()

        products = []

        for p in raw_products:
            image_dir = os.path.join(
                app.static_folder,
                "images",
                "products",
                str(p["id"])
            )

            images = []

            if os.path.exists(image_dir):
                images = sorted([
                    img for img in os.listdir(image_dir)
                    if img.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                ])

            products.append({
                **p,
                "images": images
            })

        return render_template(
            "home.html",
            products=products,
            categories=None
        )

    # CASE 2: Multiple categories → show categories
    return render_template(
        "home.html",
        products=None,
        categories=categories
    )

@app.context_processor
def inject_nav_categories():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name, slug FROM categories")
    categories = cursor.fetchall()

    return {
        "show_categories_nav": len(categories) > 1,
        "nav_categories": categories
    }

@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        def render_register_error(message):
            flash(message, "error")
            return render_template(
                "register.html",
                name=name,
                email=email,
                phone=phone
            )

        # 🔒 VALIDATIONS
        if not name:
            return render_register_error("Name is required")

        if not email:
            return render_register_error("Email is required")

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return render_register_error("Enter a valid email address")

        if len(password) < 6:
            return render_register_error("Password must be at least 6 characters")

        if phone and not re.fullmatch(r"[6-9]\d{9}", phone):
            return render_register_error("Enter a valid 10-digit phone number")

        conn = get_db_connection()
        cursor = conn.cursor()

        # ✅ Check duplicate email
        cursor.execute(
            "SELECT id FROM users WHERE email = %s",
            (email,)
        )
        existing_email = cursor.fetchone()

        if existing_email:
            return render_register_error("Email already registered. Please login.")

        # ✅ Check duplicate phone (if provided)
        if phone:
            cursor.execute(
                "SELECT id FROM users WHERE phone = %s",
                (phone,)
            )
            existing_phone = cursor.fetchone()

            if existing_phone:
                return render_register_error("Phone number already registered.")

        password_hash = generate_password_hash(password)

        try:
            cursor.execute("""
                INSERT INTO users (name, email, password_hash, phone)
                VALUES (%s, %s, %s, %s)
            """, (name, email, password_hash, phone))

            conn.commit()

        except Exception as e:
            conn.rollback()
            print("Register Error:", e)
            return render_register_error("Something went wrong. Try again.")

        flash("Account created successfully. Please login.", "success")
        return redirect("/login")

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not identifier or not password:
            flash("All fields are required", "error")
            return render_template("login.html")

        conn = get_db_connection()
        cursor = conn.cursor()

        if identifier.isdigit():
            cursor.execute(
                "SELECT * FROM users WHERE phone = %s",
                (identifier,)
            )
        else:
            cursor.execute(
                "SELECT * FROM users WHERE email = %s",
                (identifier.lower(),)
            )

        user = cursor.fetchone()

        if user and check_password_hash(user["password_hash"], password):

            # ✅ Preserve important session data
            cart_data = session.get("cart", {})
            buy_now_data = session.get("buy_now")

            session.clear()

            # Restore cart
            if cart_data:
                session["cart"] = cart_data

            # Restore buy_now
            if buy_now_data:
                session["buy_now"] = buy_now_data

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]
            session["user_role"] = user["role"]

            next_page = request.args.get("next")

            if next_page:
                return redirect(next_page)

            return redirect("/")

        flash("Invalid credentials", "error")

    return render_template("login.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM users WHERE email = %s",
            (email,)
        )
        user = cursor.fetchone()

        if user:
            token = secrets.token_urlsafe(32)
            expiry = datetime.now() + timedelta(minutes=30)

            cursor.execute("""
                UPDATE users
                SET reset_token = %s,
                    reset_token_expiry = %s
                WHERE id = %s
            """, (token, expiry, user["id"]))

            conn.commit()

            reset_link = url_for(
                "reset_password",
                token=token,
                _external=True
            )

            email_body = f"""
            <h3>Password Reset</h3>
            <p>Click below to reset your password:</p>
            <a href="{reset_link}">{reset_link}</a>
            <p>This link expires in 30 minutes.</p>
            """

            send_email_async(email, "Reset Your Password", email_body)

        flash("If this email exists, a reset link has been sent.", "info")
        return redirect("/login")
    print("FORGOT PASSWORD ROUTE HIT")
    return render_template("forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM users
        WHERE reset_token = %s
    """, (token,))
    user = cursor.fetchone()

    if not user:
        return "Invalid or expired link", 400

    # expiry already stored as datetime in PostgreSQL
    expiry_time = user["reset_token_expiry"]

    if not expiry_time or datetime.now() > expiry_time:
        return "Reset link expired", 400

    if request.method == "POST":
        new_password = request.form.get("password")

        if len(new_password) < 6:
            flash("Password must be at least 6 characters", "error")
            return render_template("reset_password.html")

        password_hash = generate_password_hash(new_password)

        cursor.execute("""
            UPDATE users
            SET password_hash = %s,
                reset_token = NULL,
                reset_token_expiry = NULL
            WHERE id = %s
        """, (password_hash, user["id"]))

        conn.commit()

        flash("Password reset successfully. Please login.", "success")
        return redirect("/login")
    return render_template("reset_password.html")

@app.context_processor
def inject_user():
    return {
        "logged_in": "user_id" in session,
        "user_name": session.get("user_name")
    }


@app.route("/logout")
def logout():

    # Preserve cart + buy_now
    cart_data = session.get("cart")
    buy_now_data = session.get("buy_now")

    session.clear()

    if cart_data:
        session["cart"] = cart_data

    if buy_now_data:
        session["buy_now"] = buy_now_data

    return redirect("/")


@app.route("/category/<slug>")
def category(slug):

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1️⃣ Get category using slug
    cursor.execute(
        "SELECT * FROM categories WHERE slug = %s",
        (slug,)
    )
    category = cursor.fetchone()

    if not category:
        return redirect("/")

    # 2️⃣ Fetch products using category ID
    cursor.execute(
        "SELECT * FROM products WHERE category = %s",
        (category["id"],)
    )
    raw_products = cursor.fetchall()
    products = []

    for p in raw_products:
        image_dir = os.path.join(
            app.static_folder,
            "images",
            "products",
            str(p["id"])
        )

        images = []
        if os.path.exists(image_dir):
            images = sorted([
                img for img in os.listdir(image_dir)
                if img.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            ])

        products.append({
            **p,
            "images": images
        })

    return render_template(
        "category.html",
        products=products,
        category_title=category["name"]
    )

@app.route("/product/<int:product_id>")
def product_detail(product_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM products WHERE id = %s",
        (product_id,)
    )
    product = cursor.fetchone()

    if product is None:
        return "Product not found", 404

    # Related products
    cursor.execute("""
        SELECT p.*,
            (SELECT image 
                FROM product_images 
                WHERE product_id = p.id 
                LIMIT 1) as image
        FROM products p
        WHERE p.category = %s
        AND p.id != %s
    """, (product["category"], product_id))

    related_products = cursor.fetchall()

    # Sizes
    cursor.execute("""
        SELECT size as label, stock
        FROM product_sizes
        WHERE product_id = %s
    """, (product_id,))

    sizes_db = cursor.fetchall()


    # Convert sizes
    sizes = [
        {
            "label": s["label"],
            "in_stock": s["stock"] > 0
        }
        for s in sizes_db
    ]

    # Load images from folder
    image_dir = os.path.join(
        app.static_folder,
        "images",
        "products",
        str(product["id"])
    )

    images = []
    if os.path.exists(image_dir):
        images = sorted([
            img for img in os.listdir(image_dir)
            if img.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ])

    return render_template(
        "product.html",
        product=product,
        sizes=sizes,
        images=images,
        related_products=related_products
    )
@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():

    if "user_id" not in session:
        return jsonify({"success": False, "message": "Login required"}), 401

    data = request.get_json()

    product_id = int(data["product_id"])
    size = data["size"]
    qty = int(data.get("quantity", 1))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM cart
        WHERE user_id = %s AND product_id = %s AND size = %s
    """, (session["user_id"], product_id, size))

    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE cart
            SET quantity = quantity + %s
            WHERE id = %s
        """, (qty, existing["id"]))
    else:
        cursor.execute("""
            INSERT INTO cart (user_id, product_id, size, quantity)
            VALUES (%s, %s, %s, %s)
        """, (session["user_id"], product_id, size, qty))

    conn.commit()

    cursor.execute("""
        SELECT SUM(quantity) as total
        FROM cart
        WHERE user_id = %s
    """, (session["user_id"],))

    cart_count = cursor.fetchone()["total"]


    return jsonify({
        "success": True,
        "cart_count": cart_count or 0
    })

@app.route("/update-cart", methods=["POST"])
def update_cart():

    if "user_id" not in session:
        return jsonify({"success": False})

    data = request.get_json()
    cart_id = data.get("key")
    action = data.get("action")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT quantity FROM cart
        WHERE id = %s AND user_id = %s
    """, (cart_id, session["user_id"]))

    item = cursor.fetchone()

    if not item:
        return jsonify({"success": False})

    if action == "inc":
        cursor.execute("""
            UPDATE cart
            SET quantity = quantity + 1
            WHERE id = %s AND user_id = %s
        """, (cart_id, session["user_id"]))

    elif action == "dec":

        if item["quantity"] <= 1:
            cursor.execute("""
                DELETE FROM cart
                WHERE id = %s AND user_id = %s
            """, (cart_id, session["user_id"]))
        else:
            cursor.execute("""
                UPDATE cart
                SET quantity = quantity - 1
                WHERE id = %s AND user_id = %s
            """, (cart_id, session["user_id"]))

    conn.commit()
    return jsonify({"success": True})

@app.route("/my-orders")
def my_orders():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM orders
        WHERE user_id = %s
        ORDER BY created_at DESC
    """, (session["user_id"],))

    orders = cursor.fetchall()

    return render_template("my_orders.html", orders=orders)

@app.route("/cart")
def cart():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.*, p.name, p.price
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id = %s
    """, (session["user_id"],))

    rows = cursor.fetchall()

    cart_items = []
    total = 0

    for row in rows:

        subtotal = row["price"] * row["quantity"]
        total += subtotal

        image_dir = os.path.join(
            app.static_folder,
            "images",
            "products",
            str(row["product_id"])
        )

        images = []
        if os.path.exists(image_dir):
            images = sorted([
                img for img in os.listdir(image_dir)
                if img.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            ])

        cart_items.append({
            "key": row["id"],
            "product_id": row["product_id"],
            "name": row["name"],
            "price": row["price"],
            "size": row["size"],
            "quantity": row["quantity"],
            "subtotal": subtotal,
            "image": images[0] if images else "no-image.png"
        })


    return render_template(
        "cart.html",
        cart_items=cart_items,
        total=total
    )
@app.route("/remove-from-cart", methods=["POST"])
def remove_from_cart():

    if "user_id" not in session:
        return jsonify({"success": False})

    data = request.get_json()
    cart_id = data.get("key")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM cart
        WHERE id = %s AND user_id = %s
    """, (cart_id, session["user_id"]))

    conn.commit()

    cursor.execute("""
        SELECT SUM(quantity) as total
        FROM cart
        WHERE user_id = %s
    """, (session["user_id"],))

    result = cursor.fetchone()
    cart_count = result["total"] if result and result["total"] else 0

    return jsonify({
        "success": True,
        "cart_count": cart_count
    })

@app.route("/checkout", methods=["GET"])
def checkout():

    if "user_id" not in session:
        return redirect(url_for("login", next=request.url))

    # ✅ ALWAYS initialize (prevents undefined error)
    subtotal = 0
    delivery_fee = 0
    cart_items = []

    checkout_type = request.args.get("type")

    # ===============================
    # ⚡ BUY NOW FLOW
    # ===============================
    if checkout_type == "buy_now":

        item = session.get("buy_now")

        if not item:
            return redirect("/")

        session["checkout_mode"] = "buy_now"

        subtotal = item["price"] * item["quantity"]

        cart_items = [{
            **item,
            "subtotal": subtotal
        }]

    # ===============================
    # 🛒 DATABASE CART FLOW
    # ===============================
    else:

        session["checkout_mode"] = "cart"

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT c.*, p.name, p.price
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (session["user_id"],))

        rows = cursor.fetchall()

        if not rows:
            return redirect("/cart")

        for row in rows:

            item_subtotal = row["price"] * row["quantity"]
            subtotal += item_subtotal

            image_dir = os.path.join(
                app.static_folder,
                "images",
                "products",
                str(row["product_id"])
            )

            images = []
            if os.path.exists(image_dir):
                images = sorted([
                    img for img in os.listdir(image_dir)
                    if img.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                ])

            cart_items.append({
                "product_id": row["product_id"],
                "name": row["name"],
                "price": row["price"],
                "size": row["size"],
                "quantity": row["quantity"],
                "subtotal": item_subtotal,
                "image": images[0] if images else None
            })

    # ===============================
    # 🚚 DELIVERY LOGIC
    # ===============================
    if subtotal >= 1200:
        delivery_fee = 0
    else:
        delivery_fee = 99

    total = subtotal + delivery_fee

    # ===============================
    # 💳 RAZORPAY ORDER
    # ===============================
    razorpay_order = razorpay_client.order.create({
        "amount": int(total * 100),
        "currency": "INR",
        "payment_capture": 1
    })

    razorpay_order_id = razorpay_order["id"]

    return render_template(
        "checkout.html",
        cart_items=cart_items,
        subtotal=subtotal,          # ✅ ALWAYS EXISTS NOW
        delivery_fee=delivery_fee,
        total=total,
        razorpay_order_id=razorpay_order_id,
        razorpay_key=os.getenv("RAZORPAY_KEY_ID"),
        amount=int(total * 100)
    )

@app.route("/buy-now", methods=["POST"])
def buy_now():

    data = request.get_json()

    product_id = int(data["product_id"])
    size = data["size"]
    quantity = int(data.get("quantity", 1))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, name, price FROM products WHERE id = %s",
        (product_id,)
    )

    product = cursor.fetchone()

    if not product:
        return jsonify({"success": False}), 404

    # GET IMAGE FROM FOLDER
    image_dir = os.path.join(
        app.static_folder,
        "images",
        "products",
        str(product_id)
    )

    images = []
    if os.path.exists(image_dir):
        images = sorted([
            img for img in os.listdir(image_dir)
            if img.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ])

    product_image = images[0] if images else None

    session["buy_now"] = {
        "product_id": product["id"],
        "name": product["name"],
        "price": product["price"],
        "size": size,
        "quantity": quantity,
        "image": product_image
    }

    return jsonify({"success": True})


@app.route("/profile")
def profile():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE id = %s",
        (session["user_id"],)
    )

    user = cursor.fetchone()



    return render_template("profile.html", user=user)


@app.route("/place-order", methods=["POST"])
def place_order():

    if "user_id" not in session:
        return jsonify({"field": "global", "message": "Login required"}), 401

    checkout_mode = session.get("checkout_mode")

    # ===============================
    # 🔥 DETERMINE ITEMS
    # ===============================
    if checkout_mode == "buy_now":

        item = session.get("buy_now")

        if not item:
            return jsonify({"field": "global", "message": "No item found"}), 400

        items = [item]

    else:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT c.product_id, c.size, c.quantity,
                   p.name, p.price
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (session["user_id"],))

        rows = cursor.fetchall()

        if not rows:

            return jsonify({"field": "global", "message": "Your cart is empty"}), 400

        items = []
        for row in rows:
            items.append({
                "product_id": row["product_id"],
                "name": row["name"],
                "price": row["price"],
                "size": row["size"],
                "quantity": row["quantity"]
            })

   

    # ===============================
    # 📋 FORM DATA
    # ===============================
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    building = request.form.get("building", "").strip()
    street = request.form.get("street", "").strip()
    city = request.form.get("city", "").strip()
    pincode = request.form.get("pincode", "").strip()
    landmark = request.form.get("landmark", "").strip()

    # ===============================
    # ✅ VALIDATION
    # ===============================
    if len(name) < 3:
        return jsonify({"field": "name", "message": "Enter valid full name"}), 400

    if not re.match(r'^[6-9][0-9]{9}$', phone):
        return jsonify({"field": "phone", "message": "Enter valid 10-digit phone number"}), 400

    if not building:
        return jsonify({"field": "building", "message": "Enter building / apartment"}), 400

    if not street:
        return jsonify({"field": "street", "message": "Enter street / area"}), 400

    if not city:
        return jsonify({"field": "city", "message": "Enter city"}), 400

    if not re.match(r'^[0-9]{6}$', pincode):
        return jsonify({"field": "pincode", "message": "Enter valid 6-digit pincode"}), 400

    # ===============================
    # 💰 CALCULATE TOTAL
    # ===============================
    total = sum(i["price"] * i["quantity"] for i in items)
    order_id = "QJ-" + uuid.uuid4().hex[:8].upper()

    if landmark:
        full_address = f"{building}, {street}, {landmark}, {city} - {pincode}"
    else:
        full_address = f"{building}, {street}, {city} - {pincode}"

    items_json = json.dumps(items)

    # ===============================
    # 💾 SAVE ORDER + UPDATE STOCK
    # ===============================
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Insert order
        cursor.execute("""
            INSERT INTO orders (
                order_id,
                customer_name,
                phone,
                address,
                items,
                total,
                user_id,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            order_id,
            name,
            phone,
            full_address,
            items_json,
            total,
            session["user_id"],
            "open"
        ))

        # Update stock
        for item in items:
            cursor.execute("""
                UPDATE product_sizes
                SET stock = stock - %s
                WHERE product_id = %s
                AND size = %s
            """, (
                item["quantity"],
                item["product_id"],
                item["size"]
            ))

        # Clear cart
        if checkout_mode == "buy_now":
            session.pop("buy_now", None)
        else:
            cursor.execute(
                "DELETE FROM cart WHERE user_id = %s",
                (session["user_id"],)
            )

        conn.commit()

    except Exception as e:
        conn.rollback()

        print("Order Error:", e)
        return jsonify({"field": "global", "message": "Order failed. Try again."}), 500


    print("EMAIL TO:", session.get("user_email"))

    items_html = ""
    for item in items:
        items_html += f"""
            <tr>
                <td style="padding:8px 0;">{item['name']} ({item['size']})</td>
                <td align="center">{item['quantity']}</td>
                <td align="right">Rs. {item['price'] * item['quantity']}</td>
            </tr>
        """

    building = request.form.get("building", "").strip()
    street = request.form.get("street", "").strip()
    city = request.form.get("city", "").strip()
    pincode = request.form.get("pincode", "").strip()

    full_address = f"{building}, {street}, {city} - {pincode}"

    email_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background:#f5f5f5; padding:20px;">

    <table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto;background:#ffffff;padding:30px;border-radius:8px;">

    <tr>
    <td align="center" style="padding-bottom:20px;">
        <img src="https://yourdomain.com/static/images/logo.png" width="150">
    </td>
    </tr>

    <tr>
    <td>
        <h2 style="margin:0;color:#111;">Order Confirmed 🎉</h2>
        <p style="color:#555;">Hi {name},</p>
        <p style="color:#555;">
            Thank you for shopping with <strong>QualyJoyn</strong>.  
            Your order has been successfully placed.
        </p>
    </td>
    </tr>

    <tr>
    <td style="padding-top:20px;">
        <strong>Order ID:</strong> {order_id}<br>
        <strong>Date:</strong> {datetime.now().strftime('%d %b %Y')}
    </td>
    </tr>

    <tr>
    <td style="padding-top:20px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #eee;border-bottom:1px solid #eee;padding:10px 0;">
            <tr>
                <th align="left">Product</th>
                <th align="center">Qty</th>
                <th align="right">Amount</th>
            </tr>
            {items_html}
        </table>
    </td>
    </tr>

    <tr>
    <td align="right" style="padding-top:20px;">
        <h3 style="margin:0;">Total: Rs. {total}</h3>
    </td>
    </tr>

    <tr>
    <td style="padding-top:30px;">
        <h4>Shipping Address</h4>
        <p style="margin:0;color:#555;">
            {name}<br>
            {full_address}<br>
            Phone: {phone}
        </p>
    </td>
    </tr>

    <tr>
    <td style="padding-top:30px;font-size:12px;color:#888;text-align:center;">
        If you have any questions, reply to this email or contact us at qualyjoyn@gmail.com<br><br>
        © {datetime.now().year} QualyJoyn. All rights reserved.
    </td>
    </tr>

    </table>

    </body>
    </html>
    """


    try:
        user_email = session.get("user_email")

        if user_email:
            send_email_async(
                user_email,
                f"Order Confirmation - {order_id}",
                email_body
            )

    except Exception as e:
        print("Email sending failed:", e)

    return jsonify({
        "success": True,
        "redirect": url_for("order_success", order_id=order_id)
    })

@app.route("/order-success/<order_id>")
def order_success(order_id):
    import json

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM orders WHERE order_id = %s",
        (order_id,)
    )

    order = cursor.fetchone()


    if not order:
        return "Order not found", 404

    items = []

    if order["items"]:
        if isinstance(order["items"], str):
            items = json.loads(order["items"])
        else:
            items = order["items"]

    return render_template(
        "order_success.html",
        order=order,
        items=items
    )

@app.route("/verify-payment", methods=["POST"])
def verify_payment():

    data = request.json

    razorpay_payment_id = data["razorpay_payment_id"]
    razorpay_order_id = data["razorpay_order_id"]
    razorpay_signature = data["razorpay_signature"]

    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature
        })

        return jsonify({
            "success": True
        })

    except Exception as e:
        print("Payment verification failed:", e)

        return jsonify({
            "success": False
        }), 400
    

@app.route("/admin")
@admin_required
def admin_dashboard():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total FROM orders")
    total_orders = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM products")
    total_products = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM users")
    total_users = cursor.fetchone()["total"]

    return render_template(
        "admin/dashboard.html",
        total_orders=total_orders,
        total_products=total_products,
        total_users=total_users
    )

@app.route("/admin/orders")
@admin_required
def admin_orders():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT orders.*, users.email
        FROM orders
        LEFT JOIN users ON orders.user_id = users.id
        ORDER BY created_at DESC
    """)

    orders = cursor.fetchall()


    return render_template("admin/orders.html", orders=orders)

@app.route("/admin/products")
@admin_required
def admin_products():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM products
        ORDER BY id DESC
    """)

    products = cursor.fetchall()


    return render_template("admin/products.html", products=products)


@app.route("/admin/delete-product/<int:product_id>")
@admin_required
def delete_product(product_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM products WHERE id = %s",
        (product_id,)
    )

    conn.commit()

    return redirect("/admin/products")

@app.route("/admin/add-product", methods=["GET", "POST"])
@admin_required
def admin_add_product():

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == "POST":

        name = request.form.get("name")
        price = request.form.get("price")
        category = request.form.get("category")
        description = request.form.get("description")
        actual_price = request.form.get("actual_price")
        badge = request.form.get("badge")

        images = request.files.getlist("images")

        try:
            # 1️⃣ Insert product and get ID (PostgreSQL way)
            cursor.execute("""
                INSERT INTO products (name, price, actual_price, category, description, badge)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (name, price, actual_price, category, description, badge))

            product_id = cursor.fetchone()["id"]

            # -------- SAVE STOCK --------
            sizes = ["S", "M", "L", "XL"]

            for size in sizes:
                stock_value = request.form.get(f"stock_{size}", 0)

                cursor.execute("""
                    INSERT INTO product_sizes (product_id, size, stock)
                    VALUES (%s, %s, %s)
                """, (product_id, size, int(stock_value)))

            # -------- SAVE IMAGES --------
            from werkzeug.utils import secure_filename

            product_folder = os.path.join(
                app.static_folder,
                "images",
                "products",
                str(product_id)
            )

            if not os.path.exists(product_folder):
                os.makedirs(product_folder)

            for image in images:
                if image.filename != "":
                    filename = secure_filename(image.filename)
                    image_path = os.path.join(product_folder, filename)
                    image.save(image_path)

                    cursor.execute("""
                        INSERT INTO product_images (product_id, image)
                        VALUES (%s, %s)
                    """, (product_id, filename))

            conn.commit()

        except Exception as e:
            conn.rollback()
            print("Add Product Error:", e)
            return "Error adding product", 500

        return redirect("/admin/products")

    # GET request
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()


    return render_template("admin/add_product.html", categories=categories)

@app.route("/admin/order/<order_id>")
@admin_required
def admin_order_detail(order_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM orders
        WHERE order_id = %s
    """, (order_id,))

    order = cursor.fetchone()


    if not order:
        return "Order not found"

    items = json.loads(order["items"]) if order["items"] else []

    return render_template(
        "admin/order_detail.html",
        order=order,
        items=items
    )

@app.route("/admin/add-category", methods=["GET", "POST"])
@admin_required
def admin_add_category():

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        name = request.form.get("name")
        slug = request.form.get("slug")

        cursor.execute("""
            INSERT INTO categories (name, slug)
            VALUES (%s, %s)
        """, (name, slug))

        conn.commit()

        return redirect("/admin")

    return render_template("admin/add_category.html")

@app.route("/admin/categories", methods=["GET", "POST"])
@admin_required
def admin_categories():

    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 Add Category
    if request.method == "POST":
        name = request.form.get("name")
        slug = request.form.get("slug")
        image = request.files.get("image")

        image_filename = None

        if image and image.filename != "":
            from werkzeug.utils import secure_filename

            image_filename = secure_filename(image.filename)

            image_folder = os.path.join(
                app.static_folder,
                "images",
                "categories"
            )

            if not os.path.exists(image_folder):
                os.makedirs(image_folder)

            image_path = os.path.join(image_folder, image_filename)
            image.save(image_path)

        cursor.execute("""
            INSERT INTO categories (name, slug, image)
            VALUES (%s, %s, %s)
        """, (name, slug, image_filename))

        conn.commit()


        return redirect("/admin/categories")

    # 🔹 Fetch Categories
    cursor.execute("""
        SELECT *
        FROM categories
        ORDER BY id DESC
    """)

    categories = cursor.fetchall()


    return render_template(
        "admin/categories.html",
        categories=categories
    )

@app.route("/admin/delete-category/<int:id>")
@admin_required
def delete_category(id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM categories WHERE id = %s",
        (id,)
    )

    conn.commit()

    return redirect("/admin/categories")



@app.route("/help")
def help_page():
    return render_template("help.html")

@app.context_processor
def inject_cart_count():

    if "user_id" not in session:
        return {"cart_count": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT SUM(quantity) AS total
        FROM cart
        WHERE user_id = %s
    """, (session["user_id"],))

    result = cursor.fetchone()

    cart_count = result["total"] if result and result["total"] else 0

    return {"cart_count": cart_count}

@app.route("/admin/close-order/<order_id>")
@admin_required
def close_order(order_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE orders
        SET status = %s
        WHERE order_id = %s
    """, ("closed", order_id))

    conn.commit()

    return redirect("/admin/orders")

@app.teardown_appcontext
def close_db_connection(exception):

    conn = g.pop("db_conn", None)

    if conn is not None:
        conn.close()

if __name__ == "__main__":
    with app.app_context():
     app.run(host="0.0.0.0", port=5000)
