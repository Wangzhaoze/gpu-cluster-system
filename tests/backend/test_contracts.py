from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError
from app.schemas import (
    JobSpec,
    EnvSetting,
    UserCreate,
    DebugSpec,
    Login,
    clean_credential,
)
from app.scheduler.mock_docker import first_fit, MockDockerScheduler
from app.storage import DockerStorage


@pytest.mark.parametrize(
    "username",
    [
        "student_gpu",
        "Student_GPU",
        "  student_gpu\n",
        "ｓｔｕｄｅｎｔ＿ｇｐｕ",
        "student_gpu​",
        "　student_gpu ",
    ],
)
def test_login_accepts_username_case_and_paste_padding_without_changing_password(username):
    credentials = Login(username=username, password=" KeepPasswordCase123! ")
    assert credentials.username == "student_gpu"
    assert credentials.password == " KeepPasswordCase123! "


@pytest.mark.parametrize(
    "typed",
    ["Ab-Q0EX_9z!", " Ab-Q0EX_9z! ", "Ａｂ－Ｑ０ＥＸ＿９ｚ！", "Ab-Q0EX_9z!​", "﻿Ab-Q0EX_9z! "],
)
def test_clean_credential_removes_only_invisible_differences(typed):
    assert clean_credential(typed) == "Ab-Q0EX_9z!"
    assert clean_credential("ab-q0ex_9z!") != "Ab-Q0EX_9z!"


@pytest.mark.parametrize(
    "path",
    [
        "/etc",
        "/workspace/../etc",
        "/workspace2",
        "/workspace/a/../../etc",
        "/workspace/a\\b",
        "/workspace/\x00",
    ],
)
def test_reject_workdir_escape(path):
    with pytest.raises(ValidationError):
        JobSpec(command="true", workdir=path)


def test_allow_nested_workspace():
    assert (
        JobSpec(command="true", workdir="/workspace/project/").workdir
        == "/workspace/project"
    )


@pytest.mark.parametrize(
    "key",
    [
        "PATH",
        "VIRTUAL_ENV",
        "LAB_UID",
        "LAB_ASSIGNED_GPUS",
        "NVIDIA_VISIBLE_DEVICES",
        "CUDA_VISIBLE_DEVICES",
        "BAD-KEY",
    ],
)
def test_reserved_environment(key):
    with pytest.raises(ValidationError):
        JobSpec(command="true", env={key: "override"})
    with pytest.raises(ValidationError):
        EnvSetting(key=key, value="override")


def test_mount_contract():
    mounts = DockerStorage().mounts("student01")
    by_target = {m["Target"]: m for m in mounts}
    assert by_target["/datasets"]["ReadOnly"]
    assert by_target["/opt/user-env"]["Type"] == "volume"
    assert by_target["/opt/user-env"]["Source"] == "lab_pyenv_student01"
    assert "/var/run/docker.sock" not in by_target


def test_exclusive_first_fit():
    free = [0, 1, 2, 3, 4]
    a = first_fit(free, 2)
    free = [g for g in free if g not in a]
    b = first_fit(free, 2)
    free = [g for g in free if g not in b]
    c = first_fit(free, 1)
    assert (a, b, c) == ([0, 1], [2, 3], [4])
    assert first_fit([], 1) is None
    assert first_fit([], 0) == []


def test_cancel_does_not_mutate_terminal_state():
    job = MagicMock(status="COMPLETED", cancel_requested=False)
    MockDockerScheduler().cancel(MagicMock(), job)
    assert not job.cancel_requested


def test_resource_validation():
    with pytest.raises(ValidationError):
        DebugSpec(requested_gpus=65)
    with pytest.raises(ValidationError):
        UserCreate(
            username="../../escape", display_name="bad", password="long-password"
        )
    with pytest.raises(ValidationError):
        JobSpec(command="true", requested_ram_mb=0)
