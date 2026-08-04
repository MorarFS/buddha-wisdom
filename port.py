import os
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from flask_cors import CORS
from query_sutta_corpus import buddha_wisdom  # Assuming this is your wisdom-seeking function
from markdown import markdown
import requests
import shutil

app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing

# --- Use the locally provided Dharma Wheel image ---
IMAGE_FILENAME = "dharma_wheel.png"
IMAGE_PATH = "/home/stefan_morar/512px-Dharma_Wheel_Rotating.svg.png"  # Use the path provided
STATIC_DIR = os.path.join(app.root_path, "static")
LOCAL_IMAGE_DESTINATION = os.path.join(STATIC_DIR, IMAGE_FILENAME)

# Ensure the 'static' directory exists
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# Copy the image to the static folder if it doesn't exist
if not os.path.exists(LOCAL_IMAGE_DESTINATION):
    try:
        shutil.copy(IMAGE_PATH, LOCAL_IMAGE_DESTINATION)
        print(f"Image copied successfully to {LOCAL_IMAGE_DESTINATION}")
    except FileNotFoundError:
        print(f"Error: Image not found at {IMAGE_PATH}")
    except Exception as e:
        print(f"An unexpected error occurred while copying the image: {e}")

# --- Serve the static image ---
@app.route("/static/<path:filename>")
def serve_static(filename):
    """Serves static files from the 'static' directory."""
    return send_from_directory("static", filename)

# Enhanced HTML template with Markdown support, loading animation, and Buddhist styling
chat_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Buddha's Wisdom Chat</title>
    <style>
        body {
            font-family: 'Times New Roman', serif; /* More traditional font */
            background-color: #f8f0e3; /* Light beige background */
            color: #5c4033; /* Dark brown text */
            margin: 0; /* Remove default margins */
            display: flex;
            flex-direction: column;
            min-height: 100vh; /* Ensure full viewport height */
        }
        h1 {
            text-align: center;
            color: #8b4513; /* Brown header */
            padding: 20px;
            background-color: #f0e6d2; /* Light tan header background */
            margin: 0;
        }
        #chatbox {
            border: 2px solid #d2b48c; /* Light brown border */
            padding: 20px;
            margin: 20px;
            flex-grow: 1; /* Allow chatbox to take up available space */
            overflow-y: auto;
            background-color: #fffaf0; /* Off-white chatbox background */
            border-radius: 10px;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1); /* Subtle shadow */
        }
        .message {
            margin-bottom: 15px;
            padding: 10px;
            border-radius: 8px;
        }
        .user {
            color: #2e8b57; /* Sea green for user */
            background-color: #e0f0e0; /* Light green background for user */
            text-align: right;
        }
        .buddha {
            color: #8b4513; /* Brown for Buddha */
            background-color: #f5f5dc; /* Beige background for Buddha */
            text-align: left;
        }
        .error {
            color: #cc0000; /* Dark red for errors */
            background-color: #ffe0e0; /* Light red background for errors */
        }
        /* Basic styling for Markdown elements */
        p {
            margin-bottom: 10px;
            line-height: 1.6; /* Improved readability */
        }
        em, i {
            font-style: italic;
        }
        strong, b {
            font-weight: bold;
        }
        h1, h2, h3, h4, h5, h6 {
            margin-top: 1em;
            margin-bottom: 0.5em;
            color: #8b4513; /* Brown headers */
        }
        pre {
            background-color: #f0f0f0;
            padding: 10px;
            overflow-x: auto;
            border-radius: 5px;
        }
        code {
            font-family: monospace;
        }
        blockquote {
            border-left: 5px solid #d2b48c; /* Light brown border */
            padding-left: 15px;
            margin-left: 0;
            font-style: italic;
        }
        /* Loading animation styles */
        #loading {
            display: none; /* Hidden by default */
            text-align: center;
            margin-top: 20px;
        }
        .dharma-wheel-container {
            display: inline-block;
            width: 60px; /* Slightly larger */
            height: 60px; /* Slightly larger */
            position: relative;
        }
        .dharma-wheel {
            position: absolute;
            width: 100%;
            height: 100%;
            animation: rotate 10s linear infinite;
        }
        @keyframes rotate {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        /* Input and button styling */
        input[type="text"] {
            width: calc(100% - 100px); /* Adjust width */
            padding: 10px;
            margin: 20px;
            border: 1px solid #d2b48c;
            border-radius: 5px;
            font-size: 16px;
        }
        button {
            padding: 10px 20px;
            background-color: #8b4513; /* Brown button */
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
        }
        button:hover {
            background-color: #a0522d; /* Darker brown on hover */
        }
        /* Full-screen chatbox */
        html, body {
            height: 100%;
        }
        #chatbox {
            height: calc(100vh - 150px); /* Adjust height to fit screen */
            margin: 20px auto;
            width: 90%;
            max-width: 1200px;
        }
        .message strong {
            color: #8b4513;
        }
    </style>
