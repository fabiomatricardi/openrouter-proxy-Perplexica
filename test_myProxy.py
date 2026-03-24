import requests
import json

# Configuration
url = "http://localhost:5555/api/v1/chat/completions"
headers = {
    "Authorization": "Bearer openrouter",
    "Content-Type": "application/json"
}

# The payload
data = {
    "model": "openrouter",
    "messages": [
        {"role": "user", "content": "Hello!"}
    ],
    "stream": False  # you can change to True to test the streaming effect
}

try:
    # Use stream=True in the request call to handle the chunked response
    response = requests.post(url, headers=headers, json=data, stream=True)

    # Check if the server returned an error (like your 401/403 Invalid Access Key)
    if response.status_code != 200:
        print(f"Error {response.status_code}: {response.text}")
    else:
        print("Connection successful! Reading stream...")
        
        # Iterate over the lines of the response
        for line in response.iter_lines():
            if line:
                # Remove the 'data: ' prefix typically used in SSE streams
                decoded_line = line.decode('utf-8')
                print(decoded_line)

except requests.exceptions.ConnectionError:
    print("Error: Could not connect to the server. Is the simulation running on port 5555?")
