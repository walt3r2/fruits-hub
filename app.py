import base64
import hmac
import logging
from dotenv import load_dotenv
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFError
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
    DATABASE=os.environ.get(
        "DATABASE_PATH", os.path.join(os.path.dirname(__file__), "fruits_hub.db")
    ),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
    MAX_CONTENT_LENGTH=1024 * 1024,
)
csrf = CSRFProtect(app)
logging.basicConfig(level=logging.INFO)




PRODUCTS = [
    {"id": "apples", "name": "Fresh apples", "description": "Crisp, sweet and picked at their best.", "price": 120, "image": "apples.jpg", "category": "Fruit"},
    {"id": "avocado", "name": "Ripe avocado", "description": "Creamy, locally loved and ready to enjoy.", "price": 80, "image": "avocado.jpg", "category": "Fruit"},
    {"id": "bananas", "name": "Sweet bananas", "description": "A naturally sweet snack for any time of day.", "price": 60, "image": "bananas.jpg", "category": "Fruit"},
    {"id": "berries", "name": "Fresh berries", "description": "A little burst of colour and goodness.", "price": 180, "image": "berry.jpg", "category": "Fruit"},
    {"id": "blueberries", "name": "Blueberries", "description": "Juicy berries, perfect for breakfast bowls.", "price": 220, "image": "blueberry.jpg", "category": "Fruit"},
    {"id": "oranges", "name": "Juicy oranges", "description": "Bright, refreshing citrus packed with flavour.", "price": 100, "image": "oranges.jpg", "category": "Fruit"},
    {"id": "pineapple", "name": "Sweet pineapple", "description": "Golden, tropical and full of sunshine.", "price": 150, "image": "pineapple.jpg", "category": "Fruit"},
    {"id": "pears", "name": "Fresh pears", "description": "Delicate, mellow sweetness in every bite.", "price": 90, "image": "peas.jpg", "category": "Fruit"},
    {"id": "strawberries", "name": "Strawberries", "description": "Bright, juicy berries from our growers.", "price": 200, "image": "strawberry.jpg", "category": "Fruit"},
    {"id": "smoothie", "name": "Fruit smoothie", "description": "A refreshing blend made with real fruit.", "price": 250, "image": "smoothie2.jpg", "category": "Drinks"},
    {"id": "lemonade", "name": "Fresh lemonade", "description": "A cool, zesty pick-me-up for sunny days.", "price": 150, "image": "lemonade.jpg", "category": "Drinks"},
    {"id": "fruit-mix", "name": "Mixed fruit box", "description": "A colourful selection for sharing.", "price": 350, "image": "mixedfruit.jpg", "category": "Fruit"},
]
PRODUCT_BY_ID = {product["id"]: product for product in PRODUCTS}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)
    connection = sqlite3.connect(app.config["DATABASE"])
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                total INTEGER NOT NULL CHECK(total > 0),
                phone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                checkout_request_id TEXT UNIQUE,
                mpesa_receipt TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                unit_price INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0)
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


init_db()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify(error="Please sign in to continue."), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def safe_redirect_target(target):
    if not target:
        return url_for("index")
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    if test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc:
        return target
    return url_for("index")


def normalize_phone(value):
    if not isinstance(value, str):
        raise ValueError("Enter a valid Kenyan mobile number, such as 0712 345 678.")
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif digits.startswith("7") or digits.startswith("1"):
        digits = "254" + digits
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise ValueError("Enter a valid Kenyan mobile number, such as 0712 345 678.")
    return digits


