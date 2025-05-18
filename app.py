from flask import Flask, render_template, request, jsonify
import osmnx as ox
import networkx as nx
import google.generativeai as genai
import geopy.distance
import requests
import subprocess
import socket
import re
import os
import sys


MODEL_CONFIG = {
    "gemini": {
        "sdk": "google",
        "api_key": "YOUR_API_KEY",  # YOUR_API_KEY
        "model": "GEMINI_MODEL_NAME",  # GEMINI_MODEL_NAME # gemini-2.0-flash-exp
    }
}


app = Flask(__name__)
place = "Phường Đội Cấn, Ba Đình, Hà Nội, Việt Nam"
G = ox.graph_from_place(place, network_type="walk", simplify=False)
G_original = G.copy()


def get_client():
    config = MODEL_CONFIG["gemini"]
    genai.configure(api_key=config["api_key"])
    return genai.GenerativeModel(config["model"])


def start_agent_service():
    agent_dir = os.path.join(os.path.dirname(__file__), "agent-location-search", "src")

    # Check if already running
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("127.0.0.1", 5001))
        s.close()
        return  # Already running
    except Exception:
        pass

    # Start the agent service
    subprocess.Popen([sys.executable, "main.py"], cwd=agent_dir)


def clean_bot_response(text):
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"^\s*[\*\-]\s*", "", text, flags=re.MULTILINE)
    lines = text.split("\n")
    text = "\n".join([line.strip() for line in lines if line.strip()])
    return text.strip()


def clean_bot_response(text):
    import re

    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    lines = text.split("\n")
    # If there is no bullet point, add it automatically
    if not any(line.strip().startswith("-") for line in lines):
        # Find the title line (usually the first line)
        if len(lines) > 1:
            title = lines[0]
            items = lines[1:]
        else:
            title = ""
            items = lines
        # Split items by dot or *
        new_items = []
        for item in items:
            # Split by . or *
            parts = re.split(r"\.\s+|\*\s+", item)
            for part in parts:
                part = part.strip()
                if part:
                    new_items.append(f"- {part}")
        # Join together
        text = title + "\n" + "\n".join(new_items)
    else:
        text = "\n".join([line.strip() for line in lines if line.strip()])
    return text.strip()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get_boundary", methods=["GET"])
def get_boundary():
    place_name = "Phường Đội Cấn, Ba Đình, Hà Nội, Việt Nam"
    gdf = ox.geocode_to_gdf(place_name)
    return gdf.to_json()


@app.route("/ban_route", methods=["POST"])
def ban_route():
    start_lat = float(request.form["start_lat"])
    start_lon = float(request.form["start_lon"])
    end_lat = float(request.form["end_lat"])
    end_lon = float(request.form["end_lon"])

    try:
        start_node = ox.nearest_nodes(G, start_lon, start_lat)
        end_node = ox.nearest_nodes(G, end_lon, end_lat)

        if nx.has_path(G, start_node, end_node):
            route = nx.astar_path(G, start_node, end_node, weight="length")
            coords = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in route]

            # Remove nodes in the banned route from the current graph
            for node in route:
                if G.has_node(node):
                    G.remove_node(node)

            return jsonify({"route": coords})
        else:
            return jsonify({"error": "No path found to ban."})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/search_location", methods=["GET"])
def search_location():
    query = request.args.get("q", "").strip()
    if not query or len(query) < 3:
        return jsonify([])
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "json",
                "addressdetails": 1,
                "limit": 5,
                "accept-language": "vi",
            },
            headers={"User-Agent": "HUST-Map/1.0"},
        )
        data = resp.json()
        results = [
            {
                "display_name": item["display_name"],
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
            }
            for item in data
        ]
        return jsonify(results)
    except Exception as e:
        print("Search location error:", e)
        return jsonify([])


@app.route("/reset_graph", methods=["POST"])
def reset_graph():
    global G
    G = G_original.copy()
    return "Graph reset."


@app.route("/get_route", methods=["POST"])
def get_route():
    start_lat = float(request.form["start_lat"])
    start_lon = float(request.form["start_lon"])
    goal_lat = float(request.form["goal_lat"])
    goal_lon = float(request.form["goal_lon"])
    mode = request.form["mode"]  # Car, Walk, or Bike

    # Find nearest nodes
    start_node = ox.nearest_nodes(G, start_lon, start_lat)
    goal_node = ox.nearest_nodes(G, goal_lon, goal_lat)

    import heapq

    def heuristic(n1, n2):
        y1, x1 = G.nodes[n1]["y"], G.nodes[n1]["x"]
        y2, x2 = G.nodes[n2]["y"], G.nodes[n2]["x"]
        return geopy.distance.distance((y1, x1), (y2, x2)).km

    def astar(G, start, goal):
        open_set = []
        heapq.heappush(open_set, (0, start))
        came_from = {}
        g_score = {start: 0}
        f_score = {start: heuristic(start, goal)}
        closed_set = set()
        while open_set:
            current_f, current = heapq.heappop(open_set)
            if current == goal:
                # reconstruct path
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path
            closed_set.add(current)
            for neighbor in G.neighbors(current):
                if neighbor in closed_set:
                    continue
                edge_data = G.get_edge_data(current, neighbor, default={})
                # If multiple edges, pick the shortest
                if isinstance(edge_data, dict) and len(edge_data) > 0:
                    if 0 in edge_data:
                        length = edge_data[0].get("length", 1)
                    else:
                        length = min([d.get("length", 1) for d in edge_data.values()])
                else:
                    length = 1
                tentative_g = g_score[current] + length / 1000.0  # convert m to km
                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + heuristic(neighbor, goal)
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))
        return None

    # Check if a path exists (simple check)
    if nx.has_path(G, start_node, goal_node):
        route = astar(G, start_node, goal_node)
        if not route:
            return jsonify({"error": "No path found."})
        # Convert route nodes to coordinates
        route_coords = [(G.nodes[node]["y"], G.nodes[node]["x"]) for node in route]
        # Calculate distance and estimated time
        total_distance = 0
        for i in range(1, len(route_coords)):
            total_distance += geopy.distance.distance(
                route_coords[i - 1], route_coords[i]
            ).km
        # Estimate time based on mode
        speed = 0
        if mode == "car":
            speed = 50  # Average speed in km/h for car
        elif mode == "walk":
            speed = 5  # Average walking speed in km/h
        elif mode == "bike":
            speed = 15  # Average speed in km/h for bike
        # Calculate estimated time in hours
        time_hours = total_distance / speed
        time_minutes = time_hours * 60
        return jsonify(
            {
                "route": route_coords,
                "distance": round(total_distance, 2),
                "time": f"{round(time_minutes)} minutes",
            }
        )
    else:
        return jsonify({"error": "No path found."})


@app.route("/chatbot", methods=["POST"])
def chatbot():
    user_msg = request.form.get("message", "").lower()
    prompt = "Nếu câu hỏi của tôi là về các địa điểm, hãy trả lời ngắn gọn, mỗi địa điểm một dòng, dùng dấu gạch đầu dòng '-', có tiêu đề, có địa chỉ, có mô tả ngắn gọn từng địa điểm. Trả lời bằng tiếng Việt. "
    user_msg = user_msg + " " + prompt
    try:
        client = get_client()
        chat = client.start_chat(history=[])
        response = chat.send_message(user_msg)
        response = clean_bot_response(response.text)
        return jsonify({"reply": response})

    except Exception:
        reply = "Sorry, the AI location agent is not available right now."
    return jsonify({"reply": reply})


if __name__ == "__main__":
    start_agent_service()
    app.run(debug=True)
