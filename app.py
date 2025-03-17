from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import bcrypt
from elasticsearch import Elasticsearch
from threading import Thread
import re
from flask_jwt_extended import create_access_token
from flask_migrate import Migrate
import requests
from flask_cors import CORS
import time
import pandas as pd
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer


# Authen.py app
auth_app = Flask(__name__)
auth_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///account.db'  # Use new account.db
auth_app.config['SECRET_KEY'] = 'your_secret_key'
auth_app.config['JWT_SECRET_KEY'] = 'your_jwt_secret_key'  # JWT secret key
db = SQLAlchemy(auth_app)
jwt = JWTManager(auth_app)
migrate = Migrate(auth_app, db)

# Search.py app
search_app = Flask(__name__)
CORS(search_app)
search_app.es_client = Elasticsearch(
    "https://localhost:9200",
    basic_auth=("elastic", "Iv0CDItraOJ7siTp4kNl"),
    ca_certs="~/http_ca.crt",
    verify_certs=True
)


CORS(auth_app , origins=["http://localhost:5173"], supports_credentials=True)
CORS(search_app, origins=["http://localhost:5173"], supports_credentials=True)

# ========================================================================
# User and Folder Models
# ========================================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Foreign Key linked to User
    user = db.relationship('User', backref=db.backref('folders', lazy=True))  # Relationship with User
    created_at = db.Column(db.DateTime, default=db.func.now())

class Recipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)


# Table to handle the many-to-many relationship between Folder and Recipe
class FolderRecipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=False)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)

    folder = db.relationship('Folder', backref=db.backref('folder_recipes', lazy=True))
    recipe = db.relationship('Recipe', backref=db.backref('folder_recipes', lazy=True))


def create_tables():
    with auth_app.app_context():
        db.create_all()  # Create all tables (User, Folder, Recipe, FolderRecipe)
        if not User.query.first():
            default_user = User(
                email="admin@example.com",
                password=bcrypt.hashpw("password".encode(), bcrypt.gensalt()),
                username="admin"
            )
            db.session.add(default_user)
            db.session.commit()

# ========================================================================
# User Routes
# ========================================================================

## Register
@auth_app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data or 'email' not in data or 'password' not in data or 'username' not in data:
        return jsonify({"message": "Missing email, password or username"}), 400

    if User.query.filter_by(email=data['email']).first():
        return jsonify({"message": "Email already exists!"}), 400

    hashed_password = bcrypt.hashpw(data['password'].encode(), bcrypt.gensalt())
    new_user = User(email=data['email'], password=hashed_password, username=data['username'])
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "User created successfully!"}), 201

## Login
@auth_app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data['email']).first()

    if not user or not bcrypt.checkpw(data['password'].encode(), user.password):
        return jsonify({"message": "Invalid credentials!"}), 401

    access_token = create_access_token(identity=user.id)

    # Return user info including user_id and access_token
    return jsonify({
        "access_token": access_token,
        "username": user.username,
        "user_id": user.id  # Sending user_id back in the response
    }), 200


# Get all USER
@auth_app.route('/users', methods=['GET'])
def get_all_users():
    users = User.query.all()
    user_list = [{'id': user.id, 'email': user.email, 'username': user.username} for user in users]

    return jsonify(user_list), 200


# Get USER by ID
@auth_app.route('/user/<int:id>', methods=['GET'])
def get_user_by_id(id):
    user = User.query.get(id)
    if user:
        return jsonify({'id': user.id, 'email': user.email}), 200
    else:
        return jsonify({"message": "User not found!"}), 404


# Delete USER by ID
@auth_app.route('/user/<int:id>', methods=['DELETE'])
def delete_user_by_id(id):
    user = User.query.get(id)
    if user:
        db.session.delete(user)
        db.session.commit()
        return jsonify({"message": f"User with id {id} has been deleted!"}), 200
    else:
        return jsonify({"message": "User not found!"}), 404


