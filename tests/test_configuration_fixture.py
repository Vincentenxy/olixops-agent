from pathlib import Path

from app.integrations.gitlab.templates import LocalFixtureTemplateProvider, render_redis


def test_local_redis_fixture_lists_and_renders() -> None:
    provider = LocalFixtureTemplateProvider(Path("fixtures/gitlab"))
    templates = provider.list_templates()
    assert [item.template_id for item in templates] == ["redis/standalone/v1"]
    package = provider.get_template("redis/standalone/v1", "fixture-main-redis-v1")
    manifest = render_redis(
        package,
        {
            "name": "demo-redis",
            "namespace": "default",
            "image": "redis:7.2-alpine",
            "replicas": 1,
            "port": 6379,
        },
    )
    assert "kind: Deployment" in manifest
    assert "name: demo-redis" in manifest
    assert "namespace: default" in manifest
