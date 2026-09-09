"""Run the complete local video-generation capability test.

This delegates to the existing Phase 4.5 production smoke pipeline so the test
uses the real ProductionProject, VoiceoverTrack, materials, timeline revisions,
and renderer rather than a parallel demo implementation.
"""

from phase45_smoke import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
