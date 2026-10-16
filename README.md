# Fruit Hub

Fruit Hub is a Flask grocery storefront with SQLite-backed customer accounts and orders. Customers can create an account, add products to a shopping bag, and start an M-Pesa STK Push checkout. Prices and totals are calculated on the server.

## Run locally

From the project directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FLASK_SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
python app.py
```

Open `http://127.0.0.1:5000`. The app creates `fruits_hub.db` on first run. Set `DATABASE_PATH` to use another SQLite file.

## Configure M-Pesa Daraja sandbox

The included `Safaricom APIs.postman_collection.json` contains Daraja request examples. Fruit Hub uses its sandbox OAuth, STK Push, and STK Push query endpoints. The C2B simulator in the collection is a different payment flow and does not confirm a Fruit Hub STK Push order.

Create a Daraja sandbox app and set its credentials as environment variables; do not put credentials in `app.py` or commit them. `MPESA_CALLBACK_URL` must use HTTPS and include the same long, random token configured as `MPESA_CALLBACK_TOKEN`. A public callback URL (for example, a secure tunnel during local development) allows Daraja to notify the app. If the callback cannot reach your local machine, checkout also queries Daraja's STK Push status endpoint while the shopper waits.

```powershell
$env:MPESA_ENV = "sandbox"
$env:MPESA_CONSUMER_KEY = "your-consumer-key"
$env:MPESA_CONSUMER_SECRET = "your-consumer-secret"
$env:MPESA_SHORTCODE = "your-test-shortcode"
$env:MPESA_PASSKEY = "your-test-passkey"
$env:MPESA_CALLBACK_TOKEN = "your-long-random-callback-token"
$env:MPESA_CALLBACK_URL = "https://your-public-host/api/payments/callback?token=your-long-random-callback-token"
```

The app uses the sandbox by default. A successful checkout sends an STK Push request; the shopper approves it using the sandbox phone/test flow configured in Daraja. The browser then polls the order status. Switch `MPESA_ENV` to `production` only after configuring live Daraja credentials, shortcode, passkey, and callback URL. Set `FLASK_SECRET_KEY` to a persistent, private random value and use HTTPS in production.

## Accounts and checkout

Accounts use email addresses and passwords of at least eight characters. Passwords are stored as secure hashes. Checkout is available after signing in; successful M-Pesa callbacks update the order status and receipt in the customer's account.