def mpesa_configuration():
    required = (
        "MPESA_CONSUMER_KEY",
        "MPESA_CONSUMER_SECRET",
        "MPESA_SHORTCODE",
        "MPESA_PASSKEY",
        "MPESA_CALLBACK_URL",
        "MPESA_CALLBACK_TOKEN",
    )
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError("M-Pesa checkout is not configured. Set: " + ", ".join(missing))
    callback = urlparse(os.environ["MPESA_CALLBACK_URL"])
    callback_token = parse_qs(callback.query).get("token", [""])[0]
    if (
        callback.scheme != "https"
        or not callback.netloc
        or not hmac.compare_digest(callback_token, os.environ["MPESA_CALLBACK_TOKEN"])
    ):
        raise RuntimeError(
            "MPESA_CALLBACK_URL must be an HTTPS callback URL with the configured token query parameter."
        )
    environment = os.environ.get("MPESA_ENV", "sandbox").lower()
    if environment not in ("sandbox", "production"):
        raise RuntimeError("MPESA_ENV must be either 'sandbox' or 'production'.")
    base_url = (
        "https://api.safaricom.co.ke"
        if environment == "production"
        else "https://sandbox.safaricom.co.ke"
    )
    return base_url


def request_stk_push(amount, phone, order_id):
    base_url = mpesa_configuration()
    consumer_key = os.environ["MPESA_CONSUMER_KEY"]
    consumer_secret = os.environ["MPESA_CONSUMER_SECRET"]
    shortcode = os.environ["MPESA_SHORTCODE"]
    passkey = os.environ["MPESA_PASSKEY"]
    timestamp = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        (shortcode + passkey + timestamp).encode("utf-8")
    ).decode("ascii")

    token_response = requests.get(
        base_url + "/oauth/v1/generate",
        params={"grant_type": "client_credentials"},
        auth=(consumer_key, consumer_secret),
        timeout=15,
    )
    token_response.raise_for_status()
    token_payload = token_response.json()
    access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
    if not access_token:
        raise RuntimeError("M-Pesa did not return an access token.")

    payment_response = requests.post(
        base_url + "/mpesa/stkpush/v1/processrequest",
        json={
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone,
            "PartyB": shortcode,
            "PhoneNumber": phone,
            "CallBackURL": os.environ["MPESA_CALLBACK_URL"],
            "AccountReference": "FruitHub" + str(order_id),
            "TransactionDesc": "Fruit Hub order " + str(order_id),
        },
        headers={"Authorization": "Bearer " + access_token},
        timeout=15,
    )
    payment_response.raise_for_status()
    result = payment_response.json()
    if not isinstance(result, dict):
        raise RuntimeError("M-Pesa returned an invalid payment response.")
    if str(result.get("ResponseCode")) != "0" or not result.get("CheckoutRequestID"):
        raise RuntimeError(result.get("CustomerMessage") or "M-Pesa could not start this payment.")
    return result["CheckoutRequestID"], result.get("CustomerMessage", "Check your phone to complete payment.")


def query_stk_push(checkout_request_id):
    base_url = mpesa_configuration()
    consumer_key = os.environ["MPESA_CONSUMER_KEY"]
    consumer_secret = os.environ["MPESA_CONSUMER_SECRET"]
    shortcode = os.environ["MPESA_SHORTCODE"]
    passkey = os.environ["MPESA_PASSKEY"]
    timestamp = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        (shortcode + passkey + timestamp).encode("utf-8")
    ).decode("ascii")

    token_response = requests.get(
        base_url + "/oauth/v1/generate",
        params={"grant_type": "client_credentials"},
        auth=(consumer_key, consumer_secret),
        timeout=15,
    )
    token_response.raise_for_status()
    token_payload = token_response.json()
    access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
    if not access_token:
        raise RuntimeError("M-Pesa did not return an access token.")

    response = requests.post(
        base_url + "/mpesa/stkpushquery/v1/query",
        json={
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        },
        headers={"Authorization": "Bearer " + access_token},
        timeout=15,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("M-Pesa returned an invalid payment status.")
    return result


@app.context_processor
def inject_template_data():
    user = None
    if session.get("user_id"):
        user = get_db().execute(
            "SELECT id, name, email FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if user is None:
            session.clear()
    return {"current_user": user, "product_catalog": PRODUCTS}


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    if request.path.startswith("/api/"):
        return jsonify(error="Your session expired. Refresh the page and try again."), 400
    return render_template("csrf_error.html", reason=error.description), 400


@app.route("/")
def index():
    return render_template("index.html", products=PRODUCTS[:6])


@app.route("/products")
def products():
    return render_template("products.html", products=PRODUCTS)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/service")
def service():
    return render_template("service.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or len(name) > 100:
            flash("Please enter your name (up to 100 characters).", "error")
        elif len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Please enter a valid email address.", "error")
        elif len(password) < 8 or len(password) > 128:
            flash("Your password must be between 8 and 128 characters.", "error")
        else:
            try:
                cursor = get_db().execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password)),
                )
                get_db().commit()
            except sqlite3.IntegrityError:
                flash("An account with that email already exists. Please sign in.", "error")
            else:
                session.clear()
                session["user_id"] = cursor.lastrowid
                flash("Welcome to Fruit Hub. Your account is ready.", "success")
                return redirect(url_for("index"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or request.form.get("next")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
        password = request.form.get("password", "")
        if user is None or len(password) > 128 or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(safe_redirect_target(next_url))
    return render_template("login.html", next_url=next_url or "")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))