</head>
<body>
    <h1>Buddha's Wisdom Chat</h1>
    <div id="chatbox">
        <div class="message buddha"><strong>Buddha:</strong> Welcome! Ask me anything about the Dharma.</div>
    </div>
    <div id="loading">
        <div class="dharma-wheel-container">
            <img class="dharma-wheel" src="/static/{{ image_filename }}" alt="Dharma Wheel">
        </div>
        <p>Seeking wisdom...</p>
    </div>
    <input type="text" id="inputBox" placeholder="Type your question here..." />
    <button id="sendButton">Send</button>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const inputBox = document.getElementById('inputBox');
            const sendButton = document.getElementById('sendButton');
            const chatbox = document.getElementById('chatbox');
            const loading = document.getElementById('loading');

            function sendMessage() {
                const message = inputBox.value.trim();
                if (message === "") return;
                inputBox.value = "";

                // Add the user message to the chatbox
                const userMsg = document.createElement('div');
                userMsg.classList.add('message', 'user');
                userMsg.innerHTML = "<strong>You:</strong> " + message;
                chatbox.appendChild(userMsg);
                chatbox.scrollTop = chatbox.scrollHeight; // Scroll to bottom

                // Show the loading animation
                loading.style.display = "block";

                // Send the message to the backend
                fetch("/query", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({query: message})
                })
                .then(response => response.json())
                .then(data => {
                    // Hide the loading animation
                    loading.style.display = "none";

                    const botMsg = document.createElement('div');
                    botMsg.classList.add('message', 'buddha');
                    botMsg.innerHTML = "<strong>Buddha:</strong> " + data.response;
                    chatbox.appendChild(botMsg);
                    chatbox.scrollTop = chatbox.scrollHeight; // Scroll to bottom
                })
                .catch(error => {
                    // Hide the loading animation
                    loading.style.display = "none";

                    console.error("Error:", error);
                    const errorMsg = document.createElement('div');
                    errorMsg.classList.add('message', 'error');
                    errorMsg.innerHTML = "<strong>Buddha:</strong> I encountered an error.";
                    chatbox.appendChild(errorMsg);
                    chatbox.scrollTop = chatbox.scrollHeight; // Scroll to bottom
                });
            }

            sendButton.addEventListener("click", sendMessage);

            inputBox.addEventListener("keypress", function(event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    sendMessage();
                }
            });
        });
    </script>
</body>
</html>
"""

@app.route("/", methods=['GET'])
def index():
    """Serves the enhanced chat interface."""
    return render_template_string(chat_template, image_filename=IMAGE_FILENAME)

@app.route("/query", methods=['POST'])
def query():
    """Handles user queries, converts Markdown to HTML, and returns Buddha's response."""
    data = request.get_json()
    user_query = data.get('query')
    if not user_query:
        return jsonify({'error': 'No query provided'}), 400
    try:
        response = buddha_wisdom(user_query)
        # Convert Markdown to HTML
        html_response = markdown(response)
        return jsonify({'response': html_response})
    except Exception as e:
        print(f"Error in /query: {e}")
        return jsonify({'response': "I encountered an error processing your request."}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
