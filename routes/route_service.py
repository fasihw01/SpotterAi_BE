import requests
from typing import Dict, Tuple
import json
from django.conf import settings

class RouteService:
    # Your OpenRouteService API Key
    ORS_API_KEY = settings.ORS_API_KEY
    
    @staticmethod
    def geocode(address: str) -> Tuple[float, float]:
        """Convert address to lat/lon using ORS Geocoding API"""
        # Geocode API does NOT use /v2/
        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            'api_key': RouteService.ORS_API_KEY,
            'text': address
        }
        
        try:
            print(f"Geocoding: {address}...")
            response = requests.get(url, params=params, timeout=10)
            
            # Check for HTTP errors
            if response.status_code != 200:
                print(f"Geocoding API error: {response.status_code}")
                print(f"Response: {response.text[:200]}")
                raise ValueError(f"Geocoding API returned status {response.status_code}")
            
            data = response.json()
            
            # Check if we got results
            if not data.get('features') or len(data['features']) == 0:
                raise ValueError(f"No results found for address: {address}")
            
            # Get the first result (best match)
            coords = data['features'][0]['geometry']['coordinates']
            lat, lon = coords[1], coords[0]  # ORS returns [lon, lat], we need (lat, lon)
            
            location_label = data['features'][0]['properties'].get('label', address)
            print(f"Found: {location_label} at ({lat:.4f}, {lon:.4f})")
            
            return lat, lon
            
        except requests.exceptions.Timeout:
            raise ValueError(f"Geocoding request timed out for: {address}")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Network error during geocoding: {str(e)}")
        except (KeyError, IndexError) as e:
            raise ValueError(f"Unexpected geocoding response format: {str(e)}")
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON response from geocoding API")

    @staticmethod
    def get_route(start: Tuple[float, float], end: Tuple[float, float]) -> Dict:
        """Get route between two points using ORS Directions API"""
        # Directions API DOES use /v2/ and returns GeoJSON
        url = "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"
        
        body = {
            'coordinates': [
                [start[1], start[0]],  # start: [lon, lat]
                [end[1], end[0]]       # end: [lon, lat]
            ]
        }
        
        headers = {
            'Authorization': RouteService.ORS_API_KEY,
            'Content-Type': 'application/json',
            'Accept': 'application/json, application/geo+json'
        }
        
        try:
            print(f"🛣️  Calculating route from ({start[0]:.4f}, {start[1]:.4f}) to ({end[0]:.4f}, {end[1]:.4f})...")
            
            response = requests.post(url, json=body, headers=headers, timeout=30)
            
            # Check for HTTP errors
            if response.status_code != 200:
                print(f"Routing API error: {response.status_code}")
                print(f"Response: {response.text[:500]}")
                
                # Try to parse error message
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', {}).get('message', response.text)
                    raise ValueError(f"Routing API error ({response.status_code}): {error_msg}")
                except:
                    raise ValueError(f"Routing API error ({response.status_code}): {response.text[:200]}")
            
            data = response.json()
            
            # Check if we got a route
            if 'features' not in data or len(data['features']) == 0:
                raise ValueError("No route found between the specified points")
            
            # Extract route from GeoJSON response
            route_feature = data['features'][0]
            properties = route_feature['properties']
            summary = properties.get('summary', {})
            
            distance_meters = summary.get('distance', 0)
            duration_seconds = summary.get('duration', 0)
            
            distance_miles = distance_meters * 0.000621371  # meters to miles
            duration_hours = duration_seconds / 3600  # seconds to hours
            
            # Get route geometry (coordinates for drawing on map)
            geometry = route_feature.get('geometry', {})
            coordinates = geometry.get('coordinates', [])
            
            print(f"Route calculated: {distance_miles:.1f} miles, {duration_hours:.2f} hours")
            
            return {
                'distance_miles': distance_miles,
                'duration_hours': duration_hours,
                'geometry': geometry,
                'coordinates': coordinates
            }
            
        except requests.exceptions.Timeout:
            raise ValueError("Routing request timed out. Please try again.")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Network error during route calculation: {str(e)}")
        except (KeyError, IndexError) as e:
            print(f"Data structure: {data}")
            raise ValueError(f"Unexpected routing response format: {str(e)}")
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON response from routing API")