@app.route("/account")
@login_required
def account():
    orders = get_db().execute(
        "SELECT id, total, status, created_at, mpesa_receipt "
        "FROM orders WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],),
    ).fetchall()
    return render_template("account.html", orders=orders)


@app.route("/api/checkout", methods=["POST"])
@login_required
def checkout():
    try:
        mpesa_configuration()
    except RuntimeError as error:
        return jsonify(error=str(error)), 503

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Your checkout details are invalid."), 400
    items = data.get("items")
    if not isinstance(items, list) or not items or len(items) > len(PRODUCTS):
        return jsonify(error="Your cart is empty or invalid."), 400
    try:
        phone = normalize_phone(data.get("phone", ""))
    except ValueError as error:
        return jsonify(error=str(error)), 400

    quantities = {}
    for item in items:
        if not isinstance(item, dict):
            return jsonify(error="Your cart contains an invalid item."), 400
        product_id = item.get("product_id")
        quantity = item.get("quantity")
        if (
            not isinstance(product_id, str)
            or product_id not in PRODUCT_BY_ID
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < 1
            or quantity > 99
        ):
            return jsonify(error="Your cart contains an invalid item or quantity."), 400
        quantities[product_id] = quantities.get(product_id, 0) + quantity
        if quantities[product_id] > 99:
            return jsonify(error="You can order up to 99 of each product."), 400

    total = sum(PRODUCT_BY_ID[key]["price"] * quantity for key, quantity in quantities.items())
    connection = get_db()
    cursor = connection.execute(
        "INSERT INTO orders (user_id, total, phone) VALUES (?, ?, ?)",
        (session["user_id"], total, phone),
    )
    order_id = cursor.lastrowid
    connection.executemany(
        "INSERT INTO order_items (order_id, product_id, product_name, unit_price, quantity) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (order_id, key, PRODUCT_BY_ID[key]["name"], PRODUCT_BY_ID[key]["price"], quantity)
            for key, quantity in quantities.items()
        ],
    )
    connection.commit()
    try:
        checkout_request_id, message = request_stk_push(total, phone, order_id)
    except (requests.RequestException, RuntimeError, ValueError) as error:
        app.logger.error("M-Pesa payment setup failed for order %s: %s", order_id, error)
        connection.execute("UPDATE orders SET status = 'failed' WHERE id = ?", (order_id,))
        connection.commit()
        return jsonify(error="We could not start your M-Pesa payment. Please try again."), 502

    connection.execute(
        "UPDATE orders SET checkout_request_id = ? WHERE id = ?",
        (checkout_request_id, order_id),
    )
    connection.commit()
    return jsonify(order_id=order_id, status="pending", message=message), 201


