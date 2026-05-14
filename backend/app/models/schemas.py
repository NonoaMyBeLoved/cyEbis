from pydantic import BaseModel, Field


class StemInfo(BaseModel):
    name: str
    label: str
    url: str
    waveform_url: str
    duration: float
    active: bool = True


class ArtifactInfo(BaseModel):
    name: str
    instrument: str
    kind: str
    url: str


class JobStatus(BaseModel):
    id: str
    status: str
    progress: float = Field(ge=0, le=1)
    message: str
    source_name: str | None = None
    warnings: list[str] = []
    stems: list[StemInfo] = []
    artifacts: list[ArtifactInfo] = []
    original_url: str | None = None
    created_at: str
    completed_at: str | None = None


class CreateJobResponse(BaseModel):
    id: str
    status_url: str


class TabResponse(BaseModel):
    instrument: str
    artifacts: list[ArtifactInfo]
    warnings: list[str] = []


class MixTrack(BaseModel):
    name: str
    volume: float = Field(ge=0, le=1.5)
    muted: bool = False
    active: bool = True


class MixRequest(BaseModel):
    tracks: list[MixTrack]
    solo: str | None = None