## Check folder each user
@auth_app.route('/user/<int:user_id>/folders', methods=['GET'])
def get_user_folders_with_recipes(user_id):
    # Step 1: Retrieve the user
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found!"}), 404

    # Step 2: Retrieve all folders for the user
    folders = Folder.query.filter_by(user_id=user_id).all()
    if not folders:
        return jsonify({"message": "No folders found for this user!"}), 404

    folder_data = []

    # Step 3: Process each folder
    for folder in folders:
        # Get recipe IDs from FolderRecipe table
        recipe_ids = (
            db.session.query(FolderRecipe.recipe_id)
            .filter(FolderRecipe.folder_id == folder.id)
            .all()
        )
        recipe_ids = [r[0] for r in recipe_ids]  # Extract IDs from query result

        # Fetch recipe details from external API
        recipe_list = []
        for recipe_id in recipe_ids:
            recipe_data = get_recipe_data(recipe_id)
            recipe_list.append({
                "RecipeId": recipe_id,
                "RecipeName": recipe_data.get('Name', "Unknown Recipe")
            })

        # Step 4: Add folder data to the response
        folder_data.append({
            "FolderId": folder.id,
            "FolderName": folder.name,
            "CreatedAt": folder.created_at,
            "Recipes": recipe_list
        })

    return jsonify(folder_data), 200


def get_recipe_data(recipe_id):
    try:
        response = requests.get(f'http://127.0.0.1:5000/search/{recipe_id}')
        print(f"API Response for recipe {recipe_id}: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Recipe data for {recipe_id}: {data}")
            return data['results'][0] if data.get('results') else {"Name": "Unknown Recipe"}
        return {"Name": "Unknown Recipe"}
    except requests.exceptions.RequestException as e:
        print(f"API request error for recipe {recipe_id}: {e}")
        return {"Name": "Unknown Recipe"}


