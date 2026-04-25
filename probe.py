import sys
import os
import asyncio

sys.path.append(os.path.join(os.getcwd(), "phase6-ui", "server"))

async def probe():
    try:
        import voice
        print("Module imported: voice")
        
        phrases = ["One moment.", "Give me a moment to process your query."]
        
        for phrase in phrases:
            print(f"Synthesizing: '{phrase}'")
            audio = await voice.synthesize(phrase)
            if audio:
                header = audio[:4]
                fmt = "Unknown"
                if header.startswith(b"RIFF"): fmt = "WAV"
                elif header.startswith(b"\xff\xfb") or header.startswith(b"ID3"): fmt = "MP3"
                elif header.startswith(b"OggS"): fmt = "OGG"
                
                print(f"  Result: Success")
                print(f"  Length: {len(audio)} bytes")
                print(f"  Format: {fmt} (Header: {header.hex()})")
            else:
                print(f"  Result: No audio data produced")
    except Exception as e:
        print(f"Error during probe: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(probe())
