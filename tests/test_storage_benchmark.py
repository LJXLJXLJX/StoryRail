"""基准样本必须是当前schema的有效上限项目，不能靠旧schema或缺失素材计时。"""

import pytest

from core.structured_director import PROJECT_SCHEMA_VERSION
from scripts.benchmark_project_storage import PNG, create_sample


@pytest.mark.parametrize("kind", ["narration", "drama", "mixed"])
def test_large_benchmark_fixture_is_valid_and_has_real_asset_bytes(tmp_path, kind):
    store = create_sample(tmp_path, kind, 100)
    document = store.read()
    assert document.schema_version == PROJECT_SCHEMA_VERSION
    assert len(document.director_script.scenes) == 100
    assert len(document.generations) == 2000
    assert len(document.director_runs) == 2
    assert document.active_director_run is None
    assert all(g.phase.value == "failed" for g in document.generations)
    asset, content = store.read_asset(document.assets[0].id)
    assert content == PNG and asset.byte_count == len(PNG)
    drivers = {s.driver for s in document.director_script.scenes}
    assert drivers == ({"narration", "drama"} if kind == "mixed" else {kind})
