from flask import Flask, request, render_template
import mysql.connector

app = Flask(__name__)

# Set up the database connection
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="customer_db"
)

# Create a cursor object
cursor = db.cursor()

# Create the orders table if it doesn't exist
cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        cust_name VARCHAR(255),
        email VARCHAR(255),
        phone_number VARCHAR(255),
        product_cost INT
    )
""")

# Commit the transaction
db.commit()

# Function to handle the form submission
def handle_orders_submission(cust_name, email, phone_number, product_cost):
    # Connect to the database
    conn = mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="customer_db"
    )

    # Create a cursor object
    cursor = conn.cursor()

    # Insert the order into the database
    cursor.execute("""
        INSERT INTO orders (cust_name, email, phone_number, product_cost)VALUES (%s, %s, %s, %s)
    """, (cust_name, email, phone_number, product_cost))

    # Commit the transaction
    conn.commit()

    # Close the connection
    conn.close()

    # Return a message indicating that the order was successful
    return 'Order for {} {} has been successfully made.'.format(cust_name, email)

# Route for the form page CRUD 
# create -> post
# read -> get
# update -> put
# delete -> delete
# REST API - Representational State Transfer
@app.route('/', methods=['GET', 'POST'])
def index():
    print(request.method)
    if request.method == 'POST':
        custname = request.form['cust_name']
        em = request.form['email']
        pn = request.form['phone_number']
        pcost = int(request.form['product_cost'])
        message = handle_orders_submission(cust_name=custname, email=em, phone_number=pn ,product_cost=pcost)
        return render_template('index.html', message=message)
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/products')
def products():
    return render_template('products.html')

@app.route('/service')
def service():
    return render_template('service.html')


if __name__ == '__main__':
    app.run(debug=True)

