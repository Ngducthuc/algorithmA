from flask import Flask, request, jsonify
from pymongo import MongoClient
from flask_cors import CORS
from bson.json_util import dumps
from shapely.geometry import LineString, Polygon, Point
import requests
import heapq
import os

# Khởi tạo Flask app
app = Flask(__name__)
CORS(app)

# Kết nối MongoDB
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://admin2:123123a@cluster0.nyw26.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
)
client = MongoClient(MONGO_URI)
db = client["Flight_A"]
road_collection = db["Road"]
point_collection = db["data_point"]
No_Flight_collection = db["No_Flight"]
distance_collection = db["distance"]
flight_path_new_collection = db["Flight_path_new"]
flight_path_collection = db["flight_path"]


# Route POST để thêm dữ liệu road
@app.route("/data-road", methods=["POST"])
def add_data_road():
    data = request.json
    if not data or "ten_duong_chinh" not in data or "cac_ten_duong_con" not in data:
        return jsonify({"error": "Missing required fields"}), 400
    result = road_collection.insert_one(data)
    return jsonify({
        "message": "Road added successfully",
        "id": str(result.inserted_id)
    }), 201

# Route GET kết hợp tọa độ và chiều
@app.route("/data-road", methods=["GET"])
def get_data_road_with_coordinates():
    roads = list(road_collection.find({}, {"_id": 0}))
    result = []

    for road in roads:
        duong_chinh = road["ten_duong_chinh"]
        ten_duong_con = road["cac_ten_duong_con"]

        enriched_con = []
        for name in ten_duong_con:
            point = point_collection.find_one(
                {"ten_duong": name},
                {"_id": 0, "vi_do": 1, "kinh_do": 1, "chieu": 1}
            )
            if point:
                enriched_con.append({
                    "ten_duong": name,
                    "vi_do": point.get("vi_do"),
                    "kinh_do": point.get("kinh_do"),
                    "chieu": point.get("chieu")
                })
            else:
                enriched_con.append({
                    "ten_duong": name,
                    "vi_do": None,
                    "kinh_do": None,
                    "chieu": None
                })

        result.append({
            "ten_duong_chinh": duong_chinh,
            "cac_ten_duong_con": enriched_con
        })
    return jsonify(result), 200

# API GET DATA CẤM BAY
@app.route("/data-no-flight", methods=["GET"])
def get_data_no_flight():
    no_flight_collection = db["No_Flight"]
    no_flight_zones = list(no_flight_collection.find({}, {"_id": 0, "name": 1, "coordinates": 1}))
    return jsonify(no_flight_zones), 200

# Api Cấm bay
@app.route("/get-point-no-flight", methods=["GET"])
def get_no_flight_zones():
    data_points = requests.get("http://localhost:5000/data-road").json()
    data_no_flight = requests.get("http://localhost:5000/data-no-flight").json()
    no_flight_zones = [
        {
            "name": zone["name"],
            "polygon": Polygon([(coord[1], coord[0]) for coord in zone["coordinates"]])
        }
        for zone in data_no_flight
    ]

    violations = []

    for road in data_points:
        ten_duong_chinh = road["ten_duong_chinh"]
        points = road["cac_ten_duong_con"]

        valid_points = [
            (p["kinh_do"], p["vi_do"]) for p in points
            if p["kinh_do"] is not None and p["vi_do"] is not None
        ]

        for i in range(len(valid_points) - 1):
            p1 = valid_points[i]
            p2 = valid_points[i + 1]
            segment = LineString([p1, p2])

            for zone in no_flight_zones:
                if segment.crosses(zone["polygon"]) or segment.within(zone["polygon"]):
                    violations.append({
                        "ten_duong_chinh": ten_duong_chinh,
                        "zone": zone["name"],
                        "from": {"kinh_do": p1[0], "vi_do": p1[1]},
                        "to": {"kinh_do": p2[0], "vi_do": p2[1]}
                    })

    return jsonify(violations)

@app.route("/get-data-flight_path", methods=["GET"])
def get_data_flight_path():
    flight_path_collection = db["flight_path"]
    flight_paths = list(flight_path_collection.find({}, {"_id": 0, "name": 1, "waypoints": 1}))

    result = []

    for flight in flight_paths:
        name = flight["name"]
        waypoint_names = flight["waypoints"]

        coordinates = []
        for wp in waypoint_names:
            point = point_collection.find_one(
                {"ten_duong": wp},
                {"_id": 0, "vi_do": 1, "kinh_do": 1}
            )
            if point and point.get("vi_do") is not None and point.get("kinh_do") is not None:
                coordinates.append([point["vi_do"], point["kinh_do"]])

        if len(coordinates) >= 2:
            result.append({
                "name": name,
                "coordinates": coordinates
            })
    return jsonify(result), 200

# API GET DATA KHOẢNG CÁCH
@app.route("/data-distance", methods=["GET"])
def get_data_distance():
    distances = list(distance_collection.find({}, {"_id": 0, "from": 1, "to": 1, "distance_nm": 1}))
    return jsonify(distances), 200


