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
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.decomposition import TruncatedSVD
import pickle


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
    __tablename__ = 'folder_recipe'
    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=False)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=True)  # Rating value between 1 and 5


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
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found!"}), 404

    folders = Folder.query.filter_by(user_id=user_id).all()
    if not folders:
        return jsonify({"message": "No folders found for this user!"}), 200  # Return a 200 status code

    folder_data = []

    for folder in folders:
        # Get recipe IDs and ratings from FolderRecipe table
        folder_recipes = (
            db.session.query(FolderRecipe.recipe_id, FolderRecipe.rating)
            .filter(FolderRecipe.folder_id == folder.id)
            .all()
        )

        recipe_list = []
        for recipe_id, rating in folder_recipes:
            recipe_data = get_recipe_data(recipe_id)
            recipe_list.append({
                "RecipeId": recipe_id,
                "RecipeName": recipe_data.get('Name', "Unknown Recipe"),
                "Rating": rating if rating is not None else "No rating"
            })

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

## Get only folder by userID & folderID
@auth_app.route('/user/<int:user_id>/folders/<int:folder_id>', methods=['GET'])
def get_user_folder_details(user_id, folder_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "User not found!"}), 404

    folder = Folder.query.filter_by(user_id=user_id, id=folder_id).first()
    if not folder:
        return jsonify({"message": "Folder not found!"}), 404

    # Step 1: Get recipe IDs and ratings from FolderRecipe table
    folder_recipes = (
        db.session.query(FolderRecipe.recipe_id, FolderRecipe.rating)
        .filter(FolderRecipe.folder_id == folder.id)
        .all()
    )

    recipe_list = []
    for recipe_id, rating in folder_recipes:
        recipe_data = get_recipe_data(recipe_id)
        recipe_list.append({
            "RecipeId": recipe_id,
            "RecipeName": recipe_data.get('Name', "Unknown Recipe"),
            "Rating": rating if rating is not None else "No rating"
        })

    # Step 2: Add folder data to the response
    return jsonify({
        "FolderName": folder.name,
        "CreatedAt": folder.created_at,
        "Recipes": recipe_list
    })



# ========================================================================
# Get Recipes in Folder Route
# ========================================================================

# Create new folder.
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

## Retrieve all folders of authenticated user.
@auth_app.route('/folders', methods=['GET'])
@jwt_required()
def get_user_folders():
    print("✅ /folders endpoint hit")
    try:
        user_id = get_jwt_identity()  # Extract user ID from the token
        print(f"User ID from token: {user_id}")  # Debugging log to verify user ID

        if not user_id:
            return jsonify({"message": "User ID is missing."}), 400

        folders = Folder.query.filter_by(user_id=user_id).all()

        if not folders:
            return jsonify([]), 200

        folder_list = [{"id": folder.id, "name": folder.name, "created_at": folder.created_at} for folder in folders]
        return jsonify(folder_list), 200
    except Exception as e:
        return jsonify({"message": f"Error: {str(e)}"}), 500

## Add Recipe in folder
@auth_app.route('/folder/<int:folder_id>/add_recipe', methods=['POST'])
@jwt_required()
def add_recipe_to_folder(folder_id):
    data = request.get_json()
    recipe_id = data.get('RecipeId')
    rating_value = data.get('rating')  # ✅ ดึงค่า rating ที่ถูกส่งมา

    print(f"📥 Received RecipeId: {recipe_id}, Rating: {rating_value}")  # Debugging

    if not recipe_id:
        return jsonify({"message": "Recipe ID is required"}), 400

    folder = Folder.query.get(folder_id)
    if not folder:
        return jsonify({"message": "Folder not found"}), 404

    existing_entry = FolderRecipe.query.filter_by(folder_id=folder_id, recipe_id=recipe_id).first()

    if existing_entry:

        print("🔄 Updating rating for existing recipe...")
        existing_entry.rating = rating_value
        db.session.commit()
        return jsonify({"message": "Recipe rating updated successfully!"}), 200

    print("➕ Adding new recipe with rating...")
    new_entry = FolderRecipe(folder_id=folder_id, recipe_id=recipe_id, rating=rating_value)
    db.session.add(new_entry)
    db.session.commit()

    return jsonify({"message": "Recipe added to folder successfully!"}), 200

## Get all recipes in specific folder.
# @auth_app.route('/folder/<int:folder_id>/recipes', methods=['GET'])
# def get_recipes_in_folder(folder_id):
#     try:
#
#         folder = db.session.get(Folder, folder_id)
#         if not folder:
#             return jsonify({"message": "Folder not found"}), 404
#
#         recipes = (
#             db.session.query(Recipe.id, Recipe.name)
#             .join(FolderRecipe, Recipe.id == FolderRecipe.recipe_id)
#             .filter(FolderRecipe.folder_id == folder_id)
#             .all()
#         )
#
#         if not recipes:
#             return jsonify({"message": "No recipes found in this folder."}), 404
#
#         # JSON Response
#         recipe_list = [{"RecipeId": r.id, "RecipeName": r.name} for r in recipes]
#
#         return jsonify({"folder_id": folder_id, "recipes": recipe_list}), 200
#
#     except Exception as e:
#         return jsonify({"message": f"An error occurred: {e}"}), 500

# Delete folder
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

# Delete recipe in folder
@auth_app.route('/folder/<int:folder_id>/remove_recipe/<int:recipe_id>', methods=['DELETE'])
@jwt_required()
def remove_recipe_from_folder(folder_id, recipe_id):
    user_id = get_jwt_identity()  # รับค่า user_id จาก JWT
    print(f"🔍 User {user_id} is trying to remove Recipe {recipe_id} from Folder {folder_id}")

    folder = Folder.query.filter_by(id=folder_id, user_id=user_id).first()
    if not folder:
        return jsonify({"message": "Folder not found or unauthorized!"}), 404

    folder_recipe = FolderRecipe.query.filter_by(folder_id=folder_id, recipe_id=recipe_id).first()
    if not folder_recipe:
        return jsonify({"message": "Recipe not found in this folder!"}), 404

    db.session.delete(folder_recipe)
    db.session.commit()

    print(f"✅ Recipe {recipe_id} removed from Folder {folder_id}")
    return jsonify({"message": "Recipe removed successfully!"}), 200

## Update folder name
@auth_app.route('/folder/<int:folder_id>', methods=['PUT'])
@jwt_required()
def update_folder_name(folder_id):
    user_id = get_jwt_identity()
    data = request.get_json()

    # Validate request data
    if not data or 'name' not in data:
        return jsonify({"message": "Folder name is required"}), 400

    # Find the folder to update
    folder = Folder.query.filter_by(id=folder_id, user_id=user_id).first()
    if not folder:
        return jsonify({"message": "Folder not found or unauthorized!"}), 404

    # Update the folder name
    folder.name = data['name']
    db.session.commit()

    return jsonify({"message": "Folder name updated successfully!", "folder_id": folder.id, "folder_name": folder.name}), 200

## Rate recipe inside a folder.
@auth_app.route('/folder/<int:folder_id>/recipe/<int:recipe_id>/rate', methods=['POST'])
@jwt_required()
def rate_recipe_in_folder(folder_id, recipe_id):
    user_id = get_jwt_identity()
    data = request.get_json()
    rating_value = data.get('rating')

    if rating_value is None or not (1 <= rating_value <= 5):
        return jsonify({"message": "Rating must be between 1 and 5."}), 400

    folder_recipe = FolderRecipe.query.filter_by(folder_id=folder_id, recipe_id=recipe_id).first()
    if not folder_recipe:
        return jsonify({"message": "Recipe not found in this folder!"}), 404

    folder_recipe.rating = rating_value
    db.session.commit()

    return jsonify({"message": "Rating submitted successfully!"}), 200

## Get the rating of a recipe in a folder.
@auth_app.route('/folder/<int:folder_id>/recipe/<int:recipe_id>/rating', methods=['GET'])
def get_recipe_rating_in_folder(folder_id, recipe_id):
    # Fetch the recipe rating for the folder
    folder_recipe = FolderRecipe.query.filter_by(folder_id=folder_id, recipe_id=recipe_id).first()

    if not folder_recipe or folder_recipe.rating is None:
        return jsonify({"message": "No rating found for this recipe in the folder."}), 404

    return jsonify({
        "recipe_id": recipe_id,
        "folder_id": folder_id,
        "rating": folder_recipe.rating
    }), 200


with open("recipe_indexer.pkl", "rb") as f:
    index_data = pickle.load(f)

df_recipes = index_data["df"]
tfidf_matrix = index_data["matrix"]
lsa = TruncatedSVD(n_components=100, random_state=42)
lsa_matrix = lsa.fit_transform(tfidf_matrix)

