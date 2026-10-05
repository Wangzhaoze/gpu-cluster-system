from .mock_docker import MockDockerScheduler


class LocalGpuDockerScheduler(MockDockerScheduler):
    """Same durable queue; Docker DeviceRequest supplies physical devices."""

    real_gpu = True
