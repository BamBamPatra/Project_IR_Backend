from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token, jwt_required
import bcrypt

# สร้าง app, database และ jwt manager
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'  # ใช้ SQLite ในตัว
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['JWT_SECRET_KEY'] = 'your_jwt_secret_key'  # secret key สำหรับ JWT
db = SQLAlchemy(app)
jwt = JWTManager(app)

# สร้าง model สำหรับผู้ใช้
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

# สร้างฐานข้อมูล
@app.before_first_request
def create_tables():
    db.create_all()

# Endpoint สำหรับการลงทะเบียน
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()

    # เช็คว่าอีเมลมีอยู่ในระบบหรือยัง
    if User.query.filter_by(email=data['email']).first():
        return jsonify({"message": "Email already exists!"}), 400

    # เข้ารหัสรหัสผ่าน
    hashed_password = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt())

    # สร้างผู้ใช้ใหม่
    new_user = User(email=data['email'], password=hashed_password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "User created successfully!"}), 201

# Endpoint สำหรับการเข้าสู่ระบบ (Login)
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()

    # ค้นหาผู้ใช้จากอีเมล
    user = User.query.filter_by(email=data['email']).first()

    if not user:
        return jsonify({"message": "User not found!"}), 404

    # ตรวจสอบรหัสผ่าน
    if bcrypt.checkpw(data['password'].encode('utf-8'), user.password.encode('utf-8')):
        # ถ้าถูกต้อง สร้าง JWT Token
        access_token = create_access_token(identity=user.id)
        return jsonify(access_token=access_token), 200
    else:
        return jsonify({"message": "Invalid credentials!"}), 401

# Endpoint ที่ต้องการ authentication
@app.route('/dashboard', methods=['GET'])
@jwt_required()
def dashboard():
    return jsonify(message="Welcome to the dashboard!")

if __name__ == '__main__':
    app.run(debug=True)
