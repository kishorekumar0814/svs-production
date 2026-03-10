# app.py (updated)
import os
import random
import base64
import html
import requests
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, abort, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, Admin, Customer, Order, Bill, ActivityLog, FavoriteItem
from utils import generate_auid, generate_cuid, generate_order_id, generate_bill_id, now_str, items_to_json, items_from_json
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from PIL import Image
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

# Load environment variables early
load_dotenv()


DATABASE_URL = (
    os.getenv("DATABASE_URL")
)

UPLOAD_FOLDER = os.path.join('instance', 'uploads')
ALLOWED_EXT = set(['png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'])

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

attempts = {}

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def _email_error_hint():
    try:
        err = getattr(g, "email_send_error", "")
        if not err:
            return ""
        err = str(err).strip()
        if not err:
            return ""
        if len(err) > 180:
            err = err[:180] + "..."
        return f" ({err})"
    except Exception:
        return ""

def _email_shell(title, subtitle, content_html):
    safe_title = html.escape(title)
    safe_subtitle = html.escape(subtitle)
    return f"""
    <html>
      <body style="margin:0;background:#eef3f7;font-family:Segoe UI,Arial,sans-serif;color:#1f2d3d;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px;">
          <tr>
            <td align="center">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border:1px solid #d8e1ea;border-radius:14px;overflow:hidden;">
                <tr>
                  <td style="padding:20px 24px;background:linear-gradient(135deg,#1f6f6d,#194f67);color:#ffffff;">
                    <h2 style="margin:0;font-size:24px;">Sri Vinayaga Stores</h2>
                    <p style="margin:6px 0 0;font-size:14px;opacity:.95;">{safe_subtitle}</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:24px;">
                    <h3 style="margin:0 0 12px;color:#16324f;font-size:21px;">{safe_title}</h3>
                    {content_html}
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 24px;background:#f7fafc;border-top:1px solid #e8edf3;color:#4c6073;font-size:13px;">
                    Need help? Reply to this email or contact Sri Vinayaga Stores.
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

def smtp_send(to_emails, subject, html_content, attachments=None):
    """
    Send an email via SendGrid SMTP (preferred) or Resend API (fallback).
    - to_emails: single email or list
    - attachments: list of dicts: [{"content": base64str, "type":"application/pdf","filename":"x.pdf"}]
    """
    try:
        to_list = to_emails if isinstance(to_emails, list) else [to_emails]
        if not to_list:
            return False

        from_name = os.getenv("FROM_NAME", "Sri Vinayaga Stores").strip()
        from_email = (
            os.getenv("SENDGRID_FROM_EMAIL")
            or os.getenv("RESEND_FROM_EMAIL")
            or os.getenv("FROM_EMAIL")
        )
        if not from_email:
            msg = "FROM_EMAIL not set"
            print(msg)
            try:
                g.email_send_error = msg
            except Exception:
                pass
            return False

        sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "").strip()
        if sendgrid_api_key:
            smtp_host = os.getenv("SENDGRID_SMTP_HOST", "smtp.sendgrid.net").strip()
            smtp_port = int(os.getenv("SENDGRID_SMTP_PORT", "587"))
            smtp_user = os.getenv("SENDGRID_SMTP_USERNAME", "apikey").strip()
            smtp_pass = sendgrid_api_key
            use_tls = os.getenv("SENDGRID_SMTP_USE_TLS", "True") == "True"
            use_ssl = os.getenv("SENDGRID_SMTP_USE_SSL", "False") == "True"

            msg = EmailMessage()
            msg["From"] = formataddr((from_name, from_email))
            msg["To"] = ", ".join(to_list)
            msg["Subject"] = subject
            msg.set_content("Please view this email in an HTML-capable client.")
            msg.add_alternative(html_content, subtype="html")

            if attachments:
                for at in attachments:
                    content_b64 = at.get("content")
                    filename = at.get("filename", "attachment")
                    mime = at.get("type", "application/octet-stream")
                    if not content_b64:
                        continue
                    try:
                        data = base64.b64decode(content_b64)
                    except Exception:
                        continue
                    if "/" in mime:
                        maintype, subtype = mime.split("/", 1)
                    else:
                        maintype, subtype = "application", "octet-stream"
                    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

            if use_ssl:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
                    smtp.login(smtp_user, smtp_pass)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
                    if use_tls:
                        smtp.starttls()
                    smtp.login(smtp_user, smtp_pass)
                    smtp.send_message(msg)
            return True

        resend_api_key = os.getenv("RESEND_API_KEY", "").strip()
        if not resend_api_key:
            msg = "SENDGRID_API_KEY/RESEND_API_KEY not set"
            print(msg)
            try:
                g.email_send_error = msg
            except Exception:
                pass
            return False

        payload = {
            "from": formataddr((from_name, from_email)),
            "to": to_list,
            "subject": subject,
            "html": html_content,
        }
        if attachments:
            resend_attachments = []
            for at in attachments:
                resend_attachments.append({
                    "filename": at.get("filename", "attachment"),
                    "content": at.get("content", ""),
                })
            payload["attachments"] = resend_attachments

        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {resend_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if response.status_code >= 400:
            msg = f"Resend send error {response.status_code}: {response.text}"
            print(msg)
            try:
                g.email_send_error = msg
            except Exception:
                pass
            return False
        return True

    except Exception as e:
        msg = f"Email send exception: {e}"
        print(msg)
        try:
            g.email_send_error = msg
        except Exception:
            pass
        return False

def send_email_otp(to_email, otp):
    """
    Convenience wrapper specifically for OTP emails.
    """
    otp_str = html.escape(str(otp))
    content = f"""
    <p style="margin:0 0 12px;">Use this one-time password to continue:</p>
    <div style="margin:14px 0;padding:14px 16px;background:#e6f3f2;border:1px dashed #1f6f6d;border-radius:10px;text-align:center;">
      <span style="font-size:30px;letter-spacing:5px;font-weight:800;color:#194f67;">{otp_str}</span>
    </div>
    <p style="margin:0 0 8px;color:#4c6073;">This OTP expires in <b>5 minutes</b>.</p>
    <p style="margin:0;color:#7a2c22;">Do not share this OTP with anyone.</p>
    """
    email_html = _email_shell("Verification OTP", "Secure account verification", content)
    return smtp_send(to_email, "Sri Vinayaga Stores - OTP", email_html)

def send_welcome_email(customer: Customer):
    """
    Send welcome email to new customer with their details.
    """
    try:
        customer_name = html.escape(customer.name or "Customer")
        customer_cuid = html.escape(customer.cuid or "-")
        customer_mobile = html.escape(customer.mobile or "-")
        customer_addr = html.escape(customer.address or "-")
        subject = f"Welcome to Sri Vinayaga Stores - {customer_name}"
        content = f"""
        <p style="margin:0 0 12px;">Welcome <b>{customer_name}</b>, your account is ready.</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e8edf3;border-radius:10px;overflow:hidden;">
          <tr><td style="padding:10px 12px;background:#f7fafc;width:140px;"><b>CUID</b></td><td style="padding:10px 12px;">{customer_cuid}</td></tr>
          <tr><td style="padding:10px 12px;background:#f7fafc;"><b>Mobile</b></td><td style="padding:10px 12px;">{customer_mobile}</td></tr>
          <tr><td style="padding:10px 12px;background:#f7fafc;"><b>Address</b></td><td style="padding:10px 12px;">{customer_addr}</td></tr>
        </table>
        <p style="margin:14px 0 0;">Thank you for choosing Sri Vinayaga Stores.</p>
        """
        email_html = _email_shell("Welcome Onboard", "Customer account created", content)
        smtp_send(customer.email, subject, email_html)
    except Exception as e:
        print("welcome email error:", e)

def send_order_to_store(order: Order, customer: Customer):
    """
    When customer places an order, email store with order info.
    If a file was uploaded, attach it.
    """
    try:
        store_email = os.getenv("STORE_EMAIL") or os.getenv("FROM_EMAIL")
        if not store_email:
            print("STORE_EMAIL/FROM_EMAIL not set; skipping order email.")
            return False

        safe_order_id = html.escape(order.order_id or "-")
        safe_customer_name = html.escape(customer.name or "-")
        safe_mobile = html.escape(customer.mobile or "-")
        safe_address = html.escape(customer.address or "-")
        safe_order_text = html.escape(order.raw_text or "-")
        safe_pickup = html.escape(order.pickup_option or "-")
        subject = f"New Order: {safe_order_id} from {safe_customer_name}"
        content = f"""
        <p style="margin:0 0 10px;">A new customer order has been submitted.</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e8edf3;border-radius:10px;overflow:hidden;">
          <tr><td style="padding:10px 12px;background:#f7fafc;width:150px;"><b>Order ID</b></td><td style="padding:10px 12px;">{safe_order_id}</td></tr>
          <tr><td style="padding:10px 12px;background:#f7fafc;"><b>Customer</b></td><td style="padding:10px 12px;">{safe_customer_name}</td></tr>
          <tr><td style="padding:10px 12px;background:#f7fafc;"><b>Mobile</b></td><td style="padding:10px 12px;">{safe_mobile}</td></tr>
          <tr><td style="padding:10px 12px;background:#f7fafc;"><b>Address</b></td><td style="padding:10px 12px;">{safe_address}</td></tr>
          <tr><td style="padding:10px 12px;background:#f7fafc;"><b>Pickup</b></td><td style="padding:10px 12px;">{safe_pickup}</td></tr>
        </table>
        <p style="margin:12px 0 6px;"><b>Order Items / Notes</b></p>
        <pre style="margin:0;padding:12px;background:#f8fafc;border:1px solid #e8edf3;border-radius:10px;white-space:pre-wrap;">{safe_order_text}</pre>
        """
        email_html = _email_shell("New Customer Order", "Incoming order alert", content)

        attachments = None
        if order.uploaded_filename:
            path = os.path.join(UPLOAD_FOLDER, order.uploaded_filename)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                    attachments = [{
                        "content": data,
                        "type": mimetype_from_filename(order.uploaded_filename),
                        "filename": order.uploaded_filename
                    }]

        return smtp_send(store_email, subject, email_html, attachments=attachments)
    except Exception as e:
        print("send_order_to_store error:", e)
        return False

def send_status_email(order: Order):
    """
    Notify the customer about order status change.
    """
    try:
        customer = Customer.query.get(order.customer_id)
        if not customer or not customer.email:
            return False

        safe_name = html.escape(customer.name or "Customer")
        safe_order_id = html.escape(order.order_id or "-")
        safe_status = html.escape(order.status or "-")
        subject = f"Order {safe_order_id} status updated"
        content = f"""
        <p style="margin:0 0 10px;">Hi <b>{safe_name}</b>,</p>
        <p style="margin:0 0 12px;">Your order status has been updated.</p>
        <div style="padding:12px;border:1px solid #e8edf3;border-radius:10px;background:#f8fbff;">
          <p style="margin:0 0 6px;"><b>Order ID:</b> {safe_order_id}</p>
          <p style="margin:0;"><b>Current Status:</b> <span style="color:#165654;">{safe_status}</span></p>
        </div>
        """
        email_html = _email_shell("Order Status Update", "Track your latest order progress", content)
        return smtp_send(customer.email, subject, email_html)
    except Exception as e:
        print("send_status_email error:", e)
        return False

def send_bill_email(bill: Bill):
    """
    Send generated PDF bill as attachment to the customer linked to the bill's order.
    """
    try:
        # find order and customer
        order = Order.query.filter_by(order_id=bill.order_id).first()
        if not order:
            print("Order not found for bill")
            return False
        customer = Customer.query.get(order.customer_id)
        if not customer or not customer.email:
            print("Customer missing for bill")
            return False

        pdf_fname = bill.pdf_filename
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_fname)
        attachments = None
        if pdf_fname and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
                attachments = [{
                    "content": data,
                    "type": "application/pdf",
                    "filename": pdf_fname
                }]

        safe_name = html.escape(customer.name or "Customer")
        safe_bill_id = html.escape(bill.bill_id or "-")
        safe_order_id = html.escape(bill.order_id or "-")
        subject = f"Sri Vinayaga Stores - Your Bill {safe_bill_id}"
        content = f"""
        <p style="margin:0 0 10px;">Hi <b>{safe_name}</b>, your bill is now ready.</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e8edf3;border-radius:10px;overflow:hidden;">
          <tr><td style="padding:10px 12px;background:#f7fafc;width:140px;"><b>Bill ID</b></td><td style="padding:10px 12px;">{safe_bill_id}</td></tr>
          <tr><td style="padding:10px 12px;background:#f7fafc;"><b>Order ID</b></td><td style="padding:10px 12px;">{safe_order_id}</td></tr>
          <tr><td style="padding:10px 12px;background:#f7fafc;"><b>Total</b></td><td style="padding:10px 12px;"><b>Rs {bill.total_amount:.2f}</b></td></tr>
        </table>
        <p style="margin:12px 0 0;">Please find the bill attached to this email.</p>
        """
        email_html = _email_shell("Bill Generated", "Your purchase summary is attached", content)
        return smtp_send(customer.email, subject, email_html, attachments=attachments)
    except Exception as e:
        print("send_bill_email error:", e)
        return False

def send_announcement_email(to_email, subject, message_html):
    content = f"""
    <p style="margin:0 0 12px;">Hello,</p>
    <div style="padding:12px;background:#f8fbff;border:1px solid #e8edf3;border-radius:10px;">
      {message_html}
    </div>
    """
    email_html = _email_shell(subject, "Important update from Sri Vinayaga Stores", content)
    return smtp_send(to_email, f"Sri Vinayaga Stores - {subject}", email_html)

def send_reorder_reminder_email(customer: Customer, days_without_order: int):
    safe_name = html.escape(customer.name or "Customer")
    content = f"""
    <p style="margin:0 0 10px;">Hi <b>{safe_name}</b>, we miss you at Sri Vinayaga Stores.</p>
    <p style="margin:0 0 10px;">You have not placed an order for <b>{days_without_order} days</b>.</p>
    <p style="margin:0;">Open your dashboard to quickly reorder previous items or use your favorites list.</p>
    """
    email_html = _email_shell("Friendly Reminder", "Your groceries are just one click away", content)
    return smtp_send(customer.email, "Sri Vinayaga Stores - We miss your orders", email_html)

def log_activity(actor_role, actor_id, actor_name, action):
    try:
        entry = ActivityLog(
            actor_role=actor_role,
            actor_id=actor_id,
            actor_name=actor_name,
            action=action
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("activity log error:", e)

def mimetype_from_filename(fname):
    ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
    mapping = {
        'pdf': 'application/pdf',
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    }
    return mapping.get(ext, 'application/octet-stream')

# ---------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------
def create_app():
    app = Flask(__name__, instance_relative_config=True)

    ist_tz = timezone(timedelta(hours=5, minutes=30))

    @app.template_filter("ist_datetime")
    def ist_datetime(dt):
        if not dt:
            return "-"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ist_tz).strftime("%d %b %Y %I:%M %p")

    # Basic config
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'devkey')
    # Database URL is read from DATABASE_URL in environment variables.
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # Connection pool settings for PostgreSQL.
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_pre_ping": True,       # Detect stale connections before use
        "pool_recycle": 300,         # Recycle connections every 5 minutes
        "pool_size": 5,              # Persistent connection pool size
        "max_overflow": 2,           # Extra connections allowed under load
        "connect_args": {"sslmode": "require"},  # Keep SSL enabled for managed DB providers
    }
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    # Resend settings used by smtp_send() (kept function name to avoid changing call sites)
    app.config['RESEND_API_KEY'] = os.getenv("RESEND_API_KEY", "")
    app.config['RESEND_FROM_EMAIL'] = os.getenv("RESEND_FROM_EMAIL", os.getenv("FROM_EMAIL", ""))

    db.init_app(app)

    # Avoid hard crash on platforms where DB is temporarily unreachable during boot.
    # Control with AUTO_CREATE_TABLES=True/False (defaults to False on Render, True locally).
    auto_create_default = "False" if os.getenv("RENDER") else "True"
    auto_create_tables = os.getenv("AUTO_CREATE_TABLES", auto_create_default) == "True"
    if auto_create_tables:
        with app.app_context():
            try:
                db.create_all()
            except Exception as e:
                print("DB init warning (create_all skipped):", e)

    # ----- decorators -----
    def admin_required(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') != 'admin' or not session.get('admin_id'):
                flash("Admin login required", "warning")
                return redirect(url_for('admin_login'))
            return f(*args, **kwargs)
        return decorated

    def customer_required(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') != 'customer' or not session.get('customer_id'):
                flash("Customer login required", "warning")
                return redirect(url_for('customer_login'))
            return f(*args, **kwargs)
        return decorated

    # ----- routes -----
    @app.route('/')
    def home():
        return render_template('home.html')

    @app.route('/offline')
    def offline():
        return render_template('offline.html')

    @app.route("/admin/security", methods=["GET", "POST"])
    def admin_security():
        key_id = "admin_security"
        if not check_rate_limit(key_id):
            flash("Too many attempts! Try again after 5 minutes.", "danger")
            return render_template("admin_key.html")
        if request.method == "POST":
            entered = request.form.get("secret_key")
            if entered == os.getenv("ADMIN_SECURITY_KEY"):
                attempts[key_id] = {"count": 0, "block_until": None}
                session["admin_access"] = True
                return redirect(url_for("admin_login"))
            record_failed_attempt(key_id)
            flash("Invalid security key!", "danger")
            return render_template("admin_key.html")
        return render_template("admin_key.html")

    @app.route("/admin/resend-otp")
    def admin_resend_otp():
        data = session.get("pending_admin")
        if not data:
            flash("Session expired. Please sign up again.", "danger")
            return redirect(url_for("admin_signup"))
        email = data["email"]
        new_otp = random.randint(100000, 999999)
        session["pending_admin"]["otp"] = new_otp
        if send_email_otp(email, new_otp):
            flash("A new OTP has been sent to your email!", "success")
        else:
            flash("Failed to send OTP email. Please check SMTP server settings." + _email_error_hint(), "danger")
        return redirect(url_for("admin_verify_otp"))

    def check_rate_limit(key):
        info = attempts.get(key)
        if info:
            if info.get("block_until") and datetime.now() < info["block_until"]:
                return False
            if info["count"] >= 3:
                attempts[key] = {"count": 0, "block_until": None}
        return True

    def record_failed_attempt(key):
        info = attempts.get(key, {"count": 0, "block_until": None})
        info["count"] += 1
        if info["count"] >= 3:
            info["block_until"] = datetime.now() + timedelta(minutes=5)
        attempts[key] = info

    # ----- Admin signup/login/dashboard -----
    @app.route("/admin/signup", methods=["GET", "POST"])
    def admin_signup():
        if not session.get("admin_access"):
            return redirect(url_for("admin_security"))
        if request.method == 'POST':
            name = request.form.get('name')
            email = request.form.get('email')
            mobile = request.form.get('mobile')
            password = request.form.get('password')
            if not (name and email and mobile and password):
                flash("Please fill all fields", "danger")
                return redirect(url_for('admin_signup'))
            if Admin.query.filter_by(email=email).first():
                flash("Email already exists", "danger")
                return redirect(url_for('admin_signup'))
            otp = random.randint(100000, 999999)
            session["pending_admin"] = {
                "name": name,
                "email": email,
                "mobile": mobile,
                "password_hash": generate_password_hash(password),
                "otp": otp
            }
            # Send OTP via SMTP
            if send_email_otp(email, otp):
                flash("OTP sent to your email!", "success")
                return redirect(url_for("admin_verify_otp"))
            flash("Failed to send OTP email. Please verify SMTP settings." + _email_error_hint(), "danger")
            return redirect(url_for("admin_signup"))
        return render_template("admin_signup.html")

    @app.route("/admin/verify-otp", methods=["GET", "POST"])
    def admin_verify_otp():
        data = session.get("pending_admin")
        if not data:
            flash("Session expired. Please sign up again.", "danger")
            return redirect(url_for("admin_signup"))
        if request.method == "POST":
            entered_otp = request.form.get("otp")
            if str(entered_otp) == str(data["otp"]):
                auid = generate_auid()
                new_admin = Admin(
                    name=data["name"],
                    email=data["email"],
                    mobile=data["mobile"],
                    password_hash=data["password_hash"],
                    auid=auid
                )
                db.session.add(new_admin)
                db.session.commit()
                session.pop("pending_admin")
                flash(f"Admin account created successfully! Your AUID: {auid}", "success")
                return redirect(url_for("admin_login"))
            flash("Incorrect OTP! Try again.", "danger")
        return render_template("admin_verify_otp.html")

    @app.route('/admin/login', methods=['GET','POST'])
    def admin_login():
        key_id = "admin_login"
        if not check_rate_limit(key_id):
            flash("Too many failed login attempts! Try again after 5 minutes.", "danger")
            return render_template('admin_login.html')
        if request.method == 'POST':
            identifier = request.form.get('identifier')
            password = request.form.get('password')
            admin = Admin.query.filter((Admin.email == identifier) | (Admin.auid == identifier)).first()
            if admin and check_password_hash(admin.password_hash, password):
                attempts[key_id] = {"count": 0, "block_until": None}
                session.clear()
                session['role'] = 'admin'
                session['admin_id'] = admin.id
                session['admin_name'] = admin.name
                log_activity("admin", admin.id, admin.name, "login")
                flash("Admin logged in", "success")
                return redirect(url_for('admin_dashboard'))
            record_failed_attempt(key_id)
            flash("Invalid credentials!", "danger")
            return render_template('admin_login.html')
        return render_template('admin_login.html')

    @app.route('/admin/logout')
    def admin_logout():
        if session.get('role') == 'admin':
            log_activity("admin", session.get('admin_id'), session.get('admin_name'), "logout")
        session.clear()
        flash("Logged out", "info")
        return redirect(url_for('home'))

    @app.route('/admin/dashboard')
    @admin_required
    def admin_dashboard():
        admin = Admin.query.get(session['admin_id'])
        orders = Order.query.order_by(Order.created_at.desc()).all()
        bills = Bill.query.order_by(Bill.created_at.desc()).all()
        billed_order_ids = {b.order_id for b in bills}
        active_orders = [o for o in orders if o.order_id not in billed_order_ids]
        billed_orders_data = []
        for b in bills:
            matched_order = next((o for o in orders if o.order_id == b.order_id), None)
            if matched_order:
                billed_orders_data.append({"order": matched_order, "bill": b})
        customers_count = Customer.query.count()
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        pending_orders = Order.query.filter_by(status="Pending").count()
        completed_orders = Order.query.filter(Order.status.in_(["Packed", "Delivered/Pickup Ready"])).count()
        notifications = Order.query.filter_by(status="Pending").order_by(Order.created_at.desc()).limit(10).all()
        last_seen_notif = session.get("admin_last_seen_notifications")
        notif_query = Order.query.filter(Order.status == "Pending")
        if last_seen_notif:
            try:
                notif_since = datetime.fromisoformat(last_seen_notif)
                notif_query = notif_query.filter(Order.created_at > notif_since)
            except ValueError:
                pass
        unseen_notifications_count = notif_query.count()
        recent_customer_activities = ActivityLog.query.filter_by(actor_role="customer").order_by(ActivityLog.created_at.desc()).limit(25).all()
        last_seen_activity = session.get("admin_last_seen_activity")
        activity_query = ActivityLog.query.filter(ActivityLog.actor_role == "customer")
        if last_seen_activity:
            try:
                activity_since = datetime.fromisoformat(last_seen_activity)
                activity_query = activity_query.filter(ActivityLog.created_at > activity_since)
            except ValueError:
                pass
        activity_count = activity_query.count()
        customer_logins_today = ActivityLog.query.filter(
            ActivityLog.actor_role == "customer",
            ActivityLog.action == "login",
            ActivityLog.created_at >= today_start
        ).count()
        return render_template(
            'admin_dashboard.html',
            admin=admin,
            orders=active_orders,
            bills=bills,
            billed_orders_data=billed_orders_data,
            customers_count=customers_count,
            pending_orders=pending_orders,
            completed_orders=completed_orders,
            notifications=notifications,
            unseen_notifications_count=unseen_notifications_count,
            activity_count=activity_count,
            customer_logins_today=customer_logins_today,
            recent_customer_activities=recent_customer_activities
        )

    @app.route('/admin/notifications/seen', methods=['POST'])
    @admin_required
    def admin_notifications_seen():
        session['admin_last_seen_notifications'] = datetime.utcnow().isoformat()
        return jsonify({"ok": True})

    @app.route('/admin/activity/seen', methods=['POST'])
    @admin_required
    def admin_activity_seen():
        session['admin_last_seen_activity'] = datetime.utcnow().isoformat()
        return jsonify({"ok": True})

    @app.route('/admin/upload_qr', methods=['POST'])
    @admin_required
    def admin_upload_qr():
        qr_file = request.files.get('qr')
        if qr_file:
            filename = "qr_code.png"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            qr_file.save(filepath)
            session['qr_uploaded'] = True
            flash("QR Code uploaded successfully", "success")
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/update', methods=['GET', 'POST'])
    @admin_required
    def admin_update():
        admin = Admin.query.get(session['admin_id'])
        if request.method == 'POST':
            name = request.form.get('name')
            email = request.form.get('email')
            mobile = request.form.get('mobile')
            existing = Admin.query.filter_by(email=email).first()
            if existing and existing.id != admin.id:
                flash("Email already taken", "danger")
                return redirect(url_for('admin_update'))
            admin.name = name
            admin.email = email
            admin.mobile = mobile
            db.session.commit()
            session['admin_name'] = name
            flash("Profile updated successfully", "success")
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_update.html', admin=admin)

    @app.route('/admin/delete', methods=['POST'])
    @admin_required
    def admin_delete():
        admin = Admin.query.get(session['admin_id'])
        bills = Bill.query.filter_by(admin_id=admin.id).all()
        for b in bills:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], b.pdf_filename))
            except:
                pass
            db.session.delete(b)
        db.session.delete(admin)
        db.session.commit()
        session.clear()
        flash("Admin account deleted permanently.", "info")
        return redirect(url_for('home'))

    @app.route('/admin/delete-bill/<bill_id>', methods=['POST'])
    @admin_required
    def delete_bill(bill_id):
        bill = Bill.query.filter_by(bill_id=bill_id).first()
        if not bill:
            flash("Bill not found!", "danger")
            return redirect(url_for('admin_dashboard'))
        try:
            # remove pdf file if exists
            if bill.pdf_filename:
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], bill.pdf_filename))
                except:
                    pass
            db.session.delete(bill)
            db.session.commit()
            flash("Bill deleted successfully!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting bill: {str(e)}", "danger")
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/billed-order/<bill_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_billed_order(bill_id):
        bill = Bill.query.filter_by(bill_id=bill_id).first()
        if not bill:
            flash("Billed order not found.", "warning")
            return redirect(url_for('admin_dashboard'))
        try:
            order = Order.query.filter_by(order_id=bill.order_id).first()
            if bill.pdf_filename:
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], bill.pdf_filename))
                except:
                    pass
            if order and order.uploaded_filename:
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], order.uploaded_filename))
                except:
                    pass
            db.session.delete(bill)
            if order:
                db.session.delete(order)
            db.session.commit()
            flash("Billed order deleted successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting billed order: {str(e)}", "danger")
        return redirect(url_for('admin_dashboard'))

    @app.route("/admin/forgot-password", methods=["GET", "POST"])
    def admin_forgot_password():
        if request.method == "POST":
            email = request.form["email"]
            new_password = request.form["new_password"]
            confirm_password = request.form["confirm_password"]
            if new_password != confirm_password:
                flash("Passwords do not match!", "error")
                return redirect(url_for("admin_forgot_password"))
            admin = Admin.query.filter_by(email=email).first()
            if not admin:
                flash("Admin email not found!", "error")
                return redirect(url_for("admin_forgot_password"))
            admin.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash("Password changed successfully!", "success")
            return redirect(url_for("admin_login"))
        return render_template("admin_forgot_password.html")

    @app.route("/admin/customers")
    def admin_customers():
        if session.get('role') != 'admin':
            flash("Unauthorized access!", "danger")
            return redirect(url_for('admin_login'))
        customers = Customer.query.all()
        return render_template("admin_customers.html", customers=customers)

    @app.route('/admin/send-mail', methods=['POST'])
    @admin_required
    def admin_send_mail():
        target = request.form.get('target', 'all')
        subject = (request.form.get('subject') or "").strip()
        message = (request.form.get('message') or "").strip()
        customer_ref = (request.form.get('customer_ref') or "").strip()

        if not subject or not message:
            flash("Subject and message are required.", "danger")
            return redirect(url_for('admin_dashboard'))

        message_html = html.escape(message).replace("\n", "<br>")
        sent_count = 0

        if target == 'all':
            customers = Customer.query.all()
            for cust in customers:
                if cust.email and send_announcement_email(cust.email, subject, message_html):
                    sent_count += 1
            flash(f"Announcement sent to {sent_count} customers.", "success")
            return redirect(url_for('admin_dashboard'))

        customer = Customer.query.filter(
            (Customer.email == customer_ref) | (Customer.cuid == customer_ref)
        ).first()
        if not customer:
            flash("Customer not found for provided email/CUID.", "danger")
            return redirect(url_for('admin_dashboard'))

        if send_announcement_email(customer.email, subject, message_html):
            flash(f"Message sent to {customer.name}.", "success")
        else:
            flash("Failed to send message. Check SMTP settings.", "danger")
        return redirect(url_for('admin_dashboard'))

    # admin change order status
    @app.route('/admin/order/<int:order_id>/status', methods=['POST'])
    @admin_required
    def admin_change_status(order_id):
        st = request.form.get('status')
        order = Order.query.get_or_404(order_id)
        if st in ['Received', 'Packed', 'Pending', 'Delivered/Pickup Ready']:
            order.status = st
            db.session.commit()
            # send status email to customer
            try:
                send_status_email(order)
            except Exception as e:
                print("error sending status email:", e)
            flash("Order status updated", "success")
        else:
            flash("Invalid status", "danger")
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/order/<int:order_id>/delete', methods=['POST'])
    @admin_required
    def admin_delete_order(order_id):
        order = Order.query.get_or_404(order_id)
        if order.uploaded_filename:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], order.uploaded_filename))
            except:
                pass
        db.session.delete(order)
        db.session.commit()
        flash("Order deleted", "info")
        return redirect(url_for('admin_dashboard'))

    @app.route("/admin/delete-customer/<int:customer_id>", methods=["POST"])
    @admin_required
    def delete_customer(customer_id):
        customer = Customer.query.get(customer_id)
        if not customer:
            flash("Customer not found!", "error")
            return redirect(url_for("admin_customers"))
        db.session.delete(customer)
        db.session.commit()
        flash("Customer deleted successfully!", "success")
        return redirect(url_for("admin_customers"))

    # billing page for admin
    @app.route('/admin/billing/<int:order_id>', methods=['GET','POST'])
    @admin_required
    def billing(order_id):
        order = Order.query.get_or_404(order_id)
        existing_bill = Bill.query.filter_by(order_id=order.order_id).first()
        if existing_bill:
            flash("Bill already exists for this order.", "info")
            return redirect(url_for('admin_dashboard'))
        if request.method == 'POST':
            names = request.form.getlist('item_name[]')
            qtys = request.form.getlist('item_qty[]')
            prices = request.form.getlist('item_price[]')
            items = []
            total = 0.0
            for n, q, p in zip(names, qtys, prices):
                try:
                    price_val = float(p)
                except:
                    price_val = 0.0
                items.append({"name": n, "qty": q, "price": price_val})
                total += price_val
            bill_id = generate_bill_id()
            admin = Admin.query.get(session['admin_id'])
            bill = Bill(bill_id=bill_id, order_id=order.order_id, admin_id=admin.id,
                        items_json=items_to_json(items), total_amount=total)
            # generate PDF now
            pdf_name = f"{bill_id}.pdf"
            pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_name)
            create_bill_pdf(app, bill, order, pdf_path)
            bill.pdf_filename = pdf_name
            db.session.add(bill)
            order.status = "Packed"
            db.session.commit()

            # send bill to customer via email (attachment)
            try:
                send_bill_email(bill)
            except Exception as e:
                print("Error sending bill email:", e)

            flash("Bill generated", "success")
            return redirect(url_for('admin_dashboard'))
        return render_template('billing.html', order=order)

    def create_bill_pdf(app, bill, order, pdf_path):
        customer = Customer.query.filter_by(id=order.customer_id).first()
        c = canvas.Canvas(pdf_path, pagesize=A4)
        width, height = A4
        # Header band
        c.setFillColorRGB(0.12, 0.44, 0.43)
        c.rect(35, height - 95, width - 70, 55, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, height - 65, "Sri Vinayaga Stores")
        c.setFont("Helvetica", 10)
        c.drawString(50, height - 80, "Pillaiyar Kuppam, Vellore - 09.")
        c.setFillColorRGB(0.12, 0.18, 0.24)

        c.setFont("Helvetica", 10)
        c.drawString(50, height - 112, f"Bill ID: {bill.bill_id}")
        c.drawString(50, height - 127, f"Order ID: {order.order_id}")
        c.drawString(50, height - 142, f"Date: {now_str()}")
        c.drawRightString(width - 50, height - 112, f"Pickup: {order.pickup_option}")
        c.drawRightString(width - 50, height - 127, f"Status: {order.status}")

        # Customer block
        c.setStrokeColorRGB(0.82, 0.87, 0.92)
        c.roundRect(45, height - 230, width - 90, 66, 6, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(55, height - 180, "Customer Details")
        c.setFont("Helvetica", 10)
        c.drawString(55, height - 195, f"Name: {customer.name if customer else ''}")
        c.drawString(55, height - 209, f"Mobile: {customer.mobile if customer else ''}")
        c.drawString(55, height - 223, f"Address: {customer.address if customer else ''}")

        # Items table
        y = height - 258
        c.setFillColorRGB(0.95, 0.97, 0.99)
        c.rect(45, y - 4, width - 90, 20, fill=1, stroke=0)
        c.setFillColorRGB(0.12, 0.18, 0.24)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(52, y + 2, "S.No")
        c.drawString(88, y + 2, "Item")
        c.drawString(360, y + 2, "Qty")
        c.drawRightString(width - 55, y + 2, "Price (Rs)")
        y -= 16
        items = items_from_json(bill.items_json)
        i = 1
        for it in items:
            c.setFont("Helvetica", 10)
            c.drawString(52, y, str(i))
            c.drawString(88, y, str(it.get('name', ''))[:45])
            c.drawString(360, y, str(it.get('qty', ''))[:15])
            c.drawRightString(width - 55, y, f"{it.get('price', 0):.2f}")
            y -= 14
            c.setStrokeColorRGB(0.91, 0.94, 0.97)
            c.line(45, y + 5, width - 45, y + 5)
            i += 1
            if y < 120:
                c.showPage()
                y = height - 85

        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(width - 180, y - 12, "Total Amount:")
        c.drawRightString(width - 55, y - 12, f"Rs {bill.total_amount:.2f}")
        # QR
        try:
            files = os.listdir(app.config['UPLOAD_FOLDER'])
            qr_candidates = [f for f in files if 'qr' in f.lower()]
            if qr_candidates:
                qr_path = os.path.join(app.config['UPLOAD_FOLDER'], qr_candidates[0])
                qr_size = 110
                c.setFont("Helvetica-Bold", 12)
                c.drawString(50, 170, "Scan & Pay")
                img = Image.open(qr_path)
                img_reader = ImageReader(img)
                c.drawImage(img_reader, 50, 40, width=qr_size, height=qr_size, preserveAspectRatio=True)
        except Exception:
            pass
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width / 2, 20, "Thanks for Ordering & Keep Purchasing - Sri Vinayaga Stores - Pillaiyar Kuppam, Vellore - 09.")
        c.save()

    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    @app.route('/favicon.ico')
    def favicon():
        upload_ico = os.path.join(app.config['UPLOAD_FOLDER'], 'favicon.ico')
        if os.path.exists(upload_ico):
            resp = send_from_directory(app.config['UPLOAD_FOLDER'], 'favicon.ico', mimetype='image/x-icon', max_age=0)
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            return resp
        static_ico = os.path.join('static', 'favicon.ico')
        if os.path.exists(static_ico):
            resp = send_from_directory('static', 'favicon.ico', mimetype='image/x-icon', max_age=0)
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            return resp
        upload_icon = os.path.join(app.config['UPLOAD_FOLDER'], 'icon-192.png')
        if os.path.exists(upload_icon):
            resp = send_from_directory(app.config['UPLOAD_FOLDER'], 'icon-192.png', mimetype='image/png', max_age=0)
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            return resp
        resp = send_from_directory('static/icons', 'icon-192.png', mimetype='image/png', max_age=0)
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp

    # ----- Customer signup/login/dashboard -----
    @app.route('/customer/signup', methods=['GET', 'POST'])
    def customer_signup():
        if request.method == 'POST':
            name = request.form.get('name')
            email = request.form.get('email')
            mobile = request.form.get('mobile')
            address = request.form.get('address')
            password = request.form.get('password')
            if not (name and email and mobile and password):
                flash("Please fill all required fields", "danger")
                return redirect(url_for('customer_signup'))
            if Customer.query.filter_by(email=email).first():
                flash("Email already exists", "danger")
                return redirect(url_for('customer_signup'))
            otp = str(random.randint(100000, 999999))
            session['customer_signup_data'] = {
                "name": name,
                "email": email,
                "mobile": mobile,
                "address": address,
                "password_hash": generate_password_hash(password),
            }
            session['customer_otp'] = otp
            if send_email_otp(email, otp):
                flash("OTP sent to your email!", "success")
                return redirect(url_for("customer_verify_otp"))
            flash("Failed to send OTP email. Please verify SMTP settings." + _email_error_hint(), "danger")
            return redirect(url_for('customer_signup'))
        return render_template("customer_signup.html")

    @app.route('/customer/verify-otp', methods=['GET', 'POST'])
    def customer_verify_otp():
        data = session.get('customer_signup_data')
        if not data:
            flash("Session expired. Please sign up again.", "danger")
            return redirect(url_for('customer_signup'))
        if request.method == 'POST':
            user_otp = request.form.get('otp')
            real_otp = session.get('customer_otp')
            if user_otp != real_otp:
                flash("Incorrect OTP! Please try again.", "danger")
                return redirect(url_for('customer_verify_otp'))
            # Create customer
            cuid = generate_cuid()
            new_customer = Customer(
                name=data["name"],
                email=data["email"],
                mobile=data["mobile"],
                address=data["address"],
                password_hash=data["password_hash"],
                cuid=cuid
            )
            db.session.add(new_customer)
            db.session.commit()
            log_activity("customer", new_customer.id, new_customer.name, "signup")
            # send welcome email
            try:
                send_welcome_email(new_customer)
            except Exception as e:
                print("welcome email failed:", e)
            session.pop("customer_signup_data")
            session.pop("customer_otp")
            flash(f"Signup successful! Your CUID: {cuid}", "success")
            return redirect(url_for("customer_login"))
        return render_template("customer_verify_otp.html")

    @app.route('/customer/resend-otp')
    def customer_resend_otp():
        data = session.get('customer_signup_data')
        if not data:
            flash("Session expired. Please sign up again.", "danger")
            return redirect(url_for('customer_signup'))
        new_otp = str(random.randint(100000, 999999))
        session['customer_otp'] = new_otp
        if send_email_otp(data["email"], new_otp):
            flash("A new OTP has been sent!", "success")
        else:
            flash("Failed to send OTP email. Please check SMTP server settings." + _email_error_hint(), "danger")
        return redirect(url_for('customer_verify_otp'))

    @app.route('/customer/login', methods=['GET','POST'])
    def customer_login():
        key_id = "customer_login"
        if not check_rate_limit(key_id):
            flash("Too many failed login attempts! Try again after 5 minutes.", "danger")
            return render_template('customer_login.html')
        if request.method == 'POST':
            identifier = request.form.get('identifier')
            password = request.form.get('password')
            cust = Customer.query.filter((Customer.email == identifier) | (Customer.cuid == identifier)).first()
            if cust and check_password_hash(cust.password_hash, password):
                attempts[key_id] = {"count": 0, "block_until": None}
                session.clear()
                session['role'] = 'customer'
                session['customer_id'] = cust.id
                session['customer_name'] = cust.name
                log_activity("customer", cust.id, cust.name, "login")
                flash("Customer logged in", "success")
                return redirect(url_for('customer_dashboard'))
            record_failed_attempt(key_id)
            flash("Invalid credentials!", "danger")
            return render_template('customer_login.html')
        return render_template('customer_login.html')

    @app.route('/customer/logout')
    def customer_logout():
        if session.get('role') == 'customer':
            log_activity("customer", session.get('customer_id'), session.get('customer_name'), "logout")
        session.clear()
        flash("Logged out", "info")
        return redirect(url_for('home'))

    @app.route('/customer/dashboard', methods=['GET','POST'])
    @customer_required
    def customer_dashboard():
        customer = Customer.query.get(session['customer_id'])
        if request.method == 'POST':
            raw_text = request.form.get('order_text')
            pickup = request.form.get('pickup_option') or 'Self Pick'
            f = request.files.get('order_file')
            filename = None
            if f and allowed_file(f.filename):
                filename = secure_filename(f.filename)
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            if (not raw_text) and (not filename):
                flash("Enter items or upload file", "danger")
                return redirect(url_for('customer_dashboard'))
            order_id = generate_order_id()
            order = Order(order_id=order_id, customer_id=customer.id,
                          raw_text=raw_text, uploaded_filename=filename, pickup_option=pickup)
            db.session.add(order)
            db.session.commit()
            log_activity("customer", customer.id, customer.name, f"placed_order:{order_id}")

            # send order to store
            try:
                send_order_to_store(order, customer)
            except Exception as e:
                print("error sending order to store:", e)

            flash(f"Order placed. Order ID: {order_id}", "success")
            return redirect(url_for('customer_dashboard'))

        # Smart reminder: send once per day if customer has not ordered in configured days
        reminder_days = int(os.getenv("REMINDER_DAYS", "7"))
        last_order = Order.query.filter_by(customer_id=customer.id).order_by(Order.created_at.desc()).first()
        if last_order:
            days_without_order = (datetime.utcnow() - last_order.created_at).days
            if days_without_order >= reminder_days:
                today = datetime.utcnow().date()
                existing_reminder = ActivityLog.query.filter(
                    ActivityLog.actor_role == "customer",
                    ActivityLog.actor_id == customer.id,
                    ActivityLog.action.like("reminder_sent:%"),
                    ActivityLog.created_at >= datetime.combine(today, datetime.min.time())
                ).first()
                if not existing_reminder:
                    try:
                        if customer.email and send_reorder_reminder_email(customer, days_without_order):
                            log_activity("customer", customer.id, customer.name, f"reminder_sent:{days_without_order}")
                    except Exception as e:
                        print("reminder email error:", e)

        orders = Order.query.filter_by(customer_id=customer.id).order_by(Order.created_at.desc()).all()
        bills = {}
        for o in orders:
            b = Bill.query.filter_by(order_id=o.order_id).first()
            if b:
                bills[o.order_id] = b
        favorites = FavoriteItem.query.filter_by(customer_id=customer.id).order_by(FavoriteItem.created_at.desc()).all()
        deals = [
            "Weekend Combo: Rice + Dal at special price",
            "Buy 2 soaps and get detergent discount",
            "Fresh vegetables restocked every morning",
            "Tea & Coffee combo offer this week",
            "Free delivery for large orders"
        ]
        prefill_order_text = session.pop("prefill_order_text", "")
        return render_template(
            'customer_dashboard.html',
            customer=customer,
            orders=orders,
            bills=bills,
            favorites=favorites,
            deals=deals,
            prefill_order_text=prefill_order_text
        )

    @app.route('/customer/order/<int:order_pk>/reorder', methods=['POST'])
    @customer_required
    def customer_reorder(order_pk):
        customer = Customer.query.get(session['customer_id'])
        old_order = Order.query.get_or_404(order_pk)
        if old_order.customer_id != customer.id:
            abort(403)
        if not (old_order.raw_text or old_order.uploaded_filename):
            flash("Cannot reorder an empty order.", "danger")
            return redirect(url_for('customer_dashboard'))
        new_order_id = generate_order_id()
        new_order = Order(
            order_id=new_order_id,
            customer_id=customer.id,
            raw_text=old_order.raw_text,
            uploaded_filename=None,
            pickup_option=old_order.pickup_option,
            status="Pending"
        )
        db.session.add(new_order)
        db.session.commit()
        try:
            send_order_to_store(new_order, customer)
        except Exception as e:
            print("error sending reorder to store:", e)
        log_activity("customer", customer.id, customer.name, f"reorder:{new_order_id}")
        flash(f"Reorder placed successfully. New Order ID: {new_order_id}", "success")
        return redirect(url_for('customer_dashboard'))

    @app.route('/customer/favorites/add', methods=['POST'])
    @customer_required
    def customer_add_favorite():
        customer = Customer.query.get(session['customer_id'])
        item_text = (request.form.get('item_text') or "").strip()
        if not item_text:
            flash("Favorite item text is required.", "danger")
            return redirect(url_for('customer_dashboard'))
        exists = FavoriteItem.query.filter_by(customer_id=customer.id, item_text=item_text).first()
        if exists:
            flash("Item already exists in favorites.", "info")
            return redirect(url_for('customer_dashboard'))
        fav = FavoriteItem(customer_id=customer.id, item_text=item_text[:300])
        db.session.add(fav)
        db.session.commit()
        log_activity("customer", customer.id, customer.name, "favorite_add")
        flash("Added to favorites.", "success")
        return redirect(url_for('customer_dashboard'))

    @app.route('/customer/favorites/<int:fav_id>/delete', methods=['POST'])
    @customer_required
    def customer_delete_favorite(fav_id):
        customer = Customer.query.get(session['customer_id'])
        fav = FavoriteItem.query.get_or_404(fav_id)
        if fav.customer_id != customer.id:
            abort(403)
        db.session.delete(fav)
        db.session.commit()
        log_activity("customer", customer.id, customer.name, "favorite_delete")
        flash("Favorite removed.", "info")
        return redirect(url_for('customer_dashboard'))

    @app.route('/customer/favorites/<int:fav_id>/use', methods=['POST'])
    @customer_required
    def customer_use_favorite(fav_id):
        customer = Customer.query.get(session['customer_id'])
        fav = FavoriteItem.query.get_or_404(fav_id)
        if fav.customer_id != customer.id:
            abort(403)
        session["prefill_order_text"] = fav.item_text
        return redirect(url_for('customer_dashboard'))

    @app.route('/customer/update', methods=['GET', 'POST'])
    @customer_required
    def customer_update():
        customer = Customer.query.get(session['customer_id'])
        if request.method == 'POST':
            name = request.form.get('name')
            email = request.form.get('email')
            mobile = request.form.get('mobile')
            address = request.form.get('address')
            existing = Customer.query.filter_by(email=email).first()
            if existing and existing.id != customer.id:
                flash("Email already taken", "danger")
                return redirect(url_for('customer_update'))
            customer.name = name
            customer.email = email
            customer.mobile = mobile
            customer.address = address
            db.session.commit()
            log_activity("customer", customer.id, customer.name, "profile_update")
            session['customer_name'] = name
            flash("Profile updated successfully", "success")
            return redirect(url_for('customer_dashboard'))
        return render_template('customer_update.html', customer=customer)

    @app.route('/customer/delete', methods=['POST'])
    @customer_required
    def customer_delete():
        customer = Customer.query.get(session['customer_id'])
        customer_id = customer.id
        customer_name = customer.name
        orders = Order.query.filter_by(customer_id=customer.id).all()
        for o in orders:
            if o.uploaded_filename:
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], o.uploaded_filename))
                except:
                    pass
            db.session.delete(o)
        db.session.delete(customer)
        db.session.commit()
        log_activity("customer", customer_id, customer_name, "account_delete")
        session.clear()
        flash("Your account has been permanently deleted.", "info")
        return redirect(url_for('home'))

    @app.route("/customer/forgot-password", methods=["GET", "POST"])
    def customer_forgot_password():
        if request.method == "POST":
            email = request.form["email"]
            new_password = request.form["new_password"]
            confirm_password = request.form["confirm_password"]
            if new_password != confirm_password:
                flash("Passwords do not match!", "error")
                return redirect(url_for("customer_forgot_password"))
            customer = Customer.query.filter_by(email=email).first()
            if not customer:
                flash("Email not registered!", "error")
                return redirect(url_for("customer_forgot_password"))
            customer.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash("Password updated successfully!", "success")
            return redirect(url_for("customer_login"))
        return render_template("customer_forgot_password.html")

    @app.route('/customer/order/<int:order_pk>/delete', methods=['POST'])
    @customer_required
    def customer_delete_order(order_pk):
        customer = Customer.query.get(session['customer_id'])
        order = Order.query.get_or_404(order_pk)
        if order.customer_id != customer.id:
            abort(403)
        if order.uploaded_filename:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], order.uploaded_filename))
            except:
                pass
        db.session.delete(order)
        db.session.commit()
        log_activity("customer", customer.id, customer.name, f"delete_order:{order.order_id}")
        flash("Order deleted", "info")
        return redirect(url_for('customer_dashboard'))

    @app.route('/bill/download/<bill_id>')
    def download_bill(bill_id):
        bill = Bill.query.filter_by(bill_id=bill_id).first_or_404()
        if not bill.pdf_filename:
            abort(404)
        return send_from_directory(app.config['UPLOAD_FOLDER'], bill.pdf_filename, as_attachment=True)

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template('404.html'), 404

    return app

# ---------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------
if __name__ == '__main__':
    app = create_app()
    app.run(debug=os.getenv("FLASK_DEBUG", "False") == "True", port=int(os.getenv("PORT", 5000)))
