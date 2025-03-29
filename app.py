from flask import Flask, render_template, request, jsonify
import osmnx as ox
import networkx as nx
import geopy.distance

app = Flask(__name__)


@app.route('/')
def index():
    return render_template("index.html")


@app.route('/get_route', methods=['POST'])
def get_route():
    start_lat = float(request.form['start_lat'])
    start_lon = float(request.form['start_lon'])
    goal_lat = float(request.form['goal_lat'])
    goal_lon = float(request.form['goal_lon'])
    mode = request.form['mode']  # Car, Walk, or Bike

    # Load the road network
    place = "Ba Đình District"
    G = ox.graph_from_place(place, network_type='walk', simplify=False)

    # Find nearest nodes
    start_node = ox.nearest_nodes(G, start_lon, start_lat)
    goal_node = ox.nearest_nodes(G, goal_lon, goal_lat)

    # Check if a path exists
    if nx.has_path(G, start_node, goal_node):
        # Find the shortest path using A* algorithm
        route = nx.astar_path(G, start_node, goal_node, weight='length')

        # Convert route nodes to coordinates
        route_coords = [(G.nodes[node]['y'], G.nodes[node]['x']) for node in route]

        # Calculate distance and estimated time
        total_distance = 0
        for i in range(1, len(route_coords)):
            total_distance += geopy.distance.distance(route_coords[i - 1], route_coords[i]).km

        # Estimate time based on mode
        speed = 0
        if mode == 'car':
            speed = 50  # Average speed in km/h for car
        elif mode == 'walk':
            speed = 5  # Average walking speed in km/h
        elif mode == 'bike':
            speed = 15  # Average speed in km/h for bike

        # Calculate estimated time in hours
        time_hours = total_distance / speed
        time_minutes = time_hours * 60

        return jsonify({
            'route': route_coords,
            'distance': round(total_distance, 2),
            'time': f"{round(time_minutes)} minutes"
        })
    else:
        return jsonify({'error': "No path found."})


if __name__ == '__main__':
    app.run(debug=True)
