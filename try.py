import openrouteservice
from openrouteservice import convert

# Replace with your actual key
api_key = "5b3ce3597851110001cf624878618b6603bc454d884934f21f812d4f"
client = openrouteservice.Client(key=api_key)

# Function to get coordinates from location name
def get_coords(location_name):
    import requests
    url = f"https://api.openrouteservice.org/geocode/search?api_key={api_key}&text={location_name}"
    res = requests.get(url)
    data = res.json()
    coords = data["features"][0]["geometry"]["coordinates"]
    return coords

def get_distance(place1, place2):
    coords1 = get_coords(place1)
    coords2 = get_coords(place2)
    
    route = client.directions(
        coordinates=[coords1, coords2],
        profile='driving-car',
        format='geojson'
    )

    distance_km = route['features'][0]['properties']['segments'][0]['distance'] / 1000
    print(f"Distance between {place1} and {place2}: {distance_km:.2f} km")

# Example usage
get_distance("Harohalli", "Jayanagar")
