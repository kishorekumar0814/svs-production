from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    mobile = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    auid = db.Column(db.String(20), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    mobile = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    cuid = db.Column(db.String(20), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(30), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    raw_text = db.Column(db.Text, nullable=True)  # data entered in box
    uploaded_filename = db.Column(db.String(300), nullable=True)
    pickup_option = db.Column(db.String(50), nullable=False, default='Self Pick')
    status = db.Column(db.String(50), nullable=False, default='Pending')  # Pending, Received, Packed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', backref='orders')

class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.String(30), unique=True, nullable=False)
    order_id = db.Column(db.String(30), nullable=False)  # link by order_id string
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    items_json = db.Column(db.Text, nullable=True)  # json list of items
    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_filename = db.Column(db.String(300), nullable=True)

    admin = db.relationship('Admin', backref='bills')

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_role = db.Column(db.String(20), nullable=False)  # admin or customer
    actor_id = db.Column(db.Integer, nullable=True)
    actor_name = db.Column(db.String(150), nullable=True)
    action = db.Column(db.String(50), nullable=False)  # login, logout
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FavoriteItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    item_text = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', backref='favorite_items')
