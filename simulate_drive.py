import requests
import time
import random

# ==========================================
# SIMULATOR CONFIGURATION
# ==========================================
BASE_URL = "https://app.bratelus.com"
USERNAME = "bratelus" 
PASSWORD = "YOUR_PASSWORD_HERE"

# Starting location: Downtown Fort Lauderdale / Las Olas
current_lat = 26.122400
current_lng = -80.137300

def run_simulator():
    print("🚗 Starting Mobile Tracker Simulator...")
    session = requests.Session()

    # 1. Grab the initial CSRF security token
    print("🔐 Authenticating...")
    login_url = f"{BASE_URL}/accounts/login/"
    session.get(login_url)
    csrftoken = session.cookies.get('csrftoken')

    # 2. Log into the web application
    login_data = {
        'username': 'root',               # ADDED: Quotes around 'root'
        'password': '!Xyzsun123',         # ADDED: Quotes around the password
        'csrfmiddlewaretoken': csrftoken, # ADDED: The comma at the end of this line
        'next': '/jobs/'
    }
    headers = {'Referer': login_url}
    session.post(login_url, data=login_data, headers=headers)

    if "sessionid" not in session.cookies:
        print("❌ Login failed! Check your username and password.")
        return

    print("✅ Login successful! Firing up the engine...")
    print("-" * 40)
    
    # 3. Start "Driving"
    api_url = f"{BASE_URL}/api/mobile/track-location/"
    
    for i in range(1, 100): # Drive for 100 pings
        api_headers = {
            'X-CSRFToken': session.cookies.get('csrftoken'),
            'Referer': f"{BASE_URL}/jobs/"
        }
        
        # Simulate driving North by slightly increasing the latitude
        global current_lat, current_lng
        current_lat += random.uniform(0.0008, 0.0015) 
        current_lng += random.uniform(-0.0002, 0.0002)

        payload = {
            "latitude": current_lat,
            "longitude": current_lng,
            "accuracy": 5.0
        }

        print(f"📍 Ping {i}: Sending Location ({current_lat:.5f}, {current_lng:.5f})...", end=" ")
        
        # Hit your new API endpoint!
        res = session.post(api_url, json=payload, headers=api_headers)
        
        if res.status_code == 200:
            print("Success!")
        else:
            print(f"Failed! HTTP {res.status_code}")

        # Wait 5 seconds before the next ping
        time.sleep(5)

if __name__ == "__main__":
    run_simulator()
