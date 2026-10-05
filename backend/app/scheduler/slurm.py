class SlurmScheduler:
    def __init__(self):
        raise NotImplementedError(
            "Slurm is a migration boundary only; use mock-docker or local-gpu-docker for the Windows POC"
        )
