# test_ws.py - LOCAL TESTING ONLY
import asyncio
import websockets
import json

async def test():
    # Use ws:// for local (no SSL)
    uri = "ws://127.0.0.1:8000/api/v1/voice/stream?call_sid=TEST123"
    
    try:
        print(f"Connecting to {uri}...")
        async with websockets.connect(uri) as websocket:
            print("✅ Connected!")
            
            # Simulate Twilio start event
            await websocket.send(json.dumps({
                "event": "start",
                "streamSid": "MZ_test"
            }))
            print("📤 Sent start event")
            
            # Receive response
            msg = await asyncio.wait_for(websocket.recv(), timeout=3)
            print(f"📨 {msg}")
            
            # Stop
            await websocket.send(json.dumps({"event": "stop"}))
            
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")

asyncio.run(test())
