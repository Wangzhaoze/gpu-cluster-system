from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.auth import current_user
from app.gpu_telemetry import parse_nvidia_smi_csv, read_telemetry
from app.main import app, validate_resources
from app.schemas import DebugSpec, JobSpec, UserCreate
from app.scheduler.mock_docker import MockDockerScheduler, first_fit


@pytest.mark.parametrize('spec,values', [
    (JobSpec, {'requested_gpus': 1, 'gpu_indices': [1, 2]}),
    (JobSpec, {'requested_gpus': 2, 'gpu_indices': [1, 1]}),
    (JobSpec, {'requested_gpus': 1, 'gpu_indices': [-1]}),
    (JobSpec, {'requested_gpus': 1, 'gpu_indices': [True]}),
    (DebugSpec, {'requested_gpus': 0, 'gpu_indices': [0]}),
])
def test_invalid_gpu_choices_rejected(spec, values):
    with pytest.raises(ValidationError):
        spec(**({'command': 'true'} if spec is JobSpec else {}), **values)


def test_exact_selection_waits_for_those_cards_and_preserves_order():
    assert first_fit([0, 1, 2], 2, [2, 0]) == [2, 0]
    assert first_fit([0, 1], 1, [2]) is None
    assert first_fit([0, 1], 2, [0, 2]) is None
    assert first_fit([0], 0, []) == []


def test_ten_hour_boundary_and_required_reason():
    assert UserCreate(username='testuser', display_name='Test', password='long-password').max_debug_hours == 10
    spec = DebugSpec(time_limit_seconds=36000)
    validate_resources(SimpleNamespace(max_gpus=1, max_debug_hours=10), spec)
    with pytest.raises(ValidationError):
        DebugSpec(time_limit_seconds=36001)
    long = DebugSpec(time_limit_seconds=39600, approval_reason='Long interactive experiment')
    resource = MockDockerScheduler().start_debug(MagicMock(), SimpleNamespace(id='user'), long)
    assert resource.status == 'AWAITING_APPROVAL'
    assert resource.approval_status == 'PENDING'
    assert resource.container_id is None and resource.assigned_gpus_json is None


def test_unapproved_long_debug_cannot_be_launched(monkeypatch):
    scheduler = MockDockerScheduler()
    finish = MagicMock()
    monkeypatch.setattr(scheduler, 'finish', finish)
    resource = SimpleNamespace(kind='debug', time_limit_seconds=39600, approval_status='PENDING')
    scheduler.launch(MagicMock(), resource)
    assert finish.call_args.args[3] == 'FAILED'


@pytest.mark.parametrize('decision', ['approve', 'reject'])
def test_members_cannot_approve_their_own_long_debug(decision):
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id='unknown', role='MEMBER')
    try:
        assert TestClient(app).post('/api/debug/unknown/' + decision, json={}).status_code == 403
    finally:
        app.dependency_overrides.clear()
    assert TestClient(app).post('/api/debug/unknown/' + decision, json={}).status_code == 401


def test_monitor_parses_real_units_and_unavailable_fields():
    gpus = parse_nvidia_smi_csv('2, GPU-abc, 0000:03:00.0, NVIDIA RTX 5060 Ti, 595.84, 16311, 1200, 15000, 95, 12, 65, 130.25, 180, [N/A], 2800, 13801')
    gpu = gpus['2']
    assert gpu['utilization_percent'] == 95 and gpu['temperature_c'] == 65
    assert gpu['power_w'] == 130.25 and gpu['fan_percent'] is None
    assert gpu['memory_total_mb'] == 16311 and gpu['uuid'] == 'GPU-abc'


def test_stale_or_mock_telemetry_never_looks_live(tmp_path):
    path = tmp_path / 'sample.json'
    assert read_telemetry(path, 'local-gpu-docker')['status'] == 'unavailable'
    path.write_text(json.dumps({'sampled_at': (datetime.now(timezone.utc)-timedelta(seconds=30)).isoformat(),
                              'gpus': {'0': {'utilization_percent': 99}}, 'error': None}))
    stale = read_telemetry(path, 'local-gpu-docker')
    assert stale['status'] == 'stale' and not stale['gpus']
    assert read_telemetry(path, 'mock-docker')['status'] == 'mock'
