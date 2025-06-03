from flask import Flask, request, jsonify
from pymongo import MongoClient
from flask_cors import CORS
from shapely.geometry import LineString, Polygon, Point
import requests
import os

app = Flask(__name__)
CORS(app)

# Kết nối MongoDB
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://admin2:123123a@cluster0.nyw26.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
)
client = MongoClient(MONGO_URI)
db = client["Flight_A"]
No_Flight_collection = db["No_Flight"]
flight_path_collection = db["flight_path"]

# Route POST để thêm dữ liệu vùng cấm bay
@app.route("/no_flight", methods=["POST"])
def add_no_flight():
    data = request.json
    if not data or "name" not in data or "coordinates" not in data:
        return jsonify({"error": "Thiếu tên hoặc tọa độ"}), 400

    name = data["name"]
    coordinates = data["coordinates"]

    if not isinstance(coordinates, list) or not all(
        isinstance(coord, list) and len(coord) == 2 and all(isinstance(x, (int, float)) for x in coord)
        for coord in coordinates
    ):
        return jsonify({"error": "Tọa độ phải là danh sách các cặp [x, y]"}), 400

    no_flight_data = {
        "name": name,
        "coordinates": coordinates
    }
    result = No_Flight_collection.insert_one(no_flight_data)
    return jsonify({
        "message": "Đã thêm vùng cấm bay",
        "id": str(result.inserted_id)
    }), 201

@app.route("/flight_path", methods=["POST"])
def add_flight_path():
    data = request.json
    if not data or "name" not in data or "waypoints" not in data:
        return jsonify({"error": "Thiếu 'name' hoặc 'waypoints'"}), 400

    name = data["name"]
    waypoints = data["waypoints"]

    if not isinstance(waypoints, list) or not all(isinstance(p, str) for p in waypoints):
        return jsonify({"error": "'waypoints' phải là danh sách các chuỗi tên waypoint"}), 400

    flight_path_data = {
        "name": name,
        "waypoints": waypoints
    }

    result = flight_path_collection.insert_one(flight_path_data)
    return jsonify({
        "message": "Đã thêm đường bay",
        "id": str(result.inserted_id)
    }), 201

if __name__ == "__main__":
    app.run(debug=True)