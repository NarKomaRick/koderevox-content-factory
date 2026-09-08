from app.main import app


def test_phase3_openapi_exposes_video_project_workflow() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        "/sources/{source_id}/video-projects": "post",
        "/sources/{source_id}/video-projects/manual": "post",
        "/video-projects/{video_project_id}": "get",
        "/video-projects/{video_project_id}/generate-edit-plan": "post",
        "/video-projects/{video_project_id}/render": "post",
        "/video-projects/{video_project_id}/rerender": "post",
        "/video-projects/{video_project_id}/approve": "post",
        "/video-projects/{video_project_id}/archive": "post",
    }
    for path, method in expected.items():
        assert method in paths[path]
