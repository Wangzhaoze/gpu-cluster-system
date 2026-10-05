#include <cstdio>
#include <cuda_runtime.h>

__global__ void answer(int *value) { *value = 42; }

int main() {
    int count = 0;
    if (cudaGetDeviceCount(&count) != cudaSuccess || count < 1) return 1;
    cudaDeviceProp device{};
    if (cudaGetDeviceProperties(&device, 0) != cudaSuccess) return 2;
    int *gpu = nullptr;
    if (cudaMalloc(&gpu, sizeof(int)) != cudaSuccess) return 3;
    answer<<<1, 1>>>(gpu);
    if (cudaGetLastError() != cudaSuccess || cudaDeviceSynchronize() != cudaSuccess) return 4;
    int result = 0;
    if (cudaMemcpy(&result, gpu, sizeof(int), cudaMemcpyDeviceToHost) != cudaSuccess) return 5;
    if (cudaFree(gpu) != cudaSuccess) return 6;
    std::printf("CUDA_KERNEL_OK GPU=%s result=%d\n", device.name, result);
    return result == 42 ? 0 : 7;
}
