import os
import cv2
import numpy as np
import face_recognition
import pandas as pd
import pytz
import base64
import io
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)

# --- CONFIGURATIONS ---
app.secret_key = 'StudentsSolutionSecretKey@2024'
# Database Setup
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- TIMEZONE HELPER (Pakistan Time) ---
def get_pkt_time():
    tz = pytz.timezone('Asia/Karachi')
    return datetime.now(tz)

# --- DATABASE MODELS ---
class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100))
    encoding = db.Column(db.PickleType, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    timestamp = db.Column(db.DateTime, default=get_pkt_time)
    status = db.Column(db.String(20), default='Present')
    employee = db.relationship('Employee', backref='attendance_records')

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(50))

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_scan', methods=['POST'])
def process_scan():
    data = request.json
    image_data = data['image']
    encoded_data = image_data.split(',')[1]
    nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_img)
    face_encodings = face_recognition.face_encodings(rgb_img, face_locations)

    if not face_encodings:
        return {"status": "error", "message": "No face detected!"}

    unknown_encoding = face_encodings[0]
    employees = Employee.query.filter_by(is_active=True).all()
    
    for emp in employees:
        match = face_recognition.compare_faces([emp.encoding], unknown_encoding, tolerance=0.5)
        if match[0]:
            # Mark Attendance
            new_entry = Attendance(employee_id=emp.id, timestamp=get_pkt_time())
            db.session.add(new_entry)
            db.session.commit()
            return {"status": "success", "message": f"Marked: {emp.name} at {get_pkt_time().strftime('%H:%M')}"}
            
    return {"status": "error", "message": "Employee not found."}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = Admin.query.filter_by(username=username).first()
        if user and user.password == password:
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials', 'error')
    return render_template('login.html')

# --- LOGOUT ROUTE (NEW) ---
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

# --- DASHBOARD (UPDATED LOGIC) ---
@app.route('/dashboard')
@login_required
def dashboard():
    employees = Employee.query.filter_by(is_active=True).all()
    
    # Logic for In/Out Time
    today = get_pkt_time().date()
    attendance_summary = []
    
    for emp in employees:
        scans = Attendance.query.filter(
            Attendance.employee_id == emp.id,
            func.date(Attendance.timestamp) == today
        ).order_by(Attendance.timestamp).all()
        
        if scans:
            in_time = scans[0].timestamp.strftime('%H:%M:%S')
            out_time = scans[-1].timestamp.strftime('%H:%M:%S') if len(scans) > 1 else "--"
            status = "Present"
        else:
            in_time = "--"
            out_time = "--"
            status = "Absent"
            
        attendance_summary.append({
            'name': emp.name,
            'department': emp.department,
            'in_time': in_time,
            'out_time': out_time,
            'status': status,
            'id': emp.id
        })

    return render_template('admin.html', summary=attendance_summary)

@app.route('/delete_employee/<int:id>')
@login_required
def delete_employee(id):
    emp = Employee.query.get(id)
    if emp:
        emp.is_active = False
        db.session.commit()
        flash(f'{emp.name} removed.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/download_report')
@login_required
def download_report():
    records = Attendance.query.all()
    data = []
    for r in records:
        data.append({
            "ID": r.employee_id,
            "Name": r.employee.name,
            "Timestamp": r.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            "Department": r.employee.department
        })
    df = pd.DataFrame(data)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    return Response(csv_buffer.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=attendance_report.csv"})

def create_app():
    with app.app_context():
        db.create_all()
        if not Admin.query.filter_by(username='admin').first():
            db.session.add(Admin(username='admin', password='admin123'))
            db.session.commit()
            print("Admin Created: admin / admin123")

if __name__ == '__main__':
    create_app()
    app.run(debug=True)