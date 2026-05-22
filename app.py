from flask import Flask, render_template, request, session, redirect, url_for, flash,jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from config import Database
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from collections import defaultdict
import base64
from crypting import NoKeyEncryptor
import google.generativeai as genai

import smtplib
import random
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import jsonify





app = Flask(__name__)
app.secret_key = 'mytestkey123'
db = Database()
crypto = NoKeyEncryptor()

UPLOAD_FOLDER = 'staticvuploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Initialize database schema - ensure rejection_reason column exists
def init_db_schema():
    """Ensure the appointments table has the rejection_reason column and create hearing_status_updates table"""
    try:
        db_conn = db.connect()
        cursor = db_conn.cursor()
        
        # Check if rejection_reason column exists
        cursor.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME='appointments' AND COLUMN_NAME='rejection_reason'
        """)
        
        if not cursor.fetchone():
            # Column doesn't exist, create it
            cursor.execute("""
                ALTER TABLE appointments 
                ADD COLUMN rejection_reason LONGTEXT NULL DEFAULT NULL
            """)
            db_conn.commit()
            print("✅ Added rejection_reason column to appointments table")
        
        # Check if hearing_status_updates table exists
        cursor.execute("""
            SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_NAME='hearing_status_updates'
        """)
        
        if not cursor.fetchone():
            # Table doesn't exist, create it
            cursor.execute("""
                CREATE TABLE hearing_status_updates (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    appointment_id INT NOT NULL,
                    lawyer_id INT NOT NULL,
                    requested_status VARCHAR(100) NOT NULL,
                    client_id VARCHAR(50) NOT NULL,
                    status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
                    rejection_reason LONGTEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (appointment_id) REFERENCES appointments(id)
                )
            """)
            db_conn.commit()
            print("✅ Created hearing_status_updates table")
        
        cursor.close()
        db_conn.close()
    except Exception as e:
        print(f"⚠️ Warning: Could not initialize database schema: {e}")

# Run initialization on app startup
init_db_schema()


# ================Login required decorator===========================
def login_required(role=None):
    def decorator(f):
        def decorated_function(*args, **kwargs):
            if 'login_id' not in session:
                flash('Please log in first.')
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('Access denied.')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator

#======================LANDING PAGE==============================
@app.route('/')
def index():
    return render_template('guest/landing.html')

#=============================USER DASHBOARD=========================

#---------------------------dashboard starts-------------------

@app.route('/user/dashboard')
def user_dashboard():
    login_id = session['login_id']
    if 'login_id' not in session:
        flash('Please login to continue.', 'warning')
        return redirect(url_for('login'))

    

    # Fetch stats for dashboard
    
    total_crime = db.fetchone("SELECT COUNT(*) AS cnt FROM crimes WHERE login_id=%s", (login_id,))
    crime_count = total_crime['cnt']

    total_missing = db.fetchone("SELECT COUNT(*) AS cnt FROM missing_persons WHERE login_id=%s", (login_id,))
    missing_count = total_missing['cnt']

    total_stolen = db.fetchone("SELECT COUNT(*) AS cnt FROM stolen_property WHERE login_id=%s", (login_id,))
    stolen_count = total_stolen['cnt']

    total_reports = crime_count + missing_count + stolen_count

    # Prevent NoneType
    stats = {
        
        "total_crime": total_crime['cnt'] if total_crime else 0,
        "total_missing": total_missing['cnt'] if total_missing else 0,
        "total_stolen": total_stolen['cnt'] if total_stolen else 0
    }
    closed_crime = db.fetchone("SELECT COUNT(*) AS cnt FROM crimes WHERE login_id=%s AND status='closed'", (login_id,))
    closed_crime_count = closed_crime['cnt']

    closed_missing = db.fetchone("SELECT COUNT(*) AS cnt FROM missing_persons WHERE login_id=%s AND status='closed'", (login_id,))
    closed_missing_count = closed_missing['cnt']

    closed_stolen = db.fetchone("SELECT COUNT(*) AS cnt FROM stolen_property WHERE login_id=%s AND status='closed'", (login_id,))
    closed_stolen_count = closed_stolen['cnt']

    total_closed = closed_crime_count + closed_missing_count + closed_stolen_count

       

    return render_template('user/dashboard.html', stats=stats,
                            crime_count=crime_count,
                            missing_count=missing_count,
                            stolen_count=stolen_count,
                            total_reports=total_reports,
                            closed_crime_count=closed_crime_count,
                            closed_missing_count=closed_missing_count,
                            closed_stolen_count=closed_stolen_count,
                            total_closed=total_closed)
    #    return render_template('user/dashboard.html')
#---------------------------dashboard ends-------------------------


# Configuration
app.config['CRIME_UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'crime')
os.makedirs(app.config['CRIME_UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}

def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

#---------------------- REGISTER/UPDATE CRIME ---------------------------
@app.route('/user/report_crime', methods=['GET', 'POST'])
def report_crime():
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in to report a crime.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        crime_id = request.form.get('crime_id')
        crime_type = request.form.get('crime_type')
        other_crime = request.form.get('other_crime_type')

        # Handle "Other" crime type
        if crime_type == "Other" and other_crime:
            crime_type = other_crime
            
        crime_date = request.form.get('crime_date')
        location = request.form.get('location')
        latitude = request.form.get("latitude")
        longitude = request.form.get("longitude")
        crimespot = request.form.get('crimespot')
        description = request.form.get('description')
        # status = request.form.get('status')
        status = request.form.get('status') or 'reported'

        reporter_name = request.form.get('reporter_name') or None
        reporter_contact = request.form.get('reporter_contact') or None
        witnesses = request.form.get('witnesses') or None
        suspects = request.form.get('suspects') or None

        # -----------------------------
        # 1️⃣ Insert or Update Crime
        # -----------------------------
        if crime_id:  # UPDATE existing record
            update_query = """
                UPDATE crimes
                SET crime_type=%s, crime_date=%s, location=%s, latitude=%s, longitude=%s, crimespot=%s,
                    description=%s, status=%s,
                    reporter_name=%s, reporter_contact=%s,
                    witnesses=%s, suspects=%s
                WHERE id=%s AND login_id=%s
            """
            db.execute(update_query, (
                crime_type, crime_date, location, latitude, longitude, crimespot,
                description, status, reporter_name, reporter_contact,
                witnesses, suspects, crime_id, login_id
            ))
            current_crime_id = int(crime_id)
            flash("✅ Crime report updated successfully!", "success")

        else:  # INSERT new record
            insert_query = """
                INSERT INTO crimes 
                (crime_type, crime_date, location, latitude, longitude, crimespot, description, status, 
                 reporter_name, reporter_contact, witnesses, suspects, login_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            current_crime_id = db.executeAndReturnId(insert_query, (
                crime_type, crime_date, location, latitude, longitude, crimespot, description, status,
                reporter_name, reporter_contact, witnesses, suspects, login_id
            ))

            if not current_crime_id:
                flash("❌ Error inserting crime record — please try again.", "danger")
                return redirect(url_for('report_crime'))

            flash("✅ Crime report submitted successfully!", "success")

        # -----------------------------
        # 2️⃣ Handle Multiple Evidence Uploads (Images & Videos)
        # -----------------------------
        evidence_files = request.files.getlist('evidence[]')
        
        # Local allowed extensions for crime reporting to avoid conflicts with global variables
        ALLOWED_CRIME_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}
        VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}

        if evidence_files:
            for file in evidence_files:
                if file and file.filename:
                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                    
                    if ext not in ALLOWED_CRIME_EXTENSIONS:
                        continue

                    # Check video size limit (15MB)
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    file.seek(0) # IMPORTANT: Reset file pointer to beginning
                    
                    if ext in VIDEO_EXTENSIONS and file_size > 15 * 1024 * 1024:
                        flash(f"⚠️ Video '{file.filename}' exceeds 15MB limit and was not uploaded.", "warning")
                        continue

                    # Generate unique filename with timestamp
                    original_filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                    filename = f"{timestamp}_{original_filename}"

                    # Save file to folder
                    save_path = os.path.join(app.config['CRIME_UPLOAD_FOLDER'], filename)
                    file.save(save_path)
                    
                    # Encrypt filename before storing in database
                    encrypted_filename = crypto.encrypt(filename)

                    # Save each file reference into database
                    db.execute("""
                        INSERT INTO evidence (evidence_type, reference_id, file_path, uploaded_by, uploaded_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, ('crime', current_crime_id, encrypted_filename, login_id))
                    
            if any(file and file.filename for file in evidence_files):
                flash("✅ Evidence uploaded successfully!", "success")

        return redirect(url_for('report_crime'))

    # -----------------------------
    # 3️⃣ GET: Display All Crimes with Evidence
    # -----------------------------
    crimes = db.fetchall("""
        SELECT * FROM crimes WHERE login_id = %s ORDER BY created_at DESC
    """, (login_id,))
    
    # Fetch evidences for crimes
    evidences = db.fetchall("""
        SELECT reference_id, file_path 
        FROM evidence 
        WHERE evidence_type = 'crime'
    """)
    
    # Decrypt evidences
    decrypted_evidences = []
    for e in evidences:
        try:
            decrypted_path = crypto.decrypt(e['file_path'])
            decrypted_evidences.append({
                'reference_id': e['reference_id'],
                'file_path': decrypted_path
            })
        except Exception as err:
            print(f"⚠️ Error decrypting evidence: {err}")
            continue

    # Attach decrypted evidences to crimes
    for crime in crimes:
        crime['evidences'] = [
            e['file_path']
            for e in decrypted_evidences
            if e['reference_id'] == crime['id']
        ]
    
    return render_template('user/crime_register.html', crimes=crimes)


# --------------------------------------------------------------
# DELETE CRIME (AND EVIDENCE)
# --------------------------------------------------------------
@app.route('/user/delete_crime/<int:crime_id>', methods=['POST'])
def delete_crime(crime_id):
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in first.", "danger")
        return redirect(url_for('login'))

    # 1️⃣ Fetch encrypted evidence paths
    evidences = db.fetchall("""
        SELECT file_path FROM evidence 
        WHERE evidence_type='crime' AND reference_id=%s
    """, (crime_id,))

    # 2️⃣ Delete files from disk
    for e in evidences:
        try:
            # Decrypt the filename first
            decrypted_filename = crypto.decrypt(e['file_path'])
            file_path = os.path.join(app.config['CRIME_UPLOAD_FOLDER'], decrypted_filename)

            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"✅ Deleted file: {decrypted_filename}")
        except Exception as err:
            print(f"⚠️ Could not remove file: {err}")

    # 3️⃣ Delete DB records
    db.execute("DELETE FROM evidence WHERE evidence_type='crime' AND reference_id=%s", (crime_id,))
    db.execute("DELETE FROM crimes WHERE id=%s AND login_id=%s", (crime_id, login_id))

    flash("🗑️ Crime record and related evidences deleted successfully!", "success")
    return redirect(url_for('report_crime'))


# --------------------------------------------------------------
# DELETE INDIVIDUAL EVIDENCE (OPTIONAL - for future use)
# --------------------------------------------------------------
@app.route('/user/delete_evidence/<int:evidence_id>', methods=['POST'])
def delete_evidence(evidence_id):
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in first.", "danger")
        return redirect(url_for('login'))

    # Fetch the evidence
    evidence = db.fetchone("""
        SELECT e.file_path, c.login_id 
        FROM evidence e
        JOIN crimes c ON e.reference_id = c.id
        WHERE e.id = %s AND e.evidence_type = 'crime'
    """, (evidence_id,))

    if not evidence:
        flash("Evidence not found.", "danger")
        return redirect(url_for('report_crime'))

    # Check ownership
    if evidence['login_id'] != login_id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for('report_crime'))

    try:
        # Decrypt and delete file
        decrypted_filename = crypto.decrypt(evidence['file_path'])
        file_path = os.path.join(app.config['CRIME_UPLOAD_FOLDER'], decrypted_filename)
        
        if os.path.exists(file_path):
            os.remove(file_path)

        # Delete from database
        db.execute("DELETE FROM evidence WHERE id=%s", (evidence_id,))
        flash("Evidence deleted successfully!", "success")
        
    except Exception as err:
        print(f"Error deleting evidence: {err}")
        flash("Error deleting evidence.", "danger")

    return redirect(url_for('report_crime'))

#----------------------------------- REGISTER CRIME END -----------------------------------



# Configuration
app.config['MISSING_UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'missing')
os.makedirs(app.config['MISSING_UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}

def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

#---------------------------------- MISSING PERSON START -------------------------------------

@app.route('/user/missing_persons', methods=['GET', 'POST'])
def missing_persons():
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in to continue.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        person_id = request.form.get('person_id')
        name = request.form.get('name')
        gender = request.form.get('gender')
        age = request.form.get('age')
        height = request.form.get('height')
        weight = request.form.get('weight')
        skintone = request.form.get('skintone')
        hair = request.form.get('hair')
        last_seen = request.form.get('last_seen')
        location = request.form.get('location')
        description = request.form.get('description') or None
        # status = request.form.get('status')
        status = request.form.get('status') or 'reported'


        # --------------------------
        # 1️⃣ Insert or Update person
        # --------------------------
        if person_id:  # UPDATE existing record
            db.execute("""
                UPDATE missing_persons
                SET name=%s, gender=%s, age=%s, height=%s, weight=%s, skintone=%s,
                    hair=%s, last_seen=%s, location=%s, description=%s, status=%s
                WHERE id=%s AND login_id=%s
            """, (name, gender, age, height, weight, skintone, hair,
                  last_seen, location, description, status, person_id, login_id))
            current_person_id = int(person_id)
            flash("✅ Missing person updated successfully!", "success")

        else:  # INSERT new record
            current_person_id = db.executeAndReturnId("""
                INSERT INTO missing_persons
                (name, gender, age, height, weight, skintone, hair, last_seen,
                 location, description, status, login_id, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            """, (name, gender, age, height, weight, skintone, hair,
                  last_seen, location, description, status, login_id))
            
            if not current_person_id:
                flash("❌ Error inserting missing person record — please try again.", "danger")
                return redirect(url_for('missing_persons'))
                
            flash("✅ Missing person registered successfully!", "success")

        # --------------------------
        # 2️⃣ Handle Multiple Evidence Uploads (Images & Videos)
        # --------------------------
        evidence_files = request.files.getlist('evidence[]')
        
        # Local allowed extensions for missing persons to avoid conflicts
        ALLOWED_MISSING_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}
        VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}

        if evidence_files:
            for file in evidence_files:
                if file and file.filename:
                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                    
                    if ext not in ALLOWED_MISSING_EXTENSIONS:
                        continue

                    # Check video size limit (15MB)
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    file.seek(0) # IMPORTANT: Reset file pointer to beginning
                    
                    if ext in VIDEO_EXTENSIONS and file_size > 15 * 1024 * 1024:
                        flash(f"⚠️ Video '{file.filename}' exceeds 15MB limit and was not uploaded.", "warning")
                        continue

                    # Generate unique filename with timestamp
                    original_filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                    filename = f"{timestamp}_{original_filename}"

                    # Save file to folder
                    save_path = os.path.join(app.config['MISSING_UPLOAD_FOLDER'], filename)
                    file.save(save_path)
                    
                    # Encrypt filename before storing in database
                    encrypted_filename = crypto.encrypt(filename)

                    # Save each file reference into database
                    db.execute("""
                        INSERT INTO evidence (evidence_type, reference_id, file_path, uploaded_by, uploaded_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, ('missing_person', current_person_id, encrypted_filename, login_id))
                    
            if any(file and file.filename for file in evidence_files):
                flash("✅ Evidence uploaded successfully!", "success")

        return redirect(url_for('missing_persons'))

    # --------------------------
    # 3️⃣ GET: Fetch persons + evidence
    # --------------------------
    persons = db.fetchall("""
        SELECT * FROM missing_persons 
        WHERE login_id=%s 
        ORDER BY last_seen DESC
    """, (login_id,))
    
    # Fetch evidences for missing persons
    evidences = db.fetchall("""
        SELECT reference_id, file_path 
        FROM evidence 
        WHERE evidence_type='missing_person'
    """)
    
    # Decrypt evidences
    decrypted_evidences = []
    for e in evidences:
        try:
            decrypted_path = crypto.decrypt(e['file_path'])
            decrypted_evidences.append({
                'reference_id': e['reference_id'],
                'file_path': decrypted_path
            })
        except Exception as err:
            print(f"⚠️ Error decrypting evidence: {err}")
            continue

    # Attach decrypted evidences to persons
    for p in persons:
        p['evidences'] = [
            e['file_path'] 
            for e in decrypted_evidences 
            if e['reference_id'] == p['id']
        ]

    return render_template('user/missing_persons.html', persons=persons)


# --------------------------------------------------------------
# DELETE MISSING PERSON + EVIDENCES
# --------------------------------------------------------------
@app.route('/user/delete_missing_person/<int:person_id>', methods=['POST'])
def delete_missing_person(person_id):
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in first.", "danger")
        return redirect(url_for('login'))

    # 1️⃣ Fetch encrypted evidence paths
    evidences = db.fetchall("""
        SELECT file_path FROM evidence 
        WHERE evidence_type='missing_person' AND reference_id=%s
    """, (person_id,))

    # 2️⃣ Delete files from disk
    for e in evidences:
        try:
            # Decrypt the filename first
            decrypted_filename = crypto.decrypt(e['file_path'])
            file_path = os.path.join(app.config['MISSING_UPLOAD_FOLDER'], decrypted_filename)

            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"✅ Deleted file: {decrypted_filename}")
        except Exception as err:
            print(f"⚠️ Could not remove file: {err}")

    # 3️⃣ Delete DB records
    db.execute("DELETE FROM evidence WHERE evidence_type='missing_person' AND reference_id=%s", (person_id,))
    db.execute("DELETE FROM missing_persons WHERE id=%s AND login_id=%s", (person_id, login_id))

    flash("🗑️ Missing person record and related evidences deleted successfully!", "success")
    return redirect(url_for('missing_persons'))


# --------------------------------------------------------------
# DELETE INDIVIDUAL EVIDENCE (OPTIONAL - for future use)
# --------------------------------------------------------------
@app.route('/user/delete_missing_evidence/<int:evidence_id>', methods=['POST'])
def delete_missing_evidence(evidence_id):
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in first.", "danger")
        return redirect(url_for('login'))

    # Fetch the evidence
    evidence = db.fetchone("""
        SELECT e.file_path, mp.login_id 
        FROM evidence e
        JOIN missing_persons mp ON e.reference_id = mp.id
        WHERE e.id = %s AND e.evidence_type = 'missing_person'
    """, (evidence_id,))

    if not evidence:
        flash("Evidence not found.", "danger")
        return redirect(url_for('missing_persons'))

    # Check ownership
    if evidence['login_id'] != login_id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for('missing_persons'))

    try:
        # Decrypt and delete file
        decrypted_filename = crypto.decrypt(evidence['file_path'])
        file_path = os.path.join(app.config['MISSING_UPLOAD_FOLDER'], decrypted_filename)
        
        if os.path.exists(file_path):
            os.remove(file_path)

        # Delete from database
        db.execute("DELETE FROM evidence WHERE id=%s", (evidence_id,))
        flash("Evidence deleted successfully!", "success")
        
    except Exception as err:
        print(f"Error deleting evidence: {err}")
        flash("Error deleting evidence.", "danger")

    return redirect(url_for('missing_persons'))

