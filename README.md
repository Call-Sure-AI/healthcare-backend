# Install dependencies
pip install -r requirements.txt

# Run the server
python -m app.main

# Or use uvicorn directly
uvicorn app.main:app --reload

# ngrok setup
choco install ngrok

ngrok config add_authtoken <AUTH_TOKEN>
ngrok config add-authtoken 33EhWIwBazEFdcloCrHCX0aIQAZ_3AYDYkih9WafwEEQonn5x

# Run ngrok
ngrok http 8080

# To install redis
i Windows - choco install redis-64
ii sudo apt-get install redis-server  # Ubuntu
brew install redis

# To start redis
Linux:
redis-server

Windows:
i Open Powershell as adminstrator
ii memurai

Incoming Call → Twilio Phone Number
                      ↓
                Twilio Media Streams (WebSocket)
                      ↓
                Your FastAPI Server
                      ↓
        ┌─────────────┴─────────────┐
        ↓                           ↓
   Redis Cache                  PostgreSQL
   (conversation state)         (final bookings)
        ↓
   OpenAI Realtime API (GPT-4 + Voice)
        ↓
   Your Appointment APIs


http://13.232.95.198:8000/api/v1/voice/incoming"# CI/CD test" 
"# CI/CD test" 
