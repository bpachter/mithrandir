import asyncio
import os
import sys
import time

# Mock logger
class MockLogger:
    def info(self, msg): print(f'[INFO] {msg}')
    def warning(self, msg): print(f'[WARN] {msg}')
    def error(self, msg): print(f'[ERROR] {msg}')

# Add current directory to path
sys.path.append('phase6-ui/server')

try:
    import voice
    # Inject mock logger
    voice.logger = MockLogger()
except ImportError as e:
    print(f'Import error: {e}')
    sys.exit(1)

async def probe():
    profile = 'mithrandir'
    phrases = ['One moment.', 'Give me a moment to process your query.']
    
    # We want to test _synthesize_prelude_strict logic.
    # In main.py:
    # async def _synthesize_prelude_strict(voice, text, requested_profile):
    #     profile = requested_profile
    #     if hasattr(voice, '_resolve_voice_profile'):
    #         profile = voice._resolve_voice_profile(requested_profile)
    #     if profile in ('mithrandir', 'gandalf'):
    #         wav = await voice.synth_prelude(text, profile)
    #         return wav, 'wav', profile
    #     return b'', 'wav', profile

    print(f'--- Probing Profile: {profile} ---')
    
    # Check if voice.synth_prelude is available
    if not hasattr(voice, 'synth_prelude'):
        print('voice.synth_prelude not found. Checking voice.py for it...')
        # Let's try to find where it is defined
        return

    for text in phrases:
        start_time = time.time()
        print(f'Testing phrase: \"{text}\"')
        try:
            # Emulate the dispatch logic
            resolved_profile = voice._resolve_voice_profile(profile)
            print(f'Resolved profile: {resolved_profile}')
            
            # Call synth_prelude directly
            # Note: synth_prelude might be async or sync depending on implementation
            # Based on main.py, it is awaited: await voice.synth_prelude(text, profile)
            if resolved_profile in ('mithrandir', 'gandalf'):
                audio_bytes = await voice.synth_prelude(text, resolved_profile)
                end_time = time.time()
                duration = end_time - start_time
                
                if audio_bytes:
                    print(f'Produced {len(audio_bytes)} bytes.')
                    print(f'Timing: {duration:.4f}s')
                else:
                    print('Produced NO audio bytes.')
                    print(f'Timing (fail): {duration:.4f}s')
            else:
                print(f'Profile {resolved_profile} not in (mithrandir, gandalf), would skip.')
        except Exception as e:
            print(f'Error during synthesis: {e}')
        print('---')

if __name__ == '__main__':
    asyncio.run(probe())
