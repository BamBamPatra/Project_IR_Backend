from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token, jwt_required
import bcrypt
import pandas as pd
from elasticsearch import Elasticsearch
from sklearn.feature_extraction.text import TfidfVectorizer
from flask_cors import CORS
import pickle
from threading import Thread

# Authen.py app
auth_app = Flask(__name__)
auth_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///account.db'  # Use new account.db
auth_app.config['SECRET_KEY'] = 'your_secret_key'
auth_app.config['JWT_SECRET_KEY'] = 'your_jwt_secret_key'  # JWT secret key
db = SQLAlchemy(auth_app)
jwt = JWTManager(auth_app)

# Search.py app
search_app = Flask(__name__)
CORS(search_app)
search_app.es_client = Elasticsearch(
    "https://localhost:9200",
    basic_auth=("elastic", "Iv0CDItraOJ7siTp4kNl"),
    ca_certs="~/http_ca.crt",
    verify_certs=True
)
CORS(auth_app, origins=["http://localhost:5173"])
CORS(search_app, origins=["http://localhost:5173"])

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

def create_tables():
    with auth_app.app_context():
        print(f"Database URI: {auth_app.config['SQLALCHEMY_DATABASE_URI']}")  # Debug log
        print("Creating tables in the database.")

        # Create all tables (it will create the user table in account.db)
        db.create_all()

        if not User.query.first():  # If no users exist, create the default user
            default_user = User(
                email="admin@example.com",
                password=bcrypt.hashpw("password".encode(), bcrypt.gensalt()),
                username="admin"  # Default username
            )
            db.session.add(default_user)
            db.session.commit()
            print("Created default user: admin@example.com")
        else:
            print("Database already initialized.")

@auth_app.route('/register', methods=['POST'])
def register():
    data = request.get_json()

    print("Received data:", data)  # Debug line to see the data

    # Check if request data exists and contains required fields
    if not data or 'email' not in data or 'password' not in data or 'username' not in data:
        return jsonify({"message": "Missing email, password or username"}), 400


    # Check if email already exists
    if User.query.filter_by(email=data['email']).first():
        return jsonify({"message": "Email already exists!"}), 400

    # Hash the password before storing
    hashed_password = bcrypt.hashpw(data['password'].encode(), bcrypt.gensalt())

    new_user = User(email=data['email'], password=hashed_password, username=data['username'])
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "User created successfully!"}), 201


from flask_jwt_extended import create_access_token


@auth_app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data['email']).first()

    if not user:
        return jsonify({"message": "User not found!"}), 404

    if bcrypt.checkpw(data['password'].encode(), user.password):
        access_token = create_access_token(identity=user.id)
        return jsonify({
            "access_token": access_token,
            "username": user.username
        }), 200
    else:
        return jsonify({"message": "Invalid credentials!"}), 401

@auth_app.route('/users', methods=['GET'])
def get_all_users():
    users = User.query.all()
    user_list = [{'id': user.id, 'email': user.email, 'username': user.username} for user in users]  # เพิ่ม 'username' ใน user_list

    return jsonify(user_list), 200

@auth_app.route('/user/<int:id>', methods=['GET'])
def get_user_by_id(id):
    user = User.query.get(id)
    if user:
        return jsonify({'id': user.id, 'email': user.email}), 200
    else:
        return jsonify({"message": "User not found!"}), 404


@auth_app.route('/user/<int:id>', methods=['DELETE'])
def delete_user_by_id(id):
    user = User.query.get(id)
    if user:
        db.session.delete(user)
        db.session.commit()
        return jsonify({"message": f"User with id {id} has been deleted!"}), 200
    else:
        return jsonify({"message": "User not found!"}), 404


# Images
def clean_images_column(df):
    df['Images'] = df['Images'].apply(lambda x: re.findall(r'https://[^"]+', x)[0] if isinstance(x, str) and re.findall(r'https://[^"]+', x) else None)
    return df

# Keywords
def clean_keywords_column(df):
    df['Keywords'] = df['Keywords'].apply(lambda x: ', '.join(re.findall(r'"([^"]*)"', x)))
    return df

# RecipeIngredientParts
def clean_ingredient_parts_column(df):
    df['RecipeIngredientParts'] = df['RecipeIngredientParts'].apply(lambda x: ', '.join(re.findall(r'"([^"]*)"', x)))
    return df

# RecipeIngredientQuantities
def clean_ingredient_quantities_column(df):
    df['RecipeIngredientQuantities'] = df['RecipeIngredientQuantities'].apply(lambda x: ', '.join(re.findall(r'"([^"]*)"', x)))
    return df

# RecipeInstructions
def clean_instructions_column(df):
    df['RecipeInstructions'] = df['RecipeInstructions'].apply(lambda x: ', '.join(re.findall(r'"([^"]*)"', x)))
    return df

# Indexer
class Indexer:
    def __init__(self, file_path, pkl_path="indexer.pkl"):
        self.pkl_path = pkl_path
        try:
            with open(self.pkl_path, "rb") as f:
                data = pickle.load(f)
                self.df = data["df"]
                self.tfidf_vectorizer = data["vectorizer"]
                self.tfidf_matrix = data["matrix"]
                print("Loaded indexer from pkl.")
        except FileNotFoundError:
            self.df = pd.read_csv(file_path)
            self.df.fillna("", inplace=True)

            self.df = clean_images_column(self.df)
            self.df = clean_keywords_column(self.df)
            self.df = clean_ingredient_parts_column(self.df)
            self.df = clean_ingredient_quantities_column(self.df)
            self.df = clean_instructions_column(self.df)

            self.tfidf_vectorizer = TfidfVectorizer(stop_words='english')
            self.index()

            with open(self.pkl_path, "wb") as f:
                pickle.dump({
                    "df": self.df,
                    "vectorizer": self.tfidf_vectorizer,
                    "matrix": self.tfidf_matrix
                }, f)
                print("Saved indexer to pkl.")

    def index(self):
        self.df['combined_text'] = self.df['Name'] + " " + self.df['Description'] + " " + self.df['RecipeInstructions']
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(self.df['combined_text'])
        for idx, row in self.df.iterrows():
            doc = row.to_dict()
            search_app.es_client.index(index='custom', id=row["RecipeId"], document=doc)

indexer = Indexer("resource/recipes.csv")

@search_app.route('/search', methods=['GET'])
@search_app.route('/search/<int:recipe_id>', methods=['GET'])
def search(recipe_id=None):
    try:
        # If recipe_id is provided in the URL, search for a specific recipe
        if recipe_id:
            query_body = {"match": {"RecipeId": recipe_id}}
        else:
            query_term = request.args.get('query', '')
            query_body = {"match": {"combined_text": query_term}} if query_term else {"match_all": {}}

        # Execute the search query
        results = search_app.es_client.search(index='custom', size=100, query=query_body)

        # Check if no results are found
        if results['hits']['total']['value'] == 0:
            return jsonify({"message": "No recipes found!"}), 404

        # Return the search results
        response = {
            'status': 'success',
            'total_hit': results['hits']['total']['value'],
            'results': [hit["_source"] for hit in results['hits']['hits']]
        }
    except Exception as e:
        response = {'status': 'error', 'message': str(e)}

    return jsonify(response)

def run_auth():
    auth_app.run(host="127.0.0.1", port=5001, debug=False)

def run_search():
    search_app.run(host="127.0.0.1", port=5000, debug=False)

if __name__ == "__main__":
    create_tables()
    Thread(target=run_auth).start()
    Thread(target=run_search).start()