@app.route("/api/payments/callback", methods=["POST"])
@csrf.exempt
def mpesa_callback():
    payload = request.get_json(silent=True)
    body = (payload or {}).get("Body") if isinstance(payload, dict) else None
    callback = body.get("stkCallback") if isinstance(body, dict) else None
    checkout_request_id = callback.get("CheckoutRequestID") if isinstance(callback, dict) else None
    if not isinstance(checkout_request_id, str) or not checkout_request_id or len(checkout_request_id) > 128:
        return jsonify(error="Invalid M-Pesa callback."), 400
    supplied_token = request.args.get("token", "")
    expected_token = os.environ.get("MPESA_CALLBACK_TOKEN", "")
    if not expected_token or not hmac.compare_digest(supplied_token, expected_token):
        app.logger.warning("Rejected M-Pesa callback with an invalid callback token.")
        return jsonify(error="Unauthorized callback."), 401

    connection = get_db()
    order = connection.execute(
        "SELECT id, total, status FROM orders WHERE checkout_request_id = ?",
        (checkout_request_id,),
    ).fetchone()
    if order is None:
        app.logger.warning("Received M-Pesa callback for an unknown checkout request.")
        return jsonify(error="Unknown checkout request."), 404

    result_code = callback.get("ResultCode")
    if order["status"] == "paid" and str(result_code) != "0":
        return jsonify(ResultCode=0, ResultDesc="Accepted")

    if str(result_code) == "0":
        callback_metadata = callback.get("CallbackMetadata")
        metadata = callback_metadata.get("Item", []) if isinstance(callback_metadata, dict) else []
        if not isinstance(metadata, list):
            metadata = []
        values = {
            item.get("Name"): item.get("Value")
            for item in metadata
            if isinstance(item, dict)
        }
        try:
            amount = int(values["Amount"])
            receipt = values["MpesaReceiptNumber"]
        except (KeyError, TypeError, ValueError):
            app.logger.error("M-Pesa success callback is missing payment details for order %s.", order["id"])
            if order["status"] != "paid":
                connection.execute("UPDATE orders SET status = 'failed' WHERE id = ?", (order["id"],))
        else:
            if amount == order["total"] and receipt:
                connection.execute(
                    "UPDATE orders SET status = 'paid', mpesa_receipt = ? WHERE id = ?",
                    (str(receipt), order["id"]),
                )
            else:
                app.logger.error("M-Pesa amount mismatch on order %s.", order["id"])
                if order["status"] != "paid":
                    connection.execute("UPDATE orders SET status = 'failed' WHERE id = ?", (order["id"],))
    else:
        if order["status"] != "paid":
            connection.execute("UPDATE orders SET status = 'failed' WHERE id = ?", (order["id"],))
    connection.commit()
    return jsonify(ResultCode=0, ResultDesc="Accepted")


@app.route("/api/orders/<int:order_id>")
@login_required
def order_status(order_id):
    order = get_db().execute(
        "SELECT id, total, status, created_at, mpesa_receipt, checkout_request_id "
        "FROM orders WHERE id = ? AND user_id = ?",
        (order_id, session["user_id"]),
    ).fetchone()
    if order is None:
        abort(404)
    if order["status"] == "pending" and order["checkout_request_id"]:
        try:
            result = query_stk_push(order["checkout_request_id"])
        except (requests.RequestException, RuntimeError, ValueError) as error:
            app.logger.error("M-Pesa status query failed for order %s: %s", order_id, error)
            return jsonify(error="We could not check your payment status just now."), 502

        if str(result.get("ResultCode")) == "0":
            get_db().execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
            get_db().commit()
        elif result.get("ResultCode") not in (None, ""):
            get_db().execute("UPDATE orders SET status = 'failed' WHERE id = ?", (order_id,))
            get_db().commit()

        order = get_db().execute(
            "SELECT id, total, status, created_at, mpesa_receipt "
            "FROM orders WHERE id = ? AND user_id = ?",
            (order_id, session["user_id"]),
        ).fetchone()
    else:
        order = dict(order)
        order.pop("checkout_request_id", None)
    return jsonify(dict(order))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