# MAIN LOGIC
# A*
def haversine(p1, p2):
    from math import radians, cos, sin, asin, sqrt
    lat1, lon1 = p1
    lat2, lon2 = p2
    R = 6371  # km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
    c = 2 * asin(sqrt(a))
    return R * c * 0.539957

def a_star(start, goal, points_dict, graph_edges, no_flight_polygons):
    open_set = [(0, [start])]
    paths = []

    while open_set:
        total_cost, path = heapq.heappop(open_set)
        current = path[-1]

        if current == goal:
            return path

        for neighbor, dist in graph_edges.get(current, []):
            if neighbor in path:
                continue
            if neighbor not in points_dict or current not in points_dict:
                continue

            segment = LineString([
                (points_dict[current][1], points_dict[current][0]),
                (points_dict[neighbor][1], points_dict[neighbor][0])
            ])

            if any(segment.crosses(zone) or segment.within(zone) for zone in no_flight_polygons):
                continue
            new_path = path + [neighbor]
            cost = sum(
                graph_edges[new_path[i]][j][1]
                for i in range(len(new_path) - 1)
                for j in range(len(graph_edges[new_path[i]]))
                if graph_edges[new_path[i]][j][0] == new_path[i + 1]
            )
            est = haversine(points_dict[neighbor], points_dict[goal])
            heapq.heappush(open_set, (cost + est, new_path))

    return []
# Yen's Algorithm
def k_shortest_paths(start, goal, k, points_dict, graph_edges, no_flight_polygons):
    first_path = a_star(start, goal, points_dict, graph_edges, no_flight_polygons)
    if not first_path:
        return []
    # Load map data
    paths = [first_path]
    candidates = []
    # Add data vào candidates
    for i in range(1, k):
        for j in range(len(paths[-1]) - 1):
            spur_node = paths[-1][j]
            root_path = paths[-1][:j + 1]

            removed_edges = []
            for path in paths:
                if path[:j + 1] == root_path and j + 1 < len(path):
                    u, v = path[j], path[j + 1]
                    for idx, (n, d) in enumerate(graph_edges.get(u, [])):
                        if n == v:
                            removed_edges.append((u, graph_edges[u][idx]))
                            del graph_edges[u][idx]
                            break

            spur_path = a_star(spur_node, goal, points_dict, graph_edges, no_flight_polygons)
            if spur_path:
                total_path = root_path[:-1] + spur_path
                if total_path not in paths:
                    total_dist = sum(
                        next(d for n, d in graph_edges[total_path[i]] if n == total_path[i + 1])
                        for i in range(len(total_path) - 1)
                    )
                    heapq.heappush(candidates, (total_dist, total_path))

            for u, edge in removed_edges:
                graph_edges[u].append(edge)

        if candidates:
            dist, best_path = heapq.heappop(candidates)
            paths.append(best_path)
        else:
            break

    return paths

@app.route("/suggest-alt-flight", methods=["POST"])
def suggest_alt_flight():
    data = request.json
    start = data.get("from")
    end = data.get("to")
    k = int(data.get("k", 3))

    if not start or not end:
        return jsonify({"error": "Thiếu điểm bắt đầu hoặc kết thúc"}), 400

    # 1. Load points
    points = {
        p["ten_duong"]: [p["vi_do"], p["kinh_do"]]
        for p in point_collection.find({}, {"_id": 0, "ten_duong": 1, "vi_do": 1, "kinh_do": 1})
        if p.get("vi_do") is not None and p.get("kinh_do") is not None
    }

    # 2. Load graph
    edges = {}
    for item in distance_collection.find({}, {"_id": 0, "from": 1, "to": 1, "distance_nm": 1}):
        f, t = item["from"], item["to"]
        if f in points and t in points:
            edges.setdefault(f, []).append((t, item["distance_nm"]))
            edges.setdefault(t, []).append((f, item["distance_nm"]))


    # 3. Load no-flight zones
    no_flight_zones = [
        Polygon([(pt[1], pt[0]) for pt in z["coordinates"]])
        for z in No_Flight_collection.find({}, {"_id": 0, "coordinates": 1})
    ]

    paths = k_shortest_paths(start, end, k, points, edges, no_flight_zones)

    if not paths:
        return jsonify({"message": "Không tìm được đường đi hợp lệ"}), 404

    result = []
    for path in paths:
        total_dist = 0
        for i in range(len(path) - 1):
            for n, d in edges[path[i]]:
                if n == path[i + 1]:
                    total_dist += d
                    break
        coords = [points[p] for p in path]
        result.append({
            "path": path,
            "coordinates": coords,
            "total_distance_nm": round(total_dist, 2)
        })

        flight_path_new_collection.insert_one({
            "from": start,
            "to": end,
            "path": path,
            "coordinates": coords,
            "total_distance_nm": round(total_dist, 2)
        })

    return jsonify(result), 200

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