#------------------------------------- MISSING PERSON END -------------------------------------------


# Configuration
app.config['STOLEN_UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'stolen')
os.makedirs(app.config['STOLEN_UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}

def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

#--------------------------------------- STOLEN PROPERTY START ----------------------------------------------

@app.route('/user/stolen_property', methods=['GET', 'POST'])
def stolen_property():
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in to report a stolen property.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        prop_id = request.form.get('prop_id')
        item_name = request.form.get('item_name')
        category = request.form.get('category')
        serial_number = request.form.get('serial_number') or None
        date_stolen = request.form.get('date_stolen')
        location = request.form.get('location')
        estimated_value = request.form.get('estimated_value') or None
        owner_contact = request.form.get('owner_contact')
        description = request.form.get('description') or None
        status = request.form.get('status') or 'reported'

        # --------------------------
        # 1️⃣ Insert or Update Property
        # --------------------------
        if prop_id:  # UPDATE existing record
            db.execute("""
                UPDATE stolen_property
                SET item_name=%s, category=%s, serial_number=%s, date_stolen=%s,
                    location=%s, estimated_value=%s, owner_contact=%s, description=%s, status=%s
                WHERE id=%s AND login_id=%s
            """, (item_name, category, serial_number, date_stolen, location,
                  estimated_value, owner_contact, description, status, prop_id, login_id))
            current_prop_id = int(prop_id)
            flash("✅ Stolen property updated successfully!", "success")

        else:  # INSERT new record
            current_prop_id = db.executeAndReturnId("""
                INSERT INTO stolen_property
                (item_name, category, serial_number, date_stolen, location,
                 estimated_value, owner_contact, description, status, login_id, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            """, (item_name, category, serial_number, date_stolen, location,
                  estimated_value, owner_contact, description, status, login_id))
            
            if not current_prop_id:
                flash("❌ Error inserting stolen property record — please try again.", "danger")
                return redirect(url_for('stolen_property'))
                
            flash("✅ Stolen property registered successfully!", "success")

        # --------------------------
        # 2️⃣ Handle Multiple Evidence Uploads (Images & Videos)
        # --------------------------
        evidence_files = request.files.getlist('evidence[]')
        
        # Local allowed extensions for stolen property to avoid conflicts
        ALLOWED_STOLEN_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}
        VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}

        if evidence_files:
            for file in evidence_files:
                if file and file.filename:
                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                    
                    if ext not in ALLOWED_STOLEN_EXTENSIONS:
                        continue

                    # Check video size limit (15MB)
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    file.seek(0) # IMPORTANT: Reset file pointer to beginning
                    
                    if ext in VIDEO_EXTENSIONS and file_size > 15 * 1024 * 1024:
                        flash(f"⚠️ Video '{file.filename}' exceeds 15MB limit and was not uploaded.", "warning")
                        continue

                    # Generate unique filename with timestamp
                    original_filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                    filename = f"{timestamp}_{original_filename}"

                    # Save file to folder
                    save_path = os.path.join(app.config['STOLEN_UPLOAD_FOLDER'], filename)
                    file.save(save_path)
                    
                    # Encrypt filename before storing in database
                    encrypted_filename = crypto.encrypt(filename)

                    # Save each file reference into database
                    db.execute("""
                        INSERT INTO evidence (evidence_type, reference_id, file_path, uploaded_by, uploaded_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, ('stolen_property', current_prop_id, encrypted_filename, login_id))
                    
            if any(file and file.filename for file in evidence_files):
                flash("✅ Evidence uploaded successfully!", "success")

        return redirect(url_for('stolen_property'))

    # --------------------------
    # 3️⃣ GET: Fetch properties + evidence
    # --------------------------
    properties = db.fetchall("""
        SELECT * FROM stolen_property 
        WHERE login_id=%s 
        ORDER BY date_stolen DESC
    """, (login_id,))
    
    # Fetch evidences for stolen properties
    evidences = db.fetchall("""
        SELECT reference_id, file_path 
        FROM evidence 
        WHERE evidence_type='stolen_property'
    """)
    
    # Decrypt evidences
    decrypted_evidences = []
    for e in evidences:
        try:
            decrypted_path = crypto.decrypt(e['file_path'])
            decrypted_evidences.append({
                'reference_id': e['reference_id'],
                'file_path': decrypted_path
            })
        except Exception as err:
            print(f"⚠️ Error decrypting evidence: {err}")
            continue

    # Attach decrypted evidences to properties
    for p in properties:
        p['evidences'] = [
            e['file_path'] 
            for e in decrypted_evidences 
            if e['reference_id'] == p['id']
        ]

    return render_template('user/stolen_property.html', properties=properties)


# --------------------------------------------------------------
# DELETE STOLEN PROPERTY + EVIDENCES
# --------------------------------------------------------------
@app.route('/user/delete_stolen_property/<int:prop_id>', methods=['POST'])
def delete_stolen_property(prop_id):
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in first.", "danger")
        return redirect(url_for('login'))

    # 1️⃣ Fetch encrypted evidence paths
    evidences = db.fetchall("""
        SELECT file_path FROM evidence 
        WHERE evidence_type='stolen_property' AND reference_id=%s
    """, (prop_id,))

    # 2️⃣ Delete files from disk
    for e in evidences:
        try:
            # Decrypt the filename first
            decrypted_filename = crypto.decrypt(e['file_path'])
            file_path = os.path.join(app.config['STOLEN_UPLOAD_FOLDER'], decrypted_filename)

            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"✅ Deleted file: {decrypted_filename}")
        except Exception as err:
            print(f"⚠️ Could not remove file: {err}")

    # 3️⃣ Delete DB records
    db.execute("DELETE FROM evidence WHERE evidence_type='stolen_property' AND reference_id=%s", (prop_id,))
    db.execute("DELETE FROM stolen_property WHERE id=%s AND login_id=%s", (prop_id, login_id))

    flash("🗑️ Stolen property and evidences deleted successfully!", "success")
    return redirect(url_for('stolen_property'))


# --------------------------------------------------------------
# DELETE INDIVIDUAL EVIDENCE (OPTIONAL - for future use)
# --------------------------------------------------------------
@app.route('/user/delete_stolen_evidence/<int:evidence_id>', methods=['POST'])
def delete_stolen_evidence(evidence_id):
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in first.", "danger")
        return redirect(url_for('login'))

    # Fetch the evidence
    evidence = db.fetchone("""
        SELECT e.file_path, sp.login_id 
        FROM evidence e
        JOIN stolen_property sp ON e.reference_id = sp.id
        WHERE e.id = %s AND e.evidence_type = 'stolen_property'
    """, (evidence_id,))

    if not evidence:
        flash("Evidence not found.", "danger")
        return redirect(url_for('stolen_property'))

    # Check ownership
    if evidence['login_id'] != login_id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for('stolen_property'))

    try:
        # Decrypt and delete file
        decrypted_filename = crypto.decrypt(evidence['file_path'])
        file_path = os.path.join(app.config['STOLEN_UPLOAD_FOLDER'], decrypted_filename)
        
        if os.path.exists(file_path):
            os.remove(file_path)

        # Delete from database
        db.execute("DELETE FROM evidence WHERE id=%s", (evidence_id,))
        flash("Evidence deleted successfully!", "success")
        
    except Exception as err:
        print(f"Error deleting evidence: {err}")
        flash("Error deleting evidence.", "danger")

    return redirect(url_for('stolen_property'))

#------------------------- STOLEN PROPERTY END ----------------------------------------




#-----------------------------book lawyer appointment start---------------------

@app.route('/user/book_appointment', methods=['GET', 'POST'])
def book_appointment():
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in to book an appointment.", "danger")
        return redirect(url_for('login'))

    db = Database()

    if request.method == 'POST':
        lawyer_id = request.form.get('lawyer_id')
        category = request.form.get('category')
        appointment_date = request.form.get('appointment_date')
        appointment_time = request.form.get('appointment_time')
        case_id = request.form.get('case_id')
        appointment_datetime = f"{appointment_date} {appointment_time}"

        # Check existing booking
        existing = db.fetchone("""
            SELECT * FROM appointments 
            WHERE login_id=%s AND category=%s AND case_id=%s
            ORDER BY id DESC LIMIT 1
        """, (login_id, category, case_id))

        if existing and existing['status'] != 'Rejected':
            flash("You’ve already booked an appointment for this case.", "warning")
            return redirect(url_for('book_appointment', category=category))

        # Get case details
        if category == 'crime':
            case = db.fetchone("SELECT * FROM crimes WHERE id=%s AND login_id=%s", (case_id, login_id))
        elif category == 'missing_person':
            case = db.fetchone("SELECT * FROM missing_persons WHERE id=%s AND login_id=%s", (case_id, login_id))
        elif category == 'stolen_property':
            case = db.fetchone("SELECT * FROM stolen_property WHERE id=%s AND login_id=%s", (case_id, login_id))
        else:
            case = None

        # import json
        # case_details = json.dumps(case, default=default_serializer) if case else "{}"

        # Insert new appointment
        db.execute("""
            INSERT INTO appointments 
                (login_id, lawyer_id, category, appointment_datetime, case_id, case_details, status)
            VALUES 
                (%s, %s, %s, %s, %s, %s, %s)
        """, (login_id, lawyer_id, category, appointment_datetime, case_id, case_details, 'Request'))

        # Notify lawyer about new custom request
        try:
            # Get client's name
            user_record = db.fetchone("SELECT full_name FROM users WHERE login_id = %s", (login_id,))
            client_name = user_record['full_name'] if user_record else "A client"
            
            # Get lawyer's login_id
            law_record = db.fetchone("SELECT login_id FROM lawyers WHERE id = %s", (lawyer_id,))
            if law_record:
                notif_msg = f"New appointment request received from client: {client_name} for category: {category}."
                db.single_insert("""
                    INSERT INTO notifications (login_id, message, is_read)
                    VALUES (%s, %s, 0)
                """, (law_record['login_id'], notif_msg))
        except Exception as e:
            print(f"Error sending notification to lawyer: {e}")

        flash("Appointment booked successfully!", "success")
        return redirect(url_for('book_appointment', category=category))

    # ---------- GET ----------
    category = request.args.get('category')
    lawyers, case_records, booked_cases = [], [], {}

    if category:
        if category == 'crime':
            specs = ['Criminal Lawyer', 'Cybercrime Lawyer', 'Human Rights Lawyer']
            case_records = db.fetchall("SELECT * FROM crimes WHERE login_id=%s ORDER BY created_at DESC", (login_id,))
        elif category == 'missing_person':
            specs = ['Family Lawyer', 'Criminal Lawyer', 'Human Rights Lawyer']
            case_records = db.fetchall("SELECT * FROM missing_persons WHERE login_id=%s ORDER BY last_seen DESC", (login_id,))
        elif category == 'stolen_property':
            specs = ['Property Lawyer', 'Criminal Lawyer', 'Cybercrime Lawyer']
            case_records = db.fetchall("SELECT * FROM stolen_property WHERE login_id=%s ORDER BY date_stolen DESC", (login_id,))
        else:
            specs = []

        if specs:
            placeholders = ','.join(['%s'] * len(specs))
            query = f"SELECT * FROM lawyers WHERE specialization IN ({placeholders})"
            lawyers = db.fetchall(query, tuple(specs))

        booked_cases_data = db.fetchall("""
            SELECT a.case_id, a.status, l.full_name AS lawyer_name
            FROM appointments a
            JOIN lawyers l ON a.lawyer_id = l.id
            WHERE a.login_id=%s AND a.category=%s
        """, (login_id, category))

        booked_cases = {a['case_id']: a for a in booked_cases_data}

    return render_template(
        'user/book_appointment.html',
        category=category,
        lawyers=lawyers,
        case_records=case_records,
        booked_cases=booked_cases
    )

#------------------booking appointment ends---------------------

#------------------------booking status start--------------------------


@app.route('/user/booking_status')
def booking_status():
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in to view your booking status.", "danger")
        return redirect(url_for('login'))

    # Fetch all appointments joined with lawyer details
    appointments = db.fetchall("""
        SELECT a.*, l.full_name AS lawyer_name, l.specialization, l.phone
        FROM appointments a
        JOIN lawyers l ON a.lawyer_id = l.id
        WHERE a.login_id = %s
        ORDER BY a.appointment_datetime DESC
    """, (login_id,))

    return render_template('user/booking_status.html', appointments=appointments)




#---------------------------booking status ends----------------------------
#--------------------crime stats on userside(hotspot mapping)-----------------
@app.route('/user/crime_mapping')
def crime_mapping():
    db = Database()

    query = """
        SELECT 
            crime_type,
            COUNT(*) AS count,
            location AS hotspot,
            latitude,
            longitude
        FROM crimes
        WHERE latitude IS NOT NULL 
          AND longitude IS NOT NULL
        GROUP BY crime_type, location, latitude, longitude
        ORDER BY count DESC
    """

    stats = db.fetchall(query)
    return render_template('user/crime_statsmap.html', stats=stats)

#----------chat bot start-----------------
@app.route('/user/chatbot')
def chatbot():
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in to use the chatbot.", "danger")
        return redirect(url_for('login'))

    # Fetch previous chat history from DB
    history = db.fetchall("SELECT message, response FROM chat_history WHERE login_id=%s ORDER BY created_at ASC", (login_id,))
    return render_template('user/chatbot.html', history=history)

def get_schema_context():
    return """
    Table: crimes
    Columns: id, crime_type, crime_date, location, description, status, reporter_name, witnesses, suspects

    Table: missing_persons
    Columns: id, name, gender, age, height, weight, last_seen, location, description, status

    Table: stolen_property
    Columns: id, item_name, category, date_stolen, location, estimated_value, description, status

    Table: lawyers
    Columns: id, full_name, phone, specialization (e.g., Criminal Lawyer, Civil Lawyer), rating, fees, email

    Table: appointments
    Columns: id, lawyer_id, appointment_datetime, status, category
    """

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    user_message = data.get('message', '')

    api_key = os.environ.get("GEMINI_API_KEY") or "AIzaSyCVfgELZKjPDjCpsr8rwKz2row32U3HkQw"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        schema = get_schema_context()

        # Step 1: Determine if DB access is needed and generate SQL
        system_prompt_sql = f"""
        You are an expert SQL developer and Legal Advocate assistant.
        Your goal is to help the user by querying the database if necessary.

        Database Schema:
        {schema}

        Rules:
        1. If the user asks for information stored in the database (crimes, lawyers, missing persons, stats), generate a valid MySQL SELECT query.
        2. The query should be plain text, starting with 'SELECT'. Do NOT use markdown formatting like ```sql.
        3. If the user asks a general legal question (e.g., "What is IPC 302?") or a greeting, logic that requires NO database access, respond with "NO_DB".
        4. Focus on the relevant tables. For "lawyers", check the lawyers table. for "crimes", check crimes table.
        5. Do not perform INSERT/UPDATE/DELETE operations. READ ONLY.
       
        """

        response_sql = model.generate_content([
            {"role": "user", "parts": [f"{system_prompt_sql}\n\nUser Question: {user_message}\nGenerate SQL or NO_DB:"]}
        ])

        llm_response = response_sql.text.strip()
        print(f"LLM SQL Step Response: {llm_response}")

        final_answer = ""

        if llm_response.upper().startswith("SELECT"):
            # Execute SQL
            sql_query = llm_response.replace("```sql", "").replace("```", "").strip()
            print(f"Executing SQL: {sql_query}")

            try:
                # Use the existing global db instance
                db_results = db.fetchall(sql_query)
                data_context = f"Database Results: {db_results}"
            except Exception as e:
                data_context = f"Database Error: {str(e)}"
                print(data_context)

            # Step 2: Generate final natural language response using data
            system_prompt_final = (
                "You are an AI Legal Advocate Chatbot. "
                "You have executed a database query to help the user. "
                "Use the provided Database Results to answer the user's question clearly and professionally. "
                "If the result is empty, say no records were found. "
                "Also provide brief legal context if relevant (e.g., mention relevant IPC sections for crimes)."
                " if BNS(BHARATH NIYAM SAMHITHA) is there insted of ipc , prioritize BNS sections."
                    "also remove ** like special charectors only allow : and ."
            )

            response_final = model.generate_content([
                {"role": "user", "parts": [f"{system_prompt_final}\n\nUser Question: {user_message}\n{data_context}"]}
            ])
            final_answer = response_final.text

        else:
            # Handle General Questions with no DB access
            system_prompt_general = (
                "You are an AI Legal Advocate Chatbot. "
                "Guide users in understanding IPC sections, checking case legitimacy (general advice), and legal procedures. "
                "Be professionally helpful and concise."
            )

            response_general = model.generate_content([
                {"role": "user", "parts": [f"{system_prompt_general}\n\n{user_message}"]}
            ])
            final_answer = response_general.text

        return jsonify({"response": final_answer})

    except Exception as e:
        print(f"Chatbot Error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # Save chat to history if we have a user and a message
        login_id = session.get('login_id')
        if login_id and user_message and 'final_answer' in locals() and final_answer:
            try:
                db.execute("INSERT INTO chat_history (login_id, message, response) VALUES (%s, %s, %s)",
                           (login_id, user_message, final_answer))
            except Exception as db_err:
                print(f"Failed to save chat history: {db_err}")
#--------------------chat bot end-----------------



@app.route('/police/chatbot')
def police_chatbot():

    login_id = session.get('login_id')

    if not login_id:
        flash("Login required","danger")
        return redirect(url_for('login'))

    history = db.fetchall(
        "SELECT message,response FROM police_chat_history WHERE login_id=%s ORDER BY created_at",
        (login_id,)
    )

    return render_template("police/chatbot.html",history=history)

@app.route('/api/police_chat',methods=['POST'])
def police_chat():

#     data=request.json
#     message=data.get("message")

#     model=genai.GenerativeModel('gemini-2.5-flash')

#     prompt=f"""
# You are a Police Assistant AI.

# Help police officers with:

# • crime reports
# • suspect analysis
# • missing persons
# • stolen property
# • IPC / BNS sections

# Question:
# {message}
# """

#     response=model.generate_content(prompt)

#     answer=response.text

#     login_id=session.get("login_id")

#     db.execute(
#     "INSERT INTO police_chat_history(login_id,message,response) VALUES(%s,%s,%s)",
#     (login_id,message,answer)
#     )

#     return jsonify({"response":answer})

    data = request.json
    user_message = data.get('message', '')

    api_key = os.environ.get("GEMINI_API_KEY") or "AIzaSyBMciH2LMJtjrT_ADO4qX2PdSBQP8lnq6M"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        schema = get_schema_context()

        # Step 1: Determine if DB access is needed and generate SQL
        system_prompt_sql = f"""
        You are an expert SQL developer and Legal Advocate assistant.
        Your goal is to help the user by querying the database if necessary.

        Database Schema:
        {schema}

        Rules:
        1. If the user asks for information stored in the database (crimes, lawyers, missing persons, stats), generate a valid MySQL SELECT query.
        2. The query should be plain text, starting with 'SELECT'. Do NOT use markdown formatting like ```sql.
        3. If the user asks a general legal question (e.g., "What is IPC 302?") or a greeting, logic that requires NO database access, respond with "NO_DB".
        4. Focus on the relevant tables. For "lawyers", check the lawyers table. for "crimes", check crimes table.
        5. Do not perform INSERT/UPDATE/DELETE operations. READ ONLY.
       
        """

        response_sql = model.generate_content([
            {"role": "user", "parts": [f"{system_prompt_sql}\n\nUser Question: {user_message}\nGenerate SQL or NO_DB:"]}
        ])

        llm_response = response_sql.text.strip()
        print(f"LLM SQL Step Response: {llm_response}")

        final_answer = ""

        if llm_response.upper().startswith("SELECT"):
            # Execute SQL
            sql_query = llm_response.replace("```sql", "").replace("```", "").strip()
            print(f"Executing SQL: {sql_query}")

            try:
                # Use the existing global db instance
                db_results = db.fetchall(sql_query)
                data_context = f"Database Results: {db_results}"
            except Exception as e:
                data_context = f"Database Error: {str(e)}"
                print(data_context)

            # Step 2: Generate final natural language response using data
            system_prompt_final = (
                "You are an AI Chatbot. "
                "You have executed a database query to help the user. "
                "Use the provided Database Results to answer the user's question clearly and professionally. "
                "If the result is empty, say no records were found. "
                "Also provide brief legal context if relevant (e.g., mention relevant IPC sections for crimes)."
                " if BNS(BHARATH NIYAM SAMHITHA) is there insted of ipc , prioritize BNS sections."
                    "also remove ** like special charectors only allow : and ."
            )

            response_final = model.generate_content([
                {"role": "user", "parts": [f"{system_prompt_final}\n\nUser Question: {user_message}\n{data_context}"]}
            ])
            final_answer = response_final.text

        else:
            # Handle General Questions with no DB access
            system_prompt_general = (
                "You are an AI Legal Advocate Chatbot. "
                "Guide users in understanding IPC sections, checking case legitimacy (general advice), and legal procedures. "
                "Be professionally helpful and concise."
            )

            response_general = model.generate_content([
                {"role": "user", "parts": [f"{system_prompt_general}\n\n{user_message}"]}
            ])
            final_answer = response_general.text

        return jsonify({"response": final_answer})

    except Exception as e:
        print(f"Chatbot Error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # Save chat to history if we have a user and a message
        login_id = session.get('login_id')
        if login_id and user_message and 'final_answer' in locals() and final_answer:
            try:
                db.execute("INSERT INTO police_chat_history (login_id, message, response) VALUES (%s, %s, %s)",
                           (login_id, user_message, final_answer))
            except Exception as db_err:
                print(f"Failed to save chat history: {db_err}")


@app.route('/lawyer/chatbot')
def lawyer_chatbot():

    login_id = session.get('login_id')

    if not login_id:
        flash("Login required","danger")
        return redirect(url_for('login'))

    history=db.fetchall(
    "SELECT message,response FROM lawyer_chat_history WHERE login_id=%s ORDER BY created_at",
    (login_id,)
    )

    return render_template("lawyer/chatbot.html",history=history)

@app.route('/api/lawyer_chat',methods=['POST'])
def lawyer_chat():

#     data=request.json
#     message=data.get("message")

#     model=genai.GenerativeModel('gemini-2.5-flash')

#     prompt=f"""
# You are an expert AI Legal Advocate.

# Assist lawyers with:

# • IPC and BNS sections
# • court procedures
# • case law references
# • legal drafting
# • legal strategy

# Question:
# {message}
# """

#     response=model.generate_content(prompt)

#     answer=response.text

#     login_id=session.get("login_id")

#     db.execute(
#     "INSERT INTO lawyer_chat_history(login_id,message,response) VALUES(%s,%s,%s)",
#     (login_id,message,answer)
#     )

#     return jsonify({"response":answer})
    data = request.json
    user_message = data.get('message', '')

    api_key = os.environ.get("GEMINI_API_KEY") or "AIzaSyBKemOfw9u6tCygdMek8kPxiM0psvGJmJk"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        schema = get_schema_context()

        # Step 1: Determine if DB access is needed and generate SQL
        system_prompt_sql = f"""
        You are an expert SQL developer and Legal Advocate assistant.
        Your goal is to help the user by querying the database if necessary.

        Database Schema:
        {schema}

        Rules:
        1. If the user asks for information stored in the database (crimes, lawyers, missing persons, stats), generate a valid MySQL SELECT query.
        2. The query should be plain text, starting with 'SELECT'. Do NOT use markdown formatting like ```sql.
        3. If the user asks a general legal question (e.g., "What is IPC 302?") or a greeting, logic that requires NO database access, respond with "NO_DB".
        4. Focus on the relevant tables. For "lawyers", check the lawyers table. for "crimes", check crimes table.
        5. Do not perform INSERT/UPDATE/DELETE operations. READ ONLY.
       
        """

        response_sql = model.generate_content([
            {"role": "user", "parts": [f"{system_prompt_sql}\n\nUser Question: {user_message}\nGenerate SQL or NO_DB:"]}
        ])

        llm_response = response_sql.text.strip()
        print(f"LLM SQL Step Response: {llm_response}")

        final_answer = ""

        if llm_response.upper().startswith("SELECT"):
            # Execute SQL
            sql_query = llm_response.replace("```sql", "").replace("```", "").strip()
            print(f"Executing SQL: {sql_query}")

            try:
                # Use the existing global db instance
                db_results = db.fetchall(sql_query)
                data_context = f"Database Results: {db_results}"
            except Exception as e:
                data_context = f"Database Error: {str(e)}"
                print(data_context)

            # Step 2: Generate final natural language response using data
            system_prompt_final = (
                "You are an AI Chatbot. "
                "You have executed a database query to help the user. "
                "Use the provided Database Results to answer the user's question clearly and professionally. "
                "If the result is empty, say no records were found. "
                "Also provide brief legal context if relevant (e.g., mention relevant IPC sections for crimes)."
                " if BNS(BHARATH NIYAM SAMHITHA) is there insted of ipc , prioritize BNS sections."
                    "also remove ** like special charectors only allow : and ."
            )

            response_final = model.generate_content([
                {"role": "user", "parts": [f"{system_prompt_final}\n\nUser Question: {user_message}\n{data_context}"]}
            ])
            final_answer = response_final.text

        else:
            # Handle General Questions with no DB access
            system_prompt_general = (
                "You are an AI Legal Advocate Chatbot. "
                "Guide users in understanding IPC sections, checking case legitimacy (general advice), and legal procedures. "
                "Be professionally helpful and concise."
            )

            response_general = model.generate_content([
                {"role": "user", "parts": [f"{system_prompt_general}\n\n{user_message}"]}
            ])
            final_answer = response_general.text

        return jsonify({"response": final_answer})

    except Exception as e:
        print(f"Chatbot Error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # Save chat to history if we have a user and a message
        login_id = session.get('login_id')
        if login_id and user_message and 'final_answer' in locals() and final_answer:
            try:
                db.execute("INSERT INTO lawyer_chat_history (login_id, message, response) VALUES (%s, %s, %s)",
                           (login_id, user_message, final_answer))
            except Exception as db_err:
                print(f"Failed to save chat history: {db_err}")


#--------------------------USER DASHBOARD-----------------------------
# @app.route('/submit_evidence')
# def submit_evidence():
#     return render_template('user/submit_evidence.html')


#==========================END OF USER DASHBOARD=====================

#===========================ADMIN DASHBOARD===============================

#-----------------------------dashboard start-----------------------------
@app.route('/admin/dashboard')
def admin_dashboard():
    # 1. Lawyers
    query = "SELECT * FROM lawyers"
    lawyers = db.fetchall(query)
    lawyer_count = len(lawyers)

    # 2. Registered Crimes
    crimes = db.fetchall("SELECT * FROM crimes ORDER BY id DESC")
    crime_count = len(crimes)

    closed_cases = db.fetchall("SELECT * FROM crimes WHERE status = 'Closed'")
    closed_count = len(closed_cases)

    # 3. Registered Missing Persons
    persons = db.fetchall("SELECT * FROM missing_persons ORDER BY id DESC")
    missing_count = len(persons)

    closed_cases = db.fetchall("SELECT * FROM missing_persons WHERE status = 'Closed'")
    closed_count = len(closed_cases)

    # 4. Registered Stolen Property
    properties = db.fetchall("SELECT * FROM stolen_property ORDER BY id DESC")
    property_count = len(properties)

    closed_cases = db.fetchall("SELECT * FROM stolen_property WHERE status = 'Closed'")
    closed_count = len(closed_cases)

    # 🔹 Crimes Over Time (group by month)
    monthly_counts = defaultdict(int)
    for c in crimes:
        if 'crime_date' in c and c['crime_date']:
            month = c['crime_date'].strftime('%b')  # e.g. 'Jan', 'Feb'
            monthly_counts[month] += 1

    # Sort by month order (Jan → Dec)
    months_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    months = []
    crime_values = []
    for m in months_order:
        months.append(m)
        crime_values.append(monthly_counts.get(m, 0))

    return render_template(
        'admin/dashboard.html',
        lawyer_count=lawyer_count,
        crime_count=crime_count,
        closed_count=closed_count,
        missing_count=missing_count,
        property_count=property_count,
        lawyers=lawyers,
        crimes=crimes,
        persons=persons,
        properties=properties,
        months=months,
        crime_values=crime_values
    )

#------------------------------dashboard ends-----------------------


#---------------------------pending lawyer approval-------------------------
# @app.route('/admin/lawyer_profile')
# def lawyer_profile():
#     try:
#         # Fetch all lawyers with status 0 (pending)
#         query = "SELECT id, username FROM users WHERE role='lawyer' AND status=0"
#         lawyers = db.fetchall(query)
#         return render_template('admin/lawyer_profile.html', lawyers=lawyers)
#     except Exception as e:
#         print(f"Error fetching lawyers: {e}")
#         flash("Could not load lawyer profiles.", "danger")
#         return render_template('admin/lawyer_profile.html', lawyers=[])


# Admin: Approve lawyer
# @app.route('/admin/approve_lawyer/<int:lawyer_id>', methods=['POST'])
# def approve_lawyer(lawyer_id):
#     try:
#         query = "UPDATE users SET status=1 WHERE id=%s"
#         db.execute(query, (lawyer_id,))
#         flash("Lawyer approved successfully!", "success")
#     except Exception as e:
#         print(f"Error approving lawyer: {e}")
#         flash("Could not approve lawyer.", "danger")
#     return redirect(url_for('lawyer_profile'))


# Admin: Reject lawyer
# @app.route('/admin/reject_lawyer/<int:lawyer_id>', methods=['POST'])
# def reject_lawyer(lawyer_id):
#     try:
#         query = "DELETE FROM users WHERE id=%s"
#         db.execute(query, (lawyer_id,))
#         flash("Lawyer rejected successfully!", "success")
#     except Exception as e:
#         print(f"Error rejecting lawyer: {e}")
#         flash("Could not reject lawyer.", "danger")

        
#     return redirect(url_for('lawyer_profile'))
#-------------------pending lawyer approval ends---------------------

#----------------------registered lawyers start---------------------
    
@app.route('/admin/registered_lawyers')
def registered_lawyers():
    query = "SELECT * FROM lawyers"
    lawyers = db.fetchall(query)  # no cursor needed
    return render_template('admin/registered_lawyers.html', lawyers=lawyers)

# -------------------------
# Route: Delete Lawyer (optional)
# -------------------------
@app.route('/admin/delete_lawyer/<int:lawyer_id>', methods=['POST'])
def delete_lawyer(lawyer_id):
    query = "DELETE FROM lawyers WHERE id=%s"
    db.execute(query, (lawyer_id,))
    return redirect(url_for('registered_lawyers'))

#----------------------registered lawyer end------------------------

#-------------------------registered user start----------------------

@app.route('/admin/registered_users')
def registered_users():
    db = Database()

    try:
        # Fetch all users (normal users)
        query = """
            SELECT id, full_name, phone, created_at
            FROM users
        """
        users = db.fetchall(query)

    except Exception as e:
        print(f"❌ Error fetching users: {e}")
        users = []

    return render_template('admin/registered_users.html', users=users)

@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    db = Database()

    try:
        # get login_id from users table
        qry = "SELECT login_id FROM users WHERE id = %s"
        record = db.fetchone(qry, (user_id,))

        if not record:
            flash("User not found!", "danger")
            return redirect(url_for('registered_users'))

        login_id = record['login_id']

        # delete from users
        db.execute("DELETE FROM users WHERE id = %s", (user_id,))

        # delete from login
        db.execute("DELETE FROM login WHERE id = %s", (login_id,))

        flash("User deleted successfully!", "success")
    
    except Exception as e:
        print("❌ ERROR deleting user:", e)
        flash("Server error!", "danger")

    return redirect(url_for('registered_users'))


#------------------registered user end----------------------------



#-----------------------------registered crime start---------------------

@app.route('/admin/registered_crime')
def registered_crime():
    try:
        query = "SELECT * FROM crimes ORDER BY id DESC"
        crimes = db.fetchall(query)
        return render_template('admin/registered_crime.html', crimes=crimes)
    except Exception as e:
        flash(f"Error fetching records: {str(e)}", "danger")
        return render_template('admin/registered_crime.html', crimes=[])
    
@app.route('/admin/update_crime_status/<crime_id>/<new_status>')
def update_crime_status(crime_id, new_status):
    db.execute("UPDATE crimes SET status=%s WHERE id=%s", (new_status, crime_id))
    flash(f"Crime status updated to {new_status}", "success")
    return redirect(url_for('registered_crime'))

    

#------------------------registered crime end---------------------------

#-------------------------registered missing person start------------------    
@app.route('/admin/registered_missing')
def registered_missing():
    try:
        persons = db.fetchall("SELECT * FROM missing_persons ORDER BY id DESC")
        return render_template('admin/registered_missing.html', persons=persons)
    except Exception as e:
        print("Error loading records:", e)
        flash("Error loading missing persons data.", "danger")
        return render_template('admin/registered_missing.html', persons=[])  
    
@app.route('/admin/update_missing_status/<int:person_id>/<string:new_status>')
def update_missing_status(person_id, new_status):
    db.execute("""
        UPDATE missing_persons
        SET status=%s
        WHERE id=%s
    """, (new_status, person_id))

    flash("Status updated successfully", "success")
    return redirect(url_for('registered_missing'))


#---------------------------registered missing person end-------------------

#---------------------------registered stolen property start-----------------------    

@app.route('/admin/registered_stolenitem')
def registered_stolenitem():
    try:
        properties = db.fetchall("SELECT * FROM stolen_property ORDER BY id DESC")
        return render_template('admin/registered_stolenitem.html', properties=properties)
    except Exception as e:
        print("Error fetching stolen items:", e)
        flash("Error loading stolen items data.", "danger")
        return render_template('admin/registered_stolenitem.html', properties=[])
    
@app.route('/admin/update_property_status/<int:prop_id>/<string:new_status>')
def update_property_status(prop_id, new_status):
    db.execute("""
        UPDATE stolen_property
        SET status=%s
        WHERE id=%s
    """, (new_status, prop_id))

    flash("Property status updated successfully", "success")
    return redirect(url_for('registered_stolenitem'))

    
#---------------------------registered stolen property end----------------------------    


# ----------------------------Crime Statistics start------------------------------------


@app.route('/admin/crime_stats')
def crime_stats():
    db = Database()
    
    # Get search parameter if provided
    search_query = request.args.get('search', '').strip()
    
    if search_query:
        # Search by crime type or location
        query = """
            SELECT 
                crime_type, 
                COUNT(*) AS count, 
                location AS hotspot
            FROM crimes
            WHERE crime_type LIKE %s OR location LIKE %s
            GROUP BY crime_type, location
            ORDER BY count DESC
        """
        stats = db.fetchall(query, (f'%{search_query}%', f'%{search_query}%'))
    else:
        # Default: show all stats ordered by count
        query = """
            SELECT 
                crime_type, 
                COUNT(*) AS count, 
                location AS hotspot
            FROM crimes
            GROUP BY crime_type, location
            ORDER BY count DESC
            LIMIT 10
        """
        stats = db.fetchall(query)
    
    return render_template('admin/crime_stats.html', stats=stats, search_query=search_query)


#---------------------------crime stats end-----------------------

    
# ============================ ADMIN HEARING STATUS VERIFICATION START ============================

@app.route('/admin/hearing_status_updates')
def admin_hearing_status_updates():
    """Display pending hearing status updates for admin verification"""
    
    # Optional: protect route
    if "username" not in session or session.get('role') != 'admin':
        return redirect(url_for("login"))
    
    try:
        # Fetch all pending hearing status updates with appointment and client details
        pending_updates = db.fetchall("""
            SELECT 
                hsu.id,
                hsu.appointment_id,
                hsu.requested_status,
                hsu.created_at,
                u.full_name AS client_name,
                u.phone AS client_phone,
                a.category,
                l.full_name AS lawyer_name,
                DATE(a.appointment_datetime) AS appointment_date,
                TIME_FORMAT(a.appointment_datetime, '%h:%i %p') AS appointment_time
            FROM hearing_status_updates hsu
            INNER JOIN appointments a ON hsu.appointment_id = a.id
            INNER JOIN users u ON a.login_id = u.login_id
            INNER JOIN lawyers l ON a.lawyer_id = l.id
            WHERE hsu.status = 'pending'
            ORDER BY hsu.created_at DESC
        """)
        
        return render_template('admin/hearing_status_updates.html', pending_updates=pending_updates)
    except Exception as e:
        print(f"❌ Error fetching hearing status updates: {e}")
        flash("Error loading hearing status updates.", "danger")
        return redirect(url_for("admin_dashboard"))


@app.route('/admin/approve_hearing_update/<int:update_id>', methods=['POST'])
def approve_hearing_update(update_id):
    """Approve a hearing status update"""
    
    if "username" not in session or session.get('role') != 'admin':
        return redirect(url_for("login"))
    
    try:
        # Get the hearing status update
        update = db.fetchone("""
            SELECT id, appointment_id, requested_status, client_id
            FROM hearing_status_updates
            WHERE id = %s AND status = 'pending'
        """, (update_id,))
        
        if not update:
            flash("Hearing status update not found.", "danger")
            return redirect(url_for("admin_hearing_status_updates"))
        
        # Get appointment details
        appointment = db.fetchone("""
            SELECT a.id, a.status, u.full_name AS client_name
            FROM appointments a
            INNER JOIN users u ON a.login_id = u.login_id
            WHERE a.id = %s
        """, (update['appointment_id'],))
        
        if not appointment:
            flash("Appointment not found.", "danger")
            return redirect(url_for("admin_hearing_status_updates"))
        
        # Update the hearing status update record
        db.execute("""
            UPDATE hearing_status_updates
            SET status = 'approved'
            WHERE id = %s
        """, (update_id,))
        
        # Update the appointment status
        db.execute("""
            UPDATE appointments
            SET status = %s
            WHERE id = %s
        """, (update['requested_status'], update['appointment_id']))
        
        # Notify the client about the hearing status change
        message = f"The hearing status for your case has been updated to '{update['requested_status']}' by the admin."
        db.single_insert("""
            INSERT INTO notifications (login_id, message, is_read)
            VALUES (%s, %s, 0)
        """, (update['client_id'], message))
        
        flash(f"Hearing status update approved! Client '{appointment['client_name']}' has been notified.", "success")
        
    except Exception as e:
        print(f"❌ Error approving hearing status update: {e}")
        flash("Error approving hearing status update.", "danger")
    
    return redirect(url_for("admin_hearing_status_updates"))


@app.route('/admin/reject_hearing_update/<int:update_id>', methods=['POST'])
def reject_hearing_update(update_id):
    """Reject a hearing status update"""
    
    if "username" not in session or session.get('role') != 'admin':
        return redirect(url_for("login"))
    
    rejection_reason = request.form.get('rejection_reason', 'No reason provided')
    
    try:
        # Get the hearing status update
        update = db.fetchone("""
            SELECT id, appointment_id, client_id
            FROM hearing_status_updates
            WHERE id = %s AND status = 'pending'
        """, (update_id,))
        
        if not update:
            flash("Hearing status update not found.", "danger")
            return redirect(url_for("admin_hearing_status_updates"))
        
        # Update the hearing status update record
        db.execute("""
            UPDATE hearing_status_updates
            SET status = 'rejected', rejection_reason = %s
            WHERE id = %s
        """, (rejection_reason, update_id))
        
        # Notify the lawyer about the rejection
        message = f"Your hearing status update request for appointment #{update['appointment_id']} has been rejected. Reason: {rejection_reason}"
        lawyer = db.fetchone("""
            SELECT l.login_id
            FROM appointments a
            INNER JOIN lawyers l ON a.lawyer_id = l.id
            WHERE a.id = %s
        """, (update['appointment_id'],))
        
        if lawyer:
            db.single_insert("""
                INSERT INTO notifications (login_id, message, is_read)
                VALUES (%s, %s, 0)
            """, (lawyer['login_id'], message))
        
        flash("Hearing status update rejected! Lawyer has been notified.", "success")
        
    except Exception as e:
        print(f"❌ Error rejecting hearing status update: {e}")
        flash("Error rejecting hearing status update.", "danger")
    
    return redirect(url_for("admin_hearing_status_updates"))

# ============================ ADMIN HEARING STATUS VERIFICATION END ============================








#==================================ADMIN DASHBOARD ENDS==========================

#=================================LAWYER DASHBOARD START============================


#-------------------------dashboard start-----------------------------


@app.route('/lawyer/dashboard')
def lawyer_dashboard():
    # Check if lawyer logged in
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in first.", "danger")
        return redirect(url_for('login'))
    
    
    # ----- Approved Cases -----
    approved_cases = db.fetchone("""
        SELECT COUNT(a.id) AS cnt
        FROM appointments a
        INNER JOIN lawyers l ON a.lawyer_id = l.id
        WHERE l.login_id = %s AND a.status = 'Approved'
    """, (login_id,))
    approved_case_count = approved_cases['cnt'] if approved_cases else 0

    


    # ----- Rejected Cases -----
    rejected_cases = db.fetchone("""
        SELECT COUNT(a.id) AS cnt
        FROM appointments a
        INNER JOIN lawyers l ON a.lawyer_id = l.id
        WHERE l.login_id = %s AND a.status = 'Rejected'
    """, (login_id,))
    rejected_case_count = rejected_cases['cnt'] if rejected_cases else 0

    # ----- Client Requests -----
    request_cases = db.fetchone("""
        SELECT COUNT(a.id) AS cnt
        FROM appointments a
        INNER JOIN lawyers l ON a.lawyer_id = l.id
        WHERE l.login_id = %s AND a.status = 'Request'
    """, (login_id,))
    request_case_count = request_cases['cnt'] if request_cases else 0

    total_case_count=approved_case_count + rejected_case_count + request_case_count
   
    print(approved_cases)

   
    # Pass all counts to template
    return render_template(
        'lawyer/dashboard.html',
        total_case_count=total_case_count,
        approved_case_count=approved_case_count,
        rejected_case_count=rejected_case_count,
        request_case_count=request_case_count,
        )

#-----------------------------dashboard end-----------------------

#---------------------lawyer profile start-----------------------



ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}

def allowed_image(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

    
@app.route('/lawyer/profile', methods=['GET', 'POST'])
def lawyer_profile():

    lawyer_id = session.get('login_id')
    lawyer = None

    if lawyer_id:
        lawyer = db.fetchone(
            "SELECT * FROM lawyers WHERE login_id=%s",
            (lawyer_id,)
        )

    if request.method == 'POST':

        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        specialization = request.form.get('specialization')
        fees = request.form.get('fees',0)
        country_code = request.form.get('country_code')

        image_file = request.files.get('image')

        image_name = lawyer['image'] if lawyer else None


        # EMAIL VALIDATION
        if '@' not in email:
            flash("Invalid Email! Must contain @", "danger")
            return redirect(url_for('lawyer_profile'))


        # PHONE VALIDATION
        if not phone.isdigit() or len(phone) != 10:
            flash("Phone number must be exactly 10 digits", "danger")
            return redirect(url_for('lawyer_profile'))


        # IMAGE UPLOAD
        if image_file and image_file.filename:

            if allowed_image(image_file.filename):

                filename = secure_filename(image_file.filename)

                save_path = os.path.join(
                    app.config['LAWYER_UPLOAD_FOLDER'],
                    filename
                )

                image_file.save(save_path)

                # DELETE OLD IMAGE
                if lawyer and lawyer.get("image"):

                    old_path = os.path.join(
                        app.config['LAWYER_UPLOAD_FOLDER'],
                        lawyer["image"]
                    )

                    if os.path.exists(old_path):
                        os.remove(old_path)

                image_name = filename

            else:

                flash("Only JPG images allowed!", "danger")
                return redirect(url_for('lawyer_profile'))


        # UPDATE PROFILE
        if lawyer:

            update_query = """
            UPDATE lawyers
            SET full_name=%s,
                email=%s,
                phone=%s,
                country_code=%s,
                specialization=%s,
                fees=%s,
                image=%s
            WHERE login_id=%s
            """

            db.execute(update_query,
                       (full_name,email,phone,country_code,specialization,fees,image_name,lawyer_id))

        else:

            insert_query = """
            INSERT INTO lawyers
            (login_id,full_name,email,phone,country_code,specialization,fees,image)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """

            db.execute(insert_query,
                       (lawyer_id,full_name,email,phone,country_code,specialization,fees,image_name))


        flash("Profile updated successfully!", "success")

        return redirect(url_for('lawyer_profile'))


    return render_template('lawyer/profile.html', lawyer=lawyer)

#-----------------------lawyer profile end-------------------------



#-------------------------------appointment approval start-------------------------------


@app.route('/lawyer/appointments')
def lawyer_appointments():
    db = Database()

    # Step 1: Get lawyer’s login_id from session
    lawyer_login_id = session.get('login_id')
    if not lawyer_login_id:
        flash("Please log in as a lawyer to view appointments.", "danger")
        return redirect(url_for('login'))

    try:
        # Step 2: Get lawyer.id using login_id
        lawyer = db.fetchone("SELECT id FROM lawyers WHERE login_id = %s", (lawyer_login_id,))
        if not lawyer:
            flash("Lawyer profile not found.", "danger")
            return redirect(url_for('dashboard'))

        lawyer_id = lawyer['id']

        # Step 3: Fetch appointments for this lawyer
        query = """
            SELECT 
                a.id AS appointment_id,
                u.full_name AS client_name,
                u.phone,
                DATE(a.appointment_datetime) AS appointment_date,
                TIME_FORMAT(a.appointment_datetime, '%%h:%%i %%p') AS appointment_time,
                a.case_id,
                a.category,
                a.status
            FROM appointments a
            INNER JOIN users u ON a.login_id = u.login_id
            WHERE a.lawyer_id = %s
            ORDER BY a.appointment_datetime DESC
        """
        appointments = db.fetchall(query, (lawyer_id,))
        print("Appointments:", appointments)

    except Exception as e:
        print(f"❌ Error fetching appointments: {e}")
        appointments = []

    return render_template('lawyer/my_appointments.html', appointments=appointments)

@app.route('/lawyer/appointments/update_appointment_status', methods=['POST'])
def update_appointment_status():
    db = Database()

    lawyer_login_id = session.get('login_id')
    if not lawyer_login_id:
        flash("Please login first", "danger")
        return redirect(url_for('login'))

    appointment_id = request.form.get('appointment_id')
    new_status = request.form.get('status')
    rejection_reason = request.form.get('rejection_reason', '')
    new_appointment_date = request.form.get('new_appointment_date', '')
    new_appointment_time = request.form.get('new_appointment_time', '')
    reschedule_message = request.form.get('reschedule_message', '')

    if not appointment_id:
        flash("Invalid appointment!", "danger")
        return redirect(url_for('lawyer_appointments'))

    # Fetch appointment details
    appt = db.fetchone("""
        SELECT id, login_id, lawyer_id, category, case_id, case_details 
        FROM appointments WHERE id=%s
    """, (appointment_id,))

    if not appt:
        flash("Appointment not found!", "danger")
        return redirect(url_for('lawyer_appointments'))

    try:
        # Get lawyer's name
        law_query = """
            SELECT u.full_name 
            FROM lawyers l 
            INNER JOIN users u ON l.login_id = u.login_id 
            WHERE l.id = %s
        """
        law_record = db.fetchone(law_query, (appt['lawyer_id'],))
        lawyer_name = law_record['full_name'] if law_record else "the lawyer"

        # Update status in appointments table
        if new_status == "Rejected" and rejection_reason:
            # Add rejection reason to the update
            db.execute(
                "UPDATE appointments SET status=%s, rejection_reason=%s WHERE id=%s",
                (new_status, rejection_reason, appointment_id)
            )
            
            # Send rejection notification with reason
            message = f"Your appointment request has been rejected by lawyer {lawyer_name}. Reason: {rejection_reason}"
            db.single_insert("""
                INSERT INTO notifications (login_id, message, is_read)
                VALUES (%s, %s, 0)
            """, (appt['login_id'], message))
            
            # If rescheduling is suggested, create a new appointment with status 'Reschedule Request'
            if new_appointment_date and new_appointment_time:
                new_datetime = f"{new_appointment_date} {new_appointment_time}"
                
                db.execute("""
                    INSERT INTO appointments 
                    (login_id, lawyer_id, category, appointment_datetime, case_id, case_details, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (appt['login_id'], appt['lawyer_id'], appt['category'], 
                      new_datetime, appt['case_id'], appt['case_details'], 'Reschedule Request'))
                
                # Send rescheduling notification
                reschedule_msg = f"Lawyer {lawyer_name} has suggested a new appointment time: {new_appointment_date} at {new_appointment_time}. Please accept or decline this reschedule request."
                if reschedule_message:
                    reschedule_msg += f" Message from lawyer: {reschedule_message}"
                
                db.single_insert("""
                    INSERT INTO notifications (login_id, message, is_read)
                    VALUES (%s, %s, 0)
                """, (appt['login_id'], reschedule_msg))
                
                flash(f"Appointment rejected with rescheduling suggestion!", "success")
            else:
                flash(f"Appointment rejected successfully!", "success")
        
        elif new_status == "Approved":
            db.execute(
                "UPDATE appointments SET status=%s WHERE id=%s",
                (new_status, appointment_id)
            )
            
            message = f"Your appointment {appointment_id} has been approved by the lawyer {lawyer_name}."
            db.single_insert("""
                INSERT INTO notifications (login_id, message, is_read)
                VALUES (%s, %s, 0)
            """, (appt['login_id'], message))
            
            flash(f"Appointment approved successfully!", "success")
        else:
            db.execute(
                "UPDATE appointments SET status=%s WHERE id=%s",
                (new_status, appointment_id)
            )
            flash(f"Appointment {new_status.lower()} successfully!", "success")

    except Exception as e:
        print("❌ Error:", e)
        flash("Error updating appointment status.", "danger")

    return redirect(url_for('lawyer_appointments'))

@app.route('/user/respond_reschedule/<int:appointment_id>', methods=['POST'])
def respond_reschedule(appointment_id):
    """Handle user accepting or declining reschedule request"""
    db = Database()
    
    login_id = session.get('login_id')
    if not login_id:
        flash("Please login first.", "danger")
        return redirect(url_for('login'))
    
    response = request.form.get('response')  # 'accept' or 'decline'
    
    # Fetch appointment
    appt = db.fetchone(
        "SELECT * FROM appointments WHERE id=%s AND login_id=%s AND status='Reschedule Request'",
        (appointment_id, login_id)
    )
    
    if not appt:
        flash("Reschedule request not found.", "danger")
        return redirect(url_for('booking_status'))
    
    try:
        if response == 'accept':
            # Change status to 'Request' so lawyer can see and approve it
            db.execute(
                "UPDATE appointments SET status=%s WHERE id=%s",
                ('Request', appointment_id)
            )
            
            # Notify lawyer that client accepted reschedule
            try:
                # Get client's name
                user_record = db.fetchone("SELECT full_name FROM users WHERE login_id = %s", (login_id,))
                client_name = user_record['full_name'] if user_record else "The client"

                # appt['lawyer_id'] is available from the fetchone call above
                law_record = db.fetchone("SELECT login_id FROM lawyers WHERE id = %s", (appt['lawyer_id'],))
                if law_record:
                    notif_msg = f"Client {client_name} has accepted your reschedule request for appointment #{appointment_id}."
                    db.single_insert("""
                        INSERT INTO notifications (login_id, message, is_read)
                        VALUES (%s, %s, 0)
                    """, (law_record['login_id'], notif_msg))
            except Exception as e:
                print(f"Error notifying lawyer of reschedule acceptance: {e}")

            flash("Reschedule request accepted! Lawyer will review it.", "success")
            
        elif response == 'decline':
            # Delete the reschedule request
            db.execute("DELETE FROM appointments WHERE id=%s", (appointment_id,))
            flash("Reschedule request declined. You can book another lawyer.", "info")
        else:
            flash("Invalid response.", "danger")
    
    except Exception as e:
        print(f"Error: {e}")
        flash("Error processing reschedule request.", "danger")
    
    return redirect(url_for('booking_status'))

@app.route('/user/notifications')
def user_notifications():
    login_id = session.get('login_id')
    if not login_id:
        flash("Please login first.", "danger")
        return redirect(url_for('login'))

    notifications = db.fetchall("""
        SELECT id, message, is_read, created_at 
        FROM notifications 
        WHERE login_id=%s 
        ORDER BY created_at DESC
    """, (login_id,))

    return render_template("user/notifications.html", notifications=notifications)

   
@app.route('/user/mark_read/<int:notif_id>')
def mark_read(notif_id):
    db.execute("UPDATE notifications SET is_read=1 WHERE id=%s", (notif_id,))
    return "OK"


#---------------------------LAWYER NOTIFICATIONS---------------------------

@app.route('/lawyer/notifications')
def lawyer_notifications():
    login_id = session.get('login_id')
    if not login_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify([]), 401
        flash("Please login first.", "danger")
        return redirect(url_for('login'))

    notifications = db.fetchall("""
        SELECT id, message, is_read, created_at 
        FROM notifications 
        WHERE login_id=%s 
        ORDER BY created_at DESC
    """, (login_id,))

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
        return jsonify(notifications)

    return render_template("lawyer/notifications.html", notifications=notifications)

@app.route('/lawyer/mark_read/<int:notif_id>')
def lawyer_mark_read(notif_id):
    login_id = session.get('login_id')
    if not login_id:
        return "Unauthorized", 401
    
    db.execute("UPDATE notifications SET is_read=1 WHERE id=%s AND login_id=%s", (notif_id, login_id))
    return "OK"

@app.route('/user/mark_all_read')
def user_mark_all_read():
    login_id = session.get('login_id')
    if login_id:
        db.execute("UPDATE notifications SET is_read=1 WHERE login_id=%s", (login_id,))
    return "OK"

@app.route('/lawyer/mark_all_read')
def lawyer_mark_all_read():
    login_id = session.get('login_id')
    if login_id:
        db.execute("UPDATE notifications SET is_read=1 WHERE login_id=%s", (login_id,))
    return "OK"


@app.route('/lawyer/case_details/<category>/<int:case_id>')
def case_details(category, case_id):
    db = Database()

    # Determine which table to use and evidence type
    table = None
    evidence_type = None
    if category == 'crime':
        table = 'crimes'
        evidence_type = 'crime'
    elif category == 'missing_person':
        table = 'missing_persons'
        evidence_type = 'missing_person'
    elif category == 'stolen_property':
        table = 'stolen_property'
        evidence_type = 'stolen_property'
    else:
        return jsonify({'error': 'Invalid category'}), 400

    # Fetch full record
    query = f"SELECT * FROM {table} WHERE id = %s"
    details = db.fetchone(query, (case_id,))

    if not details:
        return jsonify({'error': 'No details found'}), 404

    # fetch evidence paths if any
    try:
        evs = db.fetchall(
            "SELECT file_path FROM evidence WHERE reference_id=%s AND evidence_type=%s",
            (case_id, evidence_type)
        )
        files = []
        for ev in evs:
            try:
                files.append(crypto.decrypt(ev['file_path']))
            except Exception:
                continue
        if files:
            details['evidence_files'] = files
    except Exception:
        pass

    return jsonify(details)

#----------------------appoinment approval end---------------------------

# Client Requests / Messages
@app.route('/lawyer/client_requests')
def client_requests():
   
    return render_template('lawyer/client_requests.html')

#------------------------------lawyer my cases---------------------------


# ------------------------------- Lawyer Cases Start -------------------------------

@app.route('/lawyer/cases')
def lawyer_cases():
    db = Database()

    # ✅ Step 1: Ensure lawyer is logged in
    login_id = session.get('login_id')
    if not login_id:
        flash("Please log in as a lawyer to view your cases.", "danger")
        return redirect(url_for('login'))

    # ✅ Step 2: Get lawyer_id
    lawyer = db.fetchone("SELECT id FROM lawyers WHERE login_id = %s", (login_id,))
    if not lawyer:
        flash("Lawyer profile not found.", "danger")
        return redirect(url_for('dashboard'))

    lawyer_id = lawyer['id']

    # ✅ Step 3: Fetch approved cases
    approved_cases_query = """
        SELECT 
            a.id AS appointment_id,
            a.case_id,
            u.full_name AS client_name,
            u.phone AS client_phone,
            a.category,
            DATE(a.appointment_datetime) AS appointment_date,
            TIME_FORMAT(a.appointment_datetime, '%%h:%%i %%p') AS appointment_time,
            a.status
        FROM appointments a
        INNER JOIN users u ON a.login_id = u.login_id
        WHERE a.lawyer_id = %s AND a.status NOT IN ('Rejected', 'Request', 'Closed')
        ORDER BY a.appointment_datetime DESC
    """
    approved_cases = db.fetchall(approved_cases_query, (lawyer_id,))
    

    # ✅ Step 4: Get all evidence files for multiple categories
    evidence_query = """
        SELECT reference_id AS case_id, file_path, evidence_type
        FROM evidence
        WHERE evidence_type IN ('crime', 'missing_person', 'stolen_property')
    """
    all_evidence = db.fetchall(evidence_query)

    # ✅ Step 5: Group evidence by both case_id and evidence_type
    # evidence_map = {}
    # for ev in all_evidence:
    #     key = (ev['case_id'], ev['evidence_type'])
    #     if key not in evidence_map:
    #         evidence_map[key] = []
    #     evidence_map[key].append(ev['file_path'])

    evidence_map = {}

    for ev in all_evidence:
        key = (ev['case_id'], ev['evidence_type'])

        try:
            decrypted_path = crypto.decrypt(ev['file_path'])
        except Exception:
            continue  # skip corrupted evidence safely

        if key not in evidence_map:
            evidence_map[key] = []

        evidence_map[key].append(decrypted_path)


        

    # ✅ Step 6: Attach relevant evidence to each case based on category + case_id
    for case in approved_cases:
        case_id = case['case_id']
        # Map appointment category to evidence_type
        if case['category'].lower() in ['crime','crime']:
            evidence_type = 'crime'
        elif case['category'].lower() in ['missing_person', 'missing']:
            evidence_type = 'missing_person'
        elif case['category'].lower() in ['stolen_property', 'stolen']:
            evidence_type = 'stolen_property'
        else:
            evidence_type = None

        case['evidence_files'] = evidence_map.get((case_id, evidence_type), [])

    # ✅ Step 7: Fetch closed cases
    closed_query = """
        SELECT 
            a.id AS appointment_id,
            a.case_id,
            u.full_name AS client_name,
            u.phone AS client_phone,
            a.category,
            DATE(a.appointment_datetime) AS appointment_date,
            TIME_FORMAT(a.appointment_datetime, '%%h:%%i %%p') AS appointment_time,
            a.status
        FROM appointments a
        INNER JOIN users u ON a.login_id = u.login_id
        WHERE a.lawyer_id = %s AND a.status = 'Closed'
        ORDER BY a.appointment_datetime DESC
    """
    closed_cases = db.fetchall(closed_query, (lawyer_id,))

    return render_template(
        'lawyer/cases.html',
        approved_cases=approved_cases,
        closed_cases=closed_cases
    )


# ✅ Update case status (mark as closed)
@app.route('/lawyer/update_case_status', methods=['POST'])
def update_case_status():
    db = Database()

    lawyer_login_id = session.get('login_id')
    if not lawyer_login_id:
        flash("Please log in first.", "danger")
        return redirect(url_for('login'))

    appointment_id = request.form.get('appointment_id')
    new_status = request.form.get('new_status', 'Closed')

    if not appointment_id:
        flash("Invalid case.", "danger")
        return redirect(url_for('lawyer_cases'))

    try:
        query = "UPDATE appointments SET status = %s WHERE id = %s"
        db.execute(query, (new_status, appointment_id))
        flash("Case marked as Closed successfully!", "success")
    except Exception as e:
        print("❌ Error updating case:", e)
        flash("Error updating case status.", "danger")

    return redirect(url_for('lawyer_cases'))

@app.route('/lawyer/update_hearing_status', methods=['POST'])
def update_hearing_status():
    appointment_id = request.form.get("appointment_id")
    hearing_status = request.form.get("hearing_status")
    
    # Get appointment details
    appointment = db.fetchone("""
        SELECT a.id, a.login_id, a.case_id, a.category, a.lawyer_id,
               u.full_name AS client_name
        FROM appointments a
        INNER JOIN users u ON a.login_id = u.login_id
        WHERE a.id = %s
    """, (appointment_id,))
    
    if not appointment:
        flash("Appointment not found.", "danger")
        return redirect(url_for("lawyer_cases"))
    
    try:
        # Store the hearing status update request with pending status and get its id
        hsu_id = db.executeAndReturnId("""
            INSERT INTO hearing_status_updates 
            (appointment_id, lawyer_id, requested_status, client_id, status, created_at)
            VALUES (%s, %s, %s, %s, 'pending', NOW())
        """, (appointment_id, appointment['lawyer_id'], hearing_status, appointment['login_id']))

        # Notify admin about the hearing status update request (use existing notifications schema)
        message = (
            f"Lawyer has requested to update hearing status for case (appointment #{appointment_id}) "
            f"with client {appointment['client_name']} to '{hearing_status}'. Please verify and approve."
        )
        # Existing notifications inserts throughout the app use only (login_id, message, is_read)
        db.single_insert("""
            INSERT INTO notifications (login_id, message, is_read)
            VALUES (%s, %s, 0)
        """, ('admin', message))

        flash("Hearing status update request sent to admin for verification.", "info")
    except Exception as e:
        print(f"❌ Error creating hearing status update request: {e}")
        flash("Error processing hearing status update request.", "danger")
    
    return redirect(url_for("lawyer_cases"))



# ------------------------------- Lawyer Cases End -------------------------------


# ------------------------------- Lawyer Cases End -------------------------------







#===============================LAWYER DASHBOARD END=============================

#==============================police DASHBOARD START=============================
import calendar
# ===============================
# POLICE DASHBOARD
# ===============================
@app.route("/police/dashboard")
def police_dashboard():

    # Optional: protect route (recommended)
    if "username" not in session:
        return redirect(url_for("login"))

    # ---------------------------
    # TOTAL COUNTS
    # ---------------------------
    lawyer_count = db.fetchone("SELECT COUNT(*) AS total FROM lawyers")["total"]
    crime_count = db.fetchone("SELECT COUNT(*) AS total FROM crimes")["total"]
    missing_count = db.fetchone("SELECT COUNT(*) AS total FROM missing_persons")["total"]
    property_count = db.fetchone("SELECT COUNT(*) AS total FROM stolen_property")["total"]

    # ---------------------------
    # MONTHLY CRIME STATS (Last 6 Months)
    # ---------------------------
    monthly_data = db.fetchall("""
        SELECT 
            MONTH(created_at) AS month,
            COUNT(*) AS total
        FROM crimes
        WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
        GROUP BY MONTH(created_at)
        ORDER BY MONTH(created_at)
    """)

    # Prepare chart data
    months = []
    crime_values = []

    # Create dictionary for easy lookup
    month_dict = {row["month"]: row["total"] for row in monthly_data}

    # Last 6 months dynamically
    current_month = datetime.now().month
    for i in range(5, -1, -1):
        month_number = (current_month - i - 1) % 12 + 1
        months.append(calendar.month_abbr[month_number])
        crime_values.append(month_dict.get(month_number, 0))

    return render_template(
        "police/dashboard.html",
        lawyer_count=lawyer_count,
        crime_count=crime_count,
        missing_count=missing_count,
        property_count=property_count,
        months=months,
        crime_values=crime_values
    )


# ==========================================
# VIEW REGISTERED CRIMES
# ==========================================
@app.route("/police/registered_crime")
def registered_crime_police():

    # Protect route (only logged-in police/admin)
    if "username" not in session:
        return redirect(url_for("login"))

    crimes = db.fetchall("""
        SELECT 
            id,
            crime_type,
            crime_date,
            location,
            crimespot,
            reporter_name,
            reporter_contact,
            status
        FROM crimes
        ORDER BY id DESC
    """)

    return render_template(
        "police/registered_crime.html",
        crimes=crimes
    )


# ==========================================
# UPDATE CRIME STATUS
# ==========================================
@app.route("/police/update_crime_status/<int:crime_id>/<string:new_status>")
def update_crime_status_police(crime_id, new_status):

    if "username" not in session:
        return redirect(url_for("login"))

    # Allow only specific statuses
    allowed_status = ["Investigating", "Closed"]

    if new_status not in allowed_status:
        flash("Invalid status update.", "danger")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Invalid status'}), 400
        return redirect(url_for("registered_crime_police"))

    try:
        db.execute(
            "UPDATE crimes SET status=%s WHERE id=%s",
            (new_status, crime_id)
        )
        
        # Check if request is AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'new_status': new_status})

        flash("Crime status updated successfully!", "success")

    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': str(e)}), 500
        flash("Error updating status.", "danger")

    return redirect(url_for("registered_crime_police"))

# ==========================================
# VIEW REGISTERED MISSING PERSONS
# ==========================================
@app.route("/registered_missing")
def registered_missing_police():

    if "username" not in session:
        return redirect(url_for("login"))

    persons = db.fetchall("""
        SELECT 
            id,
            name,
            gender,
            age,
            height,
            weight,
            skintone,
            hair,
            last_seen,
            location,
            status
        FROM missing_persons
        ORDER BY id DESC
    """)

    return render_template(
        "police/registered_missing.html",
        persons=persons
    )


# ==========================================
# UPDATE MISSING PERSON STATUS
# ==========================================
@app.route("/police/update_missing_status/<int:person_id>/<string:new_status>")
def update_missing_status_police(person_id, new_status):

    if "username" not in session:
        return redirect(url_for("login"))

    allowed_status = ["Investigating", "Closed"]

    if new_status not in allowed_status:
        flash("Invalid status update.", "danger")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Invalid status'}), 400
        return redirect(url_for("registered_missing_police"))

    try:
        db.execute(
            "UPDATE missing_persons SET status=%s WHERE id=%s",
            (new_status, person_id)
        )
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'new_status': new_status})

        flash("Missing person status updated successfully!", "success")

    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': str(e)}), 500
        flash("Error updating status.", "danger")

    return redirect(url_for("registered_missing_police"))   

# ==========================================
# VIEW REGISTERED STOLEN PROPERTY
# ==========================================
@app.route("/registered_stolenitem")
def registered_stolenitem_police():

    if "username" not in session:
        return redirect(url_for("login"))

    properties = db.fetchall("""
        SELECT 
            id,
            item_name,
            category,
            serial_number,
            date_stolen,
            location,
            owner_contact,
            status
        FROM stolen_property
        ORDER BY id DESC
    """)

    return render_template(
        "police/registered_stolenitem.html",
        properties=properties
    )


# ==========================================
# UPDATE PROPERTY STATUS
# ==========================================
@app.route("/police/update_property_status/<int:property_id>/<string:new_status>")
def update_property_status_police(property_id, new_status):

    if "username" not in session:
        return redirect(url_for("login"))

    allowed_status = ["Investigating", "Closed"]

    if new_status not in allowed_status:
        flash("Invalid status update.", "danger")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Invalid status'}), 400
        return redirect(url_for("registered_stolenitem_police"))

    try:
        db.execute(
            "UPDATE stolen_property SET status=%s WHERE id=%s",
            (new_status, property_id)
        )
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'new_status': new_status})

        flash("Property status updated successfully!", "success")

    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': str(e)}), 500
        flash("Error updating property status.", "danger")

    return redirect(url_for("registered_stolenitem_police")) 

#=====================================LOG IN PAGE START====================================


# =========================
# LOGIN
# =========================

@app.route('/login', methods=['GET','POST'])
def login():

    if request.method == 'POST':

        username = request.form['username']
        password = request.form['password']

        try:

            query = "SELECT id,username,password,role FROM login WHERE username=%s"
            user = db.fetchone(query,(username,))

            if user and user['password'] == password:

                session['login_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']

                flash("Login successfully!","success")
                flash(f"Welcome back {user['username']}!","success")

                if user['role']=="admin":
                    return redirect(url_for('admin_dashboard'))

                elif user['role']=="lawyer":
                    return redirect(url_for('lawyer_dashboard'))

                elif user['role']=="police":
                    return redirect(url_for('police_dashboard'))

                else:
                    return redirect(url_for('user_dashboard'))

            else:

                flash("Invalid username or password","danger")

        except Exception as e:

            print("Database error:",e)
            flash("Database error occurred","danger")

    return render_template('guest/login.html')


#-------------------------------forgot password start------------------------------
# This section implements a secure OTP-based password reset mechanism. It includes:
# 1. An endpoint to request an OTP, which generates a random 6-digit code, stores it with an expiration time, and emails it to the user.
# 2. An endpoint to verify the OTP entered by the user, ensuring it matches and hasn't expired.
# 3. An endpoint to reset the password, which checks that the OTP was verified before allowing the password change.
# The OTPs are stored in-memory for simplicity. The email sending uses Gmail's SMTP server, and you must configure the admin email and app password for it to work.
# Note: Remember to replace the ADMIN_EMAIL and ADMIN_APP_PASS with your actual Gmail address and app password. Also, ensure that the Gmail account has "Less secure app access" enabled or use an app password if 2FA is on.
# The HTML email template is designed to be visually appealing and responsive, providing a clear and professional look for the OTP email.
# Security considerations:
# - OTPs are time-limited (10 minutes) and stored securely in-memory.
# - The password reset process requires OTP verification before allowing a password change.



# ─── CONFIG ──────────────────────────────────────────────
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
ADMIN_EMAIL   = "adminjusticesphere@gmail.comve"   # ← change this
ADMIN_APP_PASS = "xuof zzap vepf smur"   # ← change this (Gmail App Password)

# In-memory OTP store  {email: {"otp": "123456", "expires": timestamp, "verified": bool}}
otp_store = {}
# ─────────────────────────────────────────────────────────


def send_otp_email(to_email, otp):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "JUSTICESphere — Password Reset OTP"
    msg["From"]    = ADMIN_EMAIL
    msg["To"]      = to_email

    html = f"""
    <div style="font-family:'Segoe UI',sans-serif;max-width:480px;margin:auto;
                border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.12);">
      <div style="background:linear-gradient(135deg,#c62828,#d32f2f);padding:30px;text-align:center;">
        <h1 style="color:#fff;margin:0;font-size:1.6rem;">JUSTICESphere</h1>
        <p style="color:rgba(255,255,255,.85);margin:6px 0 0;">Password Reset</p>
      </div>
      <div style="background:#fff;padding:32px;text-align:center;">
        <p style="color:#333;margin-bottom:8px;">Your One-Time Password is:</p>
        <div style="font-size:2.5rem;font-weight:700;letter-spacing:10px;
                    color:#c62828;margin:12px 0;">{otp}</div>
        <p style="color:#888;font-size:.85rem;">This OTP expires in <strong>10 minutes</strong>.</p>
        <p style="color:#888;font-size:.82rem;margin-top:16px;">
          If you did not request this, please ignore this email.
        </p>
      </div>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(ADMIN_EMAIL, ADMIN_APP_PASS)
        server.sendmail(ADMIN_EMAIL, to_email, msg.as_string())


@app.route('/forgot_password')
def forgot_password():
    return render_template('guest/forgot_password.html')


@app.route('/forgot_password/send_otp', methods=['POST'])
def send_otp():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()

    try:
        user = db.fetchone("SELECT id FROM login WHERE email=%s", (email,))
        if not user:
            return jsonify(success=False, message="No account found with that email.")

        otp     = str(random.randint(100000, 999999))
        expires = time.time() + 600  # 10 minutes

        otp_store[email] = {"otp": otp, "expires": expires, "verified": False}

        send_otp_email(email, otp)
        return jsonify(success=True)

    except Exception as e:
        print("send_otp error:", e)
        return jsonify(success=False, message="Failed to send OTP. Try again.")


@app.route('/forgot_password/verify_otp', methods=['POST'])
def verify_otp():
    data  = request.get_json()
    email = data.get('email', '').strip().lower()
    otp   = data.get('otp', '').strip()

    record = otp_store.get(email)
    if not record:
        return jsonify(success=False, message="No OTP requested for this email.")

    if time.time() > record['expires']:
        otp_store.pop(email, None)
        return jsonify(success=False, message="OTP has expired. Please request a new one.")

    if record['otp'] != otp:
        return jsonify(success=False, message="Incorrect OTP.")

    otp_store[email]['verified'] = True
    return jsonify(success=True)


@app.route('/forgot_password/reset_password', methods=['POST'])
def reset_password():
    data         = request.get_json()
    email        = data.get('email', '').strip().lower()
    new_password = data.get('new_password', '')

    record = otp_store.get(email)
    if not record or not record.get('verified'):
        return jsonify(success=False, message="OTP not verified. Please restart.")

    if time.time() > record['expires']:
        otp_store.pop(email, None)
        return jsonify(success=False, message="Session expired. Please restart.")

    try:
        db.execute(
            "UPDATE login SET password=%s WHERE email=%s",
            (new_password, email)
        )
        otp_store.pop(email, None)
        return jsonify(success=True)

    except Exception as e:
        print("reset_password error:", e)
        return jsonify(success=False, message="Database error. Try again.")





#===================================LOGIN PAGE END=========================================

# =============================SIGNUP PAGE START(With phone number)=============================

app.config['USER_UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'users')
app.config['LAWYER_UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'lawyers')
app.config['POLICE_UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'police')

os.makedirs(app.config['USER_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['LAWYER_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['POLICE_UPLOAD_FOLDER'], exist_ok=True)





ALLOWED_EXTENSIONS = {'jpg','jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS




@app.route('/signup', methods=['GET','POST'])
def signup():

    if request.method == 'POST':

        full_name = request.form['full_name']
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        phone = request.form['phone']
        country_code = request.form['country_code']
        role = request.form['role']

        # phone = country_code + phone

        bar_number = request.form.get('bar_council_number')
        police_id = request.form.get('police_id')
        profile_image = request.files.get('profile_image')

        try:

            if password != confirm_password:
                flash("Passwords do not match!", "danger")
                return redirect(url_for('signup'))

            check_user = db.fetchone(
                "SELECT id FROM login WHERE username=%s",
                (username,)
            )

            if check_user:
                flash("Username already exists!", "danger")
                return redirect(url_for('signup'))

            check_email = db.fetchone(
                "SELECT id FROM login WHERE email=%s",
                (email,)
            )

            if check_email:
                flash("Email already registered!", "danger")
                return redirect(url_for('signup'))

            if not profile_image or not allowed_file(profile_image.filename):
                flash("Only JPG or PNG images allowed!", "danger")
                return redirect(url_for('signup'))

            filename = secure_filename(profile_image.filename)

            if role == "lawyer":
                folder = app.config['LAWYER_UPLOAD_FOLDER']
            elif role == "police":
                folder = app.config['POLICE_UPLOAD_FOLDER']
            else:
                folder = app.config['USER_UPLOAD_FOLDER']

            save_path = os.path.join(folder, filename)
            profile_image.save(save_path)

            login_id = db.executeAndReturnId(
                "INSERT INTO login (username,password,email,role) VALUES (%s,%s,%s,%s)",
                (username,password,email,role)
            )

            if role == "user":

                db.execute(
                "INSERT INTO users (full_name,country_code,phone,image,login_id) VALUES (%s,%s,%s,%s,%s)",
                (full_name,country_code,phone,filename,login_id)
                )

            elif role == "lawyer":

                db.execute(
                """INSERT INTO lawyers
                (full_name,country_code,phone,email,image,bar_council_number,login_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (full_name,country_code,phone,email,filename,bar_number,login_id)
                )

            elif role == "police":

                db.execute(
                """INSERT INTO police
                (full_name,country_code,phone,image,police_unique_id,login_id)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (full_name,country_code,phone,filename,police_id,login_id)
                )

            flash("Account created successfully!","success")
            return redirect(url_for('login'))

        except Exception as e:

            print("ERROR:",e)
            flash("Server error occurred!","danger")

    return render_template('guest/signup.html')

#======================================SIGNUP PAGE END=======================

#===============================LOGOUT=======================================

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


#=========================LOGOUT END===================================

#===============================FOR RUN================================
if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0')