@auth_app.route('/user/<int:user_id>/folders/<int:folder_id>', methods=['GET'])
def get_user_folder_details(user_id, folder_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found!"}), 404

    folder = Folder.query.filter_by(user_id=user_id, id=folder_id).first()
    if not folder:
        return jsonify({"message": "Folder not found!"}), 404

    # Step 1: Get recipe IDs from FolderRecipe table
    recipe_ids = (
        db.session.query(FolderRecipe.recipe_id)
        .filter(FolderRecipe.folder_id == folder.id)
        .all()
    )
    recipe_ids = [r[0] for r in recipe_ids]  # Extract recipe IDs

    # Step 2: Fetch recipe details from external API
    recipe_list = []
    for recipe_id in recipe_ids:
        recipe_data = get_recipe_data(recipe_id)
        recipe_list.append({
            "RecipeId": recipe_id,
            "RecipeName": recipe_data.get('Name', "Unknown Recipe")
        })

    # Step 3: Add folder data to the response
    return jsonify({
        "FolderName": folder.name,
        "CreatedAt": folder.created_at,
        "Recipes": recipe_list
    })


# def get_recipe_data(recipe_id):
#     """Fetch recipe data from external API."""
#     try:
#         response = requests.get(f'http://127.0.0.1:5000/search/{recipe_id}')
#         print(f"API Response for recipe {recipe_id}: {response.status_code}")
#
#         if response.status_code == 200:
#             data = response.json()
#             print(f"Recipe data for {recipe_id}: {data}")
#             return data['results'][0] if data.get('results') else {"Name": "Unknown Recipe"}
#         return {"Name": "Unknown Recipe"}
#     except requests.exceptions.RequestException as e:
#         print(f"API request error for recipe {recipe_id}: {e}")
#         return {"Name": "Unknown Recipe"}


# ========================================================================
# Get Recipes in Folder Route
# ========================================================================


@auth_app.route('/folder', methods=['POST'])
@jwt_required()
def create_folder():
    user_id = get_jwt_identity()
    data = request.get_json()

    if 'name' not in data:
        return jsonify({"message": "Folder name is required"}), 400

    new_folder = Folder(name=data['name'], user_id=user_id)
    db.session.add(new_folder)
    db.session.commit()

    return jsonify({"message": "Folder created successfully!", "folder_id": new_folder.id}), 201

## Check All folder
@auth_app.route('/folders', methods=['GET'])
def get_user_folders():
    folders = Folder.query.all()  # No need for user_id here
    if not folders:
        return jsonify({"message": "No folders found."}), 404

    folder_list = [{"id": folder.id, "name": folder.name, "created_at": folder.created_at} for folder in folders]
    return jsonify(folder_list), 200


## Add Recipe in folder
@auth_app.route('/folder/<int:folder_id>/add_recipe', methods=['POST'])
@jwt_required()
def add_recipe_to_folder(folder_id):
    data = request.get_json()
    recipe_id = data.get('RecipeId')

    # Check if RecipeId is provided
    if not recipe_id:
        return jsonify({"message": "Recipe ID is required"}), 400

    folder = Folder.query.get(folder_id)
    if not folder:
        return jsonify({"message": "Folder not found"}), 404

    # Call the external API to verify the recipe
    try:
        recipe_response = requests.get(f'http://127.0.0.1:5000/search/{recipe_id}')
        if recipe_response.status_code != 200:
            return jsonify({"message": "Recipe not found in the search API!"}), 404

        recipe_data = recipe_response.json()
        if not recipe_data or 'results' not in recipe_data or len(recipe_data['results']) == 0:
            return jsonify({"message": "Recipe not found!"}), 404

    except requests.exceptions.RequestException as e:
        return jsonify({"message": f"Error calling the search API: {str(e)}"}), 500

    # Check if the recipe already exists in the folder
    existing_entry = FolderRecipe.query.filter_by(folder_id=folder_id, recipe_id=recipe_id).first()
    if existing_entry:
        return jsonify({"message": "Recipe already exists in the folder"}), 400

    new_entry = FolderRecipe(folder_id=folder_id, recipe_id=recipe_id)
    db.session.add(new_entry)
    db.session.commit()

    return jsonify({"message": "Recipe added to folder successfully!"}), 200

@auth_app.route('/folder/<int:folder_id>/recipes', methods=['GET'])
def get_recipes_in_folder(folder_id):
    try:

        folder = db.session.get(Folder, folder_id)
        if not folder:
            return jsonify({"message": "Folder not found"}), 404

        recipes = (
            db.session.query(Recipe.id, Recipe.name)
            .join(FolderRecipe, Recipe.id == FolderRecipe.recipe_id)
            .filter(FolderRecipe.folder_id == folder_id)
            .all()
        )

        if not recipes:
            return jsonify({"message": "No recipes found in this folder."}), 404

        # JSON Response
        recipe_list = [{"RecipeId": r.id, "RecipeName": r.name} for r in recipes]

        return jsonify({"folder_id": folder_id, "recipes": recipe_list}), 200

    except Exception as e:
        return jsonify({"message": f"An error occurred: {e}"}), 500


@auth_app.route('/folder/<int:folder_id>', methods=['DELETE'])
@jwt_required()
def delete_folder(folder_id):
    user_id = get_jwt_identity()
    print(f"🔍 User ID from token: {user_id}")  # ✅ Log ตรวจสอบ JWT Token

    folder = Folder.query.filter_by(id=folder_id, user_id=user_id).first()
    if not folder:
        return jsonify({"message": "Folder not found or unauthorized!"}), 404

    FolderRecipe.query.filter_by(folder_id=folder_id).delete()
    db.session.delete(folder)
    db.session.commit()

    return jsonify({"message": "Folder deleted successfully!"}), 200

@auth_app.route('/folder/<int:folder_id>/remove_recipe/<int:recipe_id>', methods=['DELETE'])
@jwt_required()
def remove_recipe_from_folder(folder_id, recipe_id):
    user_id = get_jwt_identity()  # รับค่า user_id จาก JWT
    print(f"🔍 User {user_id} is trying to remove Recipe {recipe_id} from Folder {folder_id}")

    # ตรวจสอบว่าโฟลเดอร์นี้เป็นของ user หรือไม่
    folder = Folder.query.filter_by(id=folder_id, user_id=user_id).first()
    if not folder:
        return jsonify({"message": "Folder not found or unauthorized!"}), 404

    # ค้นหาและลบสูตรอาหารออกจากโฟลเดอร์
    folder_recipe = FolderRecipe.query.filter_by(folder_id=folder_id, recipe_id=recipe_id).first()
    if not folder_recipe:
        return jsonify({"message": "Recipe not found in this folder!"}), 404

    db.session.delete(folder_recipe)
    db.session.commit()

    print(f"✅ Recipe {recipe_id} removed from Folder {folder_id}")
    return jsonify({"message": "Recipe removed successfully!"}), 200



# ========================================================================
# Search function
# ========================================================================

# Images
def clean_images_column(df):
    def extract_first_image(image_str):
        if not isinstance(image_str, str) or not image_str.strip():
            return None  # ✅ ถ้าเป็นค่าว่างหรือ None ให้คืนค่า None (กัน character(0))

        print(f"🔹 Original Image String: {image_str}")  # Debug จุดนี้

        image_str = image_str.strip()

        # ✅ ตรวจสอบและตัด 'c("...")' ออกถ้ามี
        if image_str.startswith('c("') and image_str.endswith('")'):
            image_str = image_str[2:-2]  # ลบ c(" และ ")

        print(f"✅ After c() removal: {image_str}")

        # ✅ ใช้ regex หาลิงก์รูปภาพทุกประเภท (JPG, PNG, GIF, WEBP, BMP, SVG, TIFF, HEIC, ICO)
        matches = re.findall(r'https://.*?\.(?:jpg|jpeg|png|gif|webp|bmp|svg|tiff|heic|ico)(?:\?.*)?', image_str, re.IGNORECASE)

        # ✅ ดึงแค่ตัวแรก หรือคืนค่า None ถ้าไม่มีลิงก์
        first_match = matches[0] if matches else None

        print(f"🔍 Matches: {matches}")  # Debug จุดนี้
        print(f"✅ First Match: {first_match}")  # Debug จุดนี้

        return first_match

    df['image_link'] = df['image_link'].apply(extract_first_image)
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
    def __init__(self, file_path, pkl_path="recipe_indexer.pkl"):
        self.pkl_path = pkl_path
        try:
            with open(self.pkl_path, "rb") as f:
                data = pickle.load(f)
                self.df = data["df"]
                self.tfidf_vectorizer = data["vectorizer"]
                self.tfidf_matrix = data["matrix"]
                print("✅ Loaded indexer from pkl.")

        except FileNotFoundError:
            print("⚠️ No recipe_indexer.pkl found, creating new indexer...")
            self.df = pd.read_csv(file_path)
            self.df.fillna("", inplace=True)

            print("🚀 Cleaning Data...")
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
                print("✅ Saved indexer to pkl.")

    def index(self):
        self.df['combined_text'] = self.df['Name'] + " " + self.df['Description'] + " " + self.df['RecipeInstructions']
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(self.df['combined_text'])

        for idx, row in self.df.iterrows():
            doc = row.to_dict()

            print(f"Indexing Recipe {row['RecipeId']}: {doc.get('image_link')}")

            search_app.es_client.index(index='custom', id=row["RecipeId"], document=doc)


start_time = time.time()
indexer = Indexer("resource/completed_recipes.csv")
end_time = time.time()
elapsed_time = end_time - start_time
print(f"\n⏱️ Total Execution Time: {elapsed_time:.2f} seconds")


## Search
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


# ========================================================================
# Run Everything
# ========================================================================

def run_auth():
    auth_app.run(host="127.0.0.1", port=5001, debug=False)

def run_search():
    search_app.run(host="127.0.0.1", port=5000, debug=False)

if __name__ == "__main__":
    create_tables()
    Thread(target=run_auth).start()
    Thread(target=run_search).start()