@auth_app.route('/recommend/folder/<int:folder_id>', methods=['GET'])
def recommend_recipes_for_folder(folder_id):
    print(f"📥 Incoming request to /recommend/folder/{folder_id}")
    try:
        # Step 1: Get recipe IDs in folder
        folder_recipes = FolderRecipe.query.filter_by(folder_id=folder_id).all()
        if not folder_recipes:
            return jsonify({"message": "No recipes found in this folder."}), 404

        recipe_ids_in_folder = [fr.recipe_id for fr in folder_recipes]

        # Step 2: Find indices of those recipe_ids in df_recipes
        folder_indices = df_recipes[df_recipes["RecipeId"].isin(recipe_ids_in_folder)].index.tolist()
        if not folder_indices:
            return jsonify({"message": "No matching recipes in indexer."}), 404

        # Step 3: Average vector for the folder
        folder_vector = lsa_matrix[folder_indices].mean(axis=0).reshape(1, -1)

        # Step 4: Compute cosine similarity
        similarities = cosine_similarity(folder_vector, lsa_matrix).flatten()

        # Step 5: Rank by similarity, exclude ones already in folder
        similar_indices = similarities.argsort()[::-1]
        recommendations = []
        seen_ids = set(recipe_ids_in_folder)

        for idx in similar_indices:
            recipe_id = df_recipes.iloc[idx]["RecipeId"]
            if recipe_id not in seen_ids:
                recommendations.append({
                    "RecipeId": int(recipe_id),
                    "Name": df_recipes.iloc[idx]["Name"],
                    "Similarity": float(similarities[idx]),
                    "image_link": df_recipes.iloc[idx].get("image_link", None)
                })
            if len(recommendations) >= 10:
                break

        return jsonify({
            "status": "success",
            "folder_id": folder_id,
            "recommendations": recommendations
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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

        matches = re.findall(r'https://.*?\.(?:jpg|jpeg|png|gif|webp|bmp|svg|tiff|heic|ico)(?:\?.*)?', image_str, re.IGNORECASE)

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


@search_app.route('/search', methods=['GET'])
def search():
    try:
        query_term = request.args.get('query', '')  # Get query parameter

        # If query_term is not provided, we use match_all to fetch all data
        if query_term:
            # Fuzzy search for the query term if provided
            query_body = {
                "query": {
                    "fuzzy": {
                        "combined_text": {
                            "value": query_term,
                            "fuzziness": "AUTO",  # Fuzziness to handle typos
                            "prefix_length": 1
                        }
                    }
                }
            }
        else:
            # Return all records if no query is provided (use match_all)
            query_body = {
                "query": {
                    "match_all": {}  # Match all documents in the index
                }
            }

        # Pagination (if you want more than 100 items, you can adjust the size)
        query_body["from"] = 0
        query_body["size"] = 100  # Limit the results to 100 (you can increase it as needed)

        results = search_app.es_client.search(index='custom', body=query_body)

        # Handle no results found
        if results['hits']['total']['value'] == 0:
            return jsonify({"message": "No recipes found!"}), 404

        # Return the results
        response = {
            'status': 'success',
            'total_hit': results['hits']['total']['value'],
            'results': [hit["_source"] for hit in results['hits']['hits']]
        }

    except Exception as e:
        response = {'status': 'error', 'message': str(e)}

    return jsonify(response)


@search_app.route('/search/<int:recipe_id>', methods=['GET'])
def search_by_id(recipe_id):
    try:
        # Fetch a specific recipe by its ID
        results = search_app.es_client.search(index='custom', body={
            "query": {
                "match": {
                    "RecipeId": recipe_id
                }
            }
        })

        if results['hits']['total']['value'] == 0:
            return jsonify({"message": f"No recipe found for ID {recipe_id}"}), 404

        response = {
            'status': 'success',
            'results': [hit["_source"] for hit in results['hits']['hits']]
        }

    except Exception as e:
        response = {'status': 'error', 'message': str(e)}

    return jsonify(response)

@search_app.route('/suggest', methods=['GET'])
def suggest():
    try:
        query_term = request.args.get('query', '')

        if not query_term:
            return jsonify({"message": "No query provided"}), 400

        suggest_query = {
            "suggest": {
                "text": query_term,
                "simple_phrase": {
                    "phrase": {
                        "field": "combined_text",
                        "size": 5,  # Return 5 suggestions
                        "gram_size": 3,  # Token size
                        "direct_generator": [{
                            "field": "combined_text",
                            "suggest_mode": "always"
                        }],
                        "highlight": {
                            "pre_tag": "<em>",
                            "post_tag": "</em>"
                        }
                    }
                }
            }
        }

        # Run the suggestion query
        results = search_app.es_client.search(index='custom', body=suggest_query)

        if 'suggest' in results:
            suggestions = results['suggest']['simple_phrase'][0]['options']
        else:
            suggestions = []

        return jsonify({
            'status': 'success',
            'suggestions': [suggestion['text'] for suggestion in suggestions]
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


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