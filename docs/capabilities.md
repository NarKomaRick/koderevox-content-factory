# Capability matrix

| Feature | Implemented | Offline tested | Real provider tested | Production verified |
|---|---:|---:|---:|---:|
| Phase 7 Director runtime | yes | yes | no | no |
| Phase 8 Producer/research | yes | yes | no | no |
| Phase 9 multi-item planning | yes | yes | no | no |
| Durable pipeline progress | yes | yes | no | no |
| Producer/Director stage visibility | yes | yes | no | no |
| ETA from timing history | yes | yes | no | no |
| Telegram same-message progress watcher | yes | formatter/path only | no | no |
| Live web research | provider contract only | fake only | no | no |
| FFmpeg rendering | existing path | environment-dependent | no | no |
| Vision | existing opt-in path | mock/offline | no | no |
| Publishing | existing platform subsystem | fake capability only | no | no |

Host validation note: FFmpeg 9.0.1 and eSpeak NG 1.52.0 were installed user-local and the existing real render/TTS tests passed. This does not constitute production video-pipeline or platform-publishing validation.
