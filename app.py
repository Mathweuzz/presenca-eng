from flask import Flask, render_template, request, redirect, session, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload
from flask_migrate import Migrate
from datetime import datetime
import csv
import os
import bcrypt
import secrets
from pytz import timezone

app = Flask(__name__)
db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'database.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SECRET_KEY'] = 'chave_secreta'  # Defina sua chave secreta aqui
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Modelos de Banco de Dados
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration = db.Column(db.String(9), unique=True)
    name = db.Column(db.String(100))
    password_hash = db.Column(db.String(64))
    role = db.Column(db.String(10))
    classes = db.relationship('Class', backref='teacher', lazy='dynamic')
    attended_classes = db.relationship('Attendance', backref='students', lazy='dynamic')

class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(4), unique=True)
    name = db.Column(db.String(100))
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Attendance(db.Model):
    attendance_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False)
    class_date = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('User', backref='attendance_records')
    class_obj = db.relationship('Class', backref='attendances')

    def __repr__(self):
        return f"<Attendance {self.attendance_id}>"


@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        registration = request.form['registration']
        name = request.form['name']  # Adicione esta linha para obter o nome do formulário
        password = request.form['password']
        role = request.form['role']
        password_hash = hash_password(password)
        user = User(registration=registration, name=name, password_hash=password_hash, role=role)
        db.session.add(user)
        db.session.commit()
        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        registration = request.form['registration']
        password = request.form['password']
        user = User.query.filter_by(registration=registration).first()
        if user and check_password(user.password_hash, password):
            session['user_id'] = user.id
            return redirect('/dashboard')
        else:
            return 'Usuário ou senha inválidos'
    return render_template('login.html')

@app.route('/logout')
def logout():
    # Remover a sessão do usuário
    session.pop('user_id', None)

    # Redirecionar para a página de login
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user.role == 'student':
            attended_classes = user.attended_classes
            return render_template('student_dashboard.html', user=user, attended_classes=attended_classes)
        elif user.role == 'teacher':
            classes = Class.query.filter_by(teacher_id=user_id).all()  # Obtém todas as aulas do professor
            return render_template('teacher_dashboard.html', user=user, classes=classes)
    return redirect('/login')

@app.route('/class_attendance/<int:class_id>')
def class_attendance(class_id):
    class_obj = Class.query.get(class_id)
    if class_obj:
        attendance = Attendance.query.filter_by(class_id=class_id).order_by(Attendance.class_date.desc()).first()
        if attendance:
            return render_template('class_attendance.html', class_obj=class_obj, attendance=attendance)
    return redirect('/dashboard')

@app.route('/generate_class', methods=['POST'])
def generate_class():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user.role == 'teacher':
            class_code = generate_class_code()
            class_name = request.form['class_name']
            new_class = Class(code=class_code, name=class_name, teacher_id=user_id)  # Associe o ID do professor à nova aula
            db.session.add(new_class)
            db.session.commit()
            return redirect('/dashboard')
    return redirect('/login')

@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user.role == 'student':
            class_code = request.form['class_code']
            class_obj = Class.query.filter_by(code=class_code).first()
            if class_obj:
                attendance = Attendance(class_id=class_obj.id)  # Remova o argumento `user_id`
                user.attended_classes.append(attendance)  # Associe o aluno à instância de Attendance
                db.session.commit()
                return redirect('/dashboard')
    return redirect('/login')

@app.route('/download_attendance/<int:class_id>')
def download_attendance(class_id):
    class_obj = Class.query.get(class_id)
    if class_obj:
        attendance = Attendance.query.filter_by(class_id=class_id).order_by(Attendance.class_date.desc()).first()
        if attendance:
            filename = f'attendance_class_{class_obj.id}.csv'
            attendance_data = [['Registro', 'Nome', 'Data', 'Hora']]

            students = User.query.join(Attendance.students).filter(Attendance.class_id == class_id).order_by(User.name).all()
            
            brasil_timezone = timezone('America/Sao_Paulo')  # Define o fuso horário do Brasil

            for student in students:
                registro = student.registration
                nome = student.name
                data_presenca = attendance.class_date.astimezone(brasil_timezone).strftime('%Y-%m-%d')  # Converte para o fuso horário do Brasil
                hora_presenca = attendance.class_date.astimezone(brasil_timezone).strftime('%H:%M:%S')  # Converte para o fuso horário do Brasil
                attendance_data.append([registro, nome, data_presenca, hora_presenca])

            with open(filename, 'w', newline='') as file:
                writer = csv.writer(file)
                writer.writerows(attendance_data)

            return send_file(filename, as_attachment=True)

    return redirect('/dashboard')

@app.route('/delete_class/<int:class_id>', methods=['POST'])
def delete_class(class_id):
    class_obj = Class.query.get(class_id)
    if class_obj:
        # Deleta os registros de presença associados à aula
        Attendance.query.filter_by(class_id=class_id).delete()

        # Deleta a aula
        db.session.delete(class_obj)
        db.session.commit()

    return redirect('/dashboard')



def hash_password(password):
    password = password.encode('utf-8')  # Codifica a senha como bytes
    salt = bcrypt.gensalt()  # Gera um salt aleatório
    hashed_password = bcrypt.hashpw(password, salt)
    return hashed_password.decode('utf-8')  # Decodifica o hash de volta para string

def check_password(hashed_password, user_password):
    hashed_password = hashed_password.encode('utf-8')  # Codifica o hash como bytes
    user_password = user_password.encode('utf-8')  # Codifica a senha como bytes
    return bcrypt.checkpw(user_password, hashed_password)

def generate_class_code():
    class_code = secrets.randbelow(10000)  # Gera um código aleatório de 4 dígitos
    return str(class_code).zfill(4)  # Preenche o código com zeros à esquerda, se necessário

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
