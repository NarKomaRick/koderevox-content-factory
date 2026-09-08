from dataclasses import dataclass


@dataclass(frozen=True)
class AudioProcessor:
    normalization_enabled: bool = True
    noise_reduction_enabled: bool = False

    def ffmpeg_filter(self) -> str:
        filters: list[str] = []
        if self.noise_reduction_enabled:
            filters.append("afftdn=nf=-25")
        if self.normalization_enabled:
            filters.extend(["loudnorm=I=-16:LRA=11:TP=-1.5", "alimiter=limit=0.95"])
        return ",".join(filters) or "anull"
