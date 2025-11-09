# test_redis.py

import redis

try:
    # 1. Corrected the 'host' parameter
    # 2. Added the required 'password' parameter
    r = redis.Redis(
        host='65.2.153.63',
        port=6379,
        password="CallsureAIRedis@2024",
        db=0,
        decode_responses=True  # Optional: automatically decodes responses to strings
    )

    # Check the connection
    r.ping()
    print("Successfully connected to Redis!")

    # Set and get a value
    r.set('test', 'Hello Redis!')
    value = r.get('test')
    print(f"Retrieved value: {value}")

except redis.exceptions.AuthenticationError:
    print("Authentication failed! Please check your password.")
except redis.exceptions.ConnectionError as e:
    print(f"Could not connect to Redis: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")