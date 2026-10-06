"""Verify CUDA tensor operations on every GPU visible inside this container."""

import torch

assert torch.cuda.is_available(), "PyTorch cannot access CUDA; check the NVIDIA Container Toolkit"
assert torch.version.cuda == "12.8", torch.version.cuda
print(f"PyTorch {torch.__version__}; CUDA {torch.version.cuda}; architectures {torch.cuda.get_arch_list()}", flush=True)
for index in range(torch.cuda.device_count()):
    device = torch.device(f"cuda:{index}")
    matrix = torch.ones((128, 128), device=device)
    product = matrix @ matrix
    torch.cuda.synchronize(device)
    assert product[0, 0].item() == 128
    print(f"TORCH_CUDA_OK GPU={index} name={torch.cuda.get_device_name(index)} capability={torch.cuda.get_device_capability(index)}", flush=True)
