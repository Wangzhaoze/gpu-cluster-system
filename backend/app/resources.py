"""Docker host capacity and shared workspace/workload admission budgets."""
from docker.errors import DockerException
from fastapi import HTTPException
from sqlalchemy import select

from .config import settings
from .docker_runtime import runtime
from .models import Workload
from .scheduler.base import ACTIVE

MIB = 1024**2


def _docker_info():
    return runtime.client.info()


def host_limits():
    info = _docker_info()
    cpus, memory = info.get('NCPU'), info.get('MemTotal')
    if type(cpus) is not int or type(memory) is not int or cpus < 1 or memory < MIB:
        raise DockerException('Docker 返回了无效的主机 CPU/内存容量')
    memory_mb = memory // MIB
    reserve = settings.memory_reserve_mb
    if reserve < 0 or reserve >= memory_mb:
        raise DockerException('系统预留内存必须小于 Docker 主机总内存')
    return {'total_cpus': cpus, 'total_ram_mb': memory_mb,
            'reserved_ram_mb': reserve, 'schedulable_ram_mb': memory_mb - reserve}


def request_error(cpus, ram_mb, limits):
    if cpus > limits['total_cpus']:
        return f"CPU 请求超过主机上限（{limits['total_cpus']} 线程）"
    if ram_mb > limits['schedulable_ram_mb']:
        return f"内存请求超过共享预算（{limits['schedulable_ram_mb'] / 1024:.2f} GB，另为系统预留 {limits['reserved_ram_mb'] / 1024:g} GB）"
    return None


def validate_request(cpus, ram_mb):
    error = request_error(cpus, ram_mb, host_limits())
    if error:
        raise HTTPException(422, error)


def capacity(db, exclude_workspace=None, limits=None):
    limits = limits or host_limits()
    active = list(db.scalars(select(Workload).where(Workload.status.in_(ACTIVE))))
    used_cpus = sum(item.requested_cpus for item in active)
    used_ram = sum(item.requested_ram_mb for item in active)
    workspaces = runtime.client.containers.list(filters={'status': 'running', 'label': [
        'lab.managed=true', f'lab.project={settings.project}', 'lab.kind=workspace']})
    for container in workspaces:
        if container.id == exclude_workspace:
            continue
        config = container.attrs['HostConfig']
        # An old unlimited workspace cannot safely be counted as zero usage.
        used_cpus += (config.get('NanoCpus') or 0) / 1_000_000_000 or limits['total_cpus']
        used_ram += (config.get('Memory') or 0) // MIB or limits['schedulable_ram_mb']
    return {**limits, 'allocated_cpus': used_cpus, 'allocated_ram_mb': used_ram,
            'available_cpus': max(0, limits['total_cpus'] - used_cpus),
            'available_ram_mb': max(0, limits['schedulable_ram_mb'] - used_ram)}


def require_available(db, cpus, ram_mb, exclude_workspace=None):
    current = capacity(db, exclude_workspace=exclude_workspace)
    error = request_error(cpus, ram_mb, current)
    if error:
        raise HTTPException(422, error)
    if cpus > current['available_cpus'] or ram_mb > current['available_ram_mb']:
        raise HTTPException(409, 'CPU 或内存预算不足，请等待其他任务结束或释放工作区资源')
