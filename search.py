from flask import Flask, request, jsonify
import time
import pandas as pd
import re
from elasticsearch import Elasticsearch
from sklearn.feature_extraction.text import TfidfVectorizer
from flask_cors import CORS
import pickle

app = Flask(__name__)
CORS(app)
app.es_client = Elasticsearch("https://localhost:9200", basic_auth=("elastic", "Iv0CDItraOJ7siTp4kNl"),
                              ca_certs="~/http_ca.crt")

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
            self.df.fillna("", inplace=True)  # Fill missing values

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
        self.df['combined_text'] = (
            self.df['Name'] + " " + self.df['Description'] + " " + self.df['RecipeInstructions']
        )
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(self.df['combined_text'])

        for idx, row in self.df.iterrows():
            doc = row.to_dict()
            app.es_client.index(index='custom', id=row["RecipeId"], document=doc)

indexer = Indexer("resource/recipes.csv")

@app.route('/search', methods=['GET'])
def search():
    query_term = request.args.get('query', '')
    try:
        query_body = {"match": {"combined_text": query_term}} if query_term else {"match_all": {}}
        results = app.es_client.search(index='custom', size=100, query=query_body)
        response = {
            'status': 'success',
            'total_hit': results['hits']['total']['value'],
            'results': [hit["_source"] for hit in results['hits']['hits']]
        }
    except Exception as e:
        response = {'status': 'error', 'message': str(e)}
    return jsonify(response)

@app.route('/search/<id>', methods=['GET'])
def search_by_id(id):
    try:
        result = app.es_client.get(index='custom', id=id)
        return jsonify({'status': 'success', 'recipe': result['_source']})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5000, debug=False)