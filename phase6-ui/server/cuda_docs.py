"""
cuda_docs.py — Curated CUDA + Gemma4 reference data for Mithrandir.

Structured so the /api/docs endpoint can serve it to the UI, and the
search_docs agent tool can query it inline during conversations.

All hardware specs are specific to Ben's RTX 4090 (Ada Lovelace, sm_89).
"""

from __future__ import annotations

DOCS: list[dict] = [

    # ─────────────────────────────────────────────────────────────────────
    # CATEGORY: rtx4090 — Hardware you're running on
    # ─────────────────────────────────────────────────────────────────────

    {
        "id": "hw-ada-overview",
        "category": "rtx4090",
        "title": "RTX 4090 — Ada Lovelace Overview",
        "summary": "Your GPU is NVIDIA Ada Lovelace (sm_89). 16,384 FP32 CUDA cores across 128 SMs, 24 GB GDDR6X at 1,008 GB/s.",
        "detail": (
            "The RTX 4090 uses NVIDIA's Ada Lovelace architecture (compute capability 8.9). "
            "Key improvements over Ampere (3090): 4th-gen Tensor Cores with FP8 support, "
            "improved L2 cache (72 MB vs 6 MB), 3rd-gen RT cores, and the new Optical Flow Accelerator.\n\n"
            "For CUDA development, the most relevant change is the **massive L2 cache**: "
            "72 MB means many workloads that were memory-bound on previous GPUs now fit in cache. "
            "Compute capability 8.9 is required for FP8 Tensor Core instructions."
        ),
        "specs": [
            ("CUDA Cores", "16,384 (128 SMs × 128 cores/SM)"),
            ("Tensor Cores", "512 (4th-gen, FP8/FP16/BF16/TF32/INT8)"),
            ("RT Cores", "128 (3rd-gen)"),
            ("VRAM", "24 GB GDDR6X"),
            ("Memory Bandwidth", "1,008 GB/s"),
            ("L2 Cache", "72 MB"),
            ("Boost Clock", "2,520 MHz"),
            ("FP32 TFLOPS", "82.6"),
            ("BF16 TFLOPS", "165.2"),
            ("INT8 TOPS", "660.6"),
            ("Compute Capability", "8.9 (Ada Lovelace)"),
            ("TDP", "450 W"),
        ],
        "example": None,
        "tags": ["ada", "lovelace", "rtx4090", "hardware", "compute capability", "sm_89"],
    },

    {
        "id": "hw-sm-structure",
        "category": "rtx4090",
        "title": "Streaming Multiprocessor (SM) Architecture",
        "summary": "Each of the 128 SMs on your 4090 is an independent compute unit. Understanding SM resources is the key to writing high-performance kernels.",
        "detail": (
            "One SM on Ada Lovelace (sm_89) has:\n"
            "- 128 FP32/INT32 CUDA cores (split into 4 warps schedulers × 32 cores)\n"
            "- 4 Tensor Core units (4th-gen)\n"
            "- 1 RT Core\n"
            "- 128 KB L1 data cache / shared memory (configurable split)\n"
            "- 65,536 32-bit registers (shared among all resident threads)\n"
            "- Max 1,536 resident threads (48 warps × 32 threads)\n"
            "- Max 32 resident thread blocks\n\n"
            "The SM is the unit of resource allocation. All threads in a block run on the **same** SM, "
            "sharing its L1/shared memory and registers. A kernel's per-thread register count "
            "and per-block shared memory directly determine how many blocks can run concurrently per SM "
            "(this is **occupancy**)."
        ),
        "specs": [
            ("SMs on RTX 4090", "128"),
            ("CUDA cores per SM", "128"),
            ("Registers per SM", "65,536 × 32-bit"),
            ("Max threads per SM", "1,536"),
            ("Max warps per SM", "48"),
            ("Max blocks per SM", "32"),
            ("L1/Shared Memory", "128 KB (configurable 0-100 KB shared)"),
            ("Warp Schedulers per SM", "4"),
        ],
        "example": (
            "# Check SM resource usage at compile time (CUDA C++)\n"
            "# nvcc -arch=sm_89 --ptxas-options=-v mykernel.cu\n"
            "# Output: registers, smem per block, spill stores\n\n"
            "# Python: check SM count\n"
            "import torch\n"
            "print(torch.cuda.get_device_properties(0).multi_processor_count)  # 128"
        ),
        "tags": ["sm", "streaming multiprocessor", "registers", "shared memory", "occupancy", "warp scheduler"],
    },

    {
        "id": "hw-tensor-cores",
        "category": "rtx4090",
        "title": "4th-Gen Tensor Cores & Supported Precisions",
        "summary": "Tensor Cores are matrix-multiply-accumulate (MMA) units that power cuBLAS, cuDNN, and every LLM inference operation. The 4090 adds FP8 for 2× throughput vs FP16.",
        "detail": (
            "Ada Lovelace Tensor Cores support these precisions:\n\n"
            "| Precision | Use Case | 4090 Throughput |\n"
            "|-----------|----------|------------------|\n"
            "| FP32 (TF32) | Training (default PyTorch AMP) | 82.6 TFLOPS |\n"
            "| FP16/BF16 | Inference, mixed training | 165.2 TFLOPS |\n"
            "| INT8 | Quantized inference | 660.6 TOPS |\n"
            "| FP8 (E4M3/E5M2) | New in Ada — ultra-fast inference | ~1,321 TOPS |\n\n"
            "When running Gemma4 26B via Ollama:\n"
            "- Default (Q4_K_M): ~65 tokens/sec — uses INT4 dequant + FP16 compute\n"
            "- FP16 would require 52 GB VRAM — doesn't fit on a single 4090\n"
            "- Q8_0: ~30 tokens/sec — higher quality, fits in 28 GB (just over 4090 VRAM)\n\n"
            "Enable TF32 for all FP32 ops in PyTorch:\n"
            "```python\n"
            "torch.backends.cuda.matmul.allow_tf32 = True\n"
            "torch.backends.cudnn.allow_tf32 = True\n"
            "```"
        ),
        "specs": [
            ("FP32 (TF32)", "82.6 TFLOPS"),
            ("FP16 / BF16", "165.2 TFLOPS"),
            ("INT8", "660.6 TOPS"),
            ("FP8 (E4M3/E5M2)", "~1,321 TOPS (Ada new)"),
            ("MMA tile size (FP16)", "16×16×16"),
        ],
        "example": (
            "import torch\n"
            "# Check if tensor cores are being used\n"
            "torch.backends.cuda.matmul.allow_tf32 = True  # Use TF32 Tensor Cores for FP32\n"
            "torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = True\n\n"
            "# Profile GEMM to see tensor core utilization:\n"
            "# nsys profile --stats=true python script.py\n"
            "# Look for 'gemm_splitk_kernel' or 'volta_h884gemm' in output"
        ),
        "tags": ["tensor cores", "fp16", "bf16", "fp8", "int8", "tf32", "matmul", "mma", "precision"],
    },

    # ─────────────────────────────────────────────────────────────────────
    # CATEGORY: memory — Memory hierarchy
    # ─────────────────────────────────────────────────────────────────────

    {
        "id": "mem-hierarchy",
        "category": "memory",
        "title": "CUDA Memory Hierarchy — Overview",
        "summary": "Global → L2 → L1/Shared → Registers. Each level is faster but smaller. Profiling almost always reveals memory as the bottleneck — not compute.",
        "detail": (
            "Memory hierarchy on RTX 4090 (fastest to slowest):\n\n"
            "| Level | Size | Bandwidth | Latency | Scope |\n"
            "|-------|------|-----------|---------|-------|\n"
            "| Registers | 256 KB/SM | ~20 TB/s | ~1 cycle | Per-thread |\n"
            "| L1/Shared | 128 KB/SM | ~20 TB/s | ~30 cycles | Per-block |\n"
            "| L2 Cache | 72 MB | ~7 TB/s | ~200 cycles | Chip-wide |\n"
            "| GDDR6X | 24 GB | ~1,008 GB/s | ~600 cycles | All threads |\n\n"
            "**The golden rule:** every byte brought from global memory costs ~600 cycles. "
            "Copy data into shared memory once, reuse it many times within the block. "
            "The Ada L2 (72 MB) is large enough to hold entire activations for many LLM layers "
            "— this is why the 4090 performs so well for inference.\n\n"
            "Most kernels are **memory-bandwidth-bound**, not compute-bound. "
            "Measure bandwidth utilization with Nsight Compute before optimizing compute."
        ),
        "specs": [
            ("Registers", "~256 KB/SM, ~1-cycle latency"),
            ("L1 / Shared", "128 KB/SM configurable, ~30-cycle latency"),
            ("L2 Cache", "72 MB chip-wide, ~200-cycle latency"),
            ("GDDR6X (Global)", "24 GB, 1,008 GB/s, ~600-cycle latency"),
        ],
        "example": None,
        "tags": ["memory", "global", "shared", "l1", "l2", "registers", "bandwidth", "latency", "hierarchy"],
    },

    {
        "id": "mem-shared",
        "category": "memory",
        "title": "Shared Memory — The Programmer-Managed Cache",
        "summary": "Shared memory is 100× faster than global memory and is explicitly managed by the programmer. Use it to cache tiles of data that multiple threads in a block reuse.",
        "detail": (
            "Shared memory (`__shared__`) is on-chip SRAM located in the same physical block as L1. "
            "On Ada Lovelace, each SM has 128 KB total L1+shared, configurable up to 100 KB shared.\n\n"
            "**When to use shared memory:**\n"
            "- Each global memory location is read more than once per block\n"
            "- Adjacent threads need overlapping data (stencil ops, matrix multiply)\n"
            "- You need fine-grained synchronization between threads\n\n"
            "**Bank conflicts:** Shared memory is divided into 32 banks (4-byte each). "
            "If multiple threads in a warp access the same bank simultaneously (different addresses), "
            "the accesses serialize. Avoid by using padding or restructuring access patterns.\n\n"
            "**Dynamic vs static allocation:**\n"
            "- Static: `__shared__ float tile[32][32];` — size known at compile time\n"
            "- Dynamic: `extern __shared__ float smem[];` + `<<<grid, block, smem_bytes>>>` — flexible"
        ),
        "specs": [
            ("Size per SM", "Up to 100 KB (Ada)"),
            ("Banks", "32 banks × 4 bytes = 128 bytes/bank"),
            ("Bank width", "4 bytes (32-bit)"),
            ("Bandwidth", "~100 TB/s aggregate (all SMs)"),
        ],
        "example": (
            "// Tiled matrix multiply — classic shared memory use\n"
            "__global__ void matmul(float *A, float *B, float *C, int N) {\n"
            "    __shared__ float tileA[TILE][TILE];\n"
            "    __shared__ float tileB[TILE][TILE];\n"
            "    int row = blockIdx.y * TILE + threadIdx.y;\n"
            "    int col = blockIdx.x * TILE + threadIdx.x;\n"
            "    float sum = 0.0f;\n"
            "    for (int t = 0; t < N/TILE; t++) {\n"
            "        tileA[threadIdx.y][threadIdx.x] = A[row*N + t*TILE + threadIdx.x];\n"
            "        tileB[threadIdx.y][threadIdx.x] = B[(t*TILE + threadIdx.y)*N + col];\n"
            "        __syncthreads();  // ensure both tiles are fully loaded\n"
            "        for (int k = 0; k < TILE; k++) sum += tileA[threadIdx.y][k] * tileB[k][threadIdx.x];\n"
            "        __syncthreads();  // ensure consumption before next iteration\n"
            "    }\n"
            "    C[row*N + col] = sum;\n"
            "}"
        ),
        "tags": ["shared memory", "bank conflicts", "tiling", "smem", "cache", "__shared__", "__syncthreads"],
    },

    {
        "id": "mem-coalescing",
        "category": "memory",
        "title": "Global Memory Coalescing",
        "summary": "When 32 threads in a warp read global memory, the hardware merges adjacent accesses into the fewest possible 128-byte transactions. Strided or random access can waste 32× bandwidth.",
        "detail": (
            "Global memory reads/writes are serviced in **128-byte cache lines**. "
            "A warp of 32 threads each accessing a 4-byte float spans 128 bytes — exactly one cache line. "
            "If these 32 accesses map to consecutive addresses (coalesced), that's **1 transaction**. "
            "If each thread accesses a separate cache line, that's **32 transactions** — 32× slower.\n\n"
            "**Rules for coalesced access:**\n"
            "1. Thread `i` in the warp should access element `base + i` (or a scalar multiple)\n"
            "2. Use Structure-of-Arrays (SoA) rather than Array-of-Structures (AoS)\n"
            "3. Align arrays to 128-byte boundaries (cudaMalloc always does this)\n\n"
            "**Checking coalescing:** In Nsight Compute, look at `l2_global_load_bytes` vs "
            "`dram_read_bytes`. A ratio > 2× indicates poor coalescing."
        ),
        "specs": [
            ("Cache line size", "128 bytes"),
            ("Warp size", "32 threads"),
            ("Ideal: 32 × 4-byte reads", "= 1 cache line = 1 transaction"),
            ("Worst case: 32 random addresses", "= 32 transactions (32× slower)"),
        ],
        "example": (
            "// BAD: AoS — each field access strides by struct size\n"
            "struct Particle { float x, y, z, w; };\n"
            "Particle *p; // thread i reads p[i].x → stride = 16 bytes → 4 transactions per warp\n\n"
            "// GOOD: SoA — coalesced reads\n"
            "float *px, *py, *pz, *pw;\n"
            "// thread i reads px[i] → stride = 4 bytes → 1 transaction per warp"
        ),
        "tags": ["coalescing", "global memory", "bandwidth", "cache line", "SoA", "AoS", "transaction"],
    },

    {
        "id": "mem-registers",
        "category": "memory",
        "title": "Registers & Register Spilling",
        "summary": "Registers are the fastest memory (~1 cycle) but finite — 65,536 per SM, shared among all resident threads. Too many registers per thread → fewer threads → lower occupancy.",
        "detail": (
            "Each SM has 65,536 × 32-bit registers. If your kernel uses R registers per thread "
            "and has T threads per block:\n"
            "- Max blocks per SM ≤ 65536 / (R × T)\n\n"
            "**Register spilling:** when the compiler can't fit all variables in registers, "
            "it spills them to local memory (which maps to L1/global — slow). "
            "Check for spills: `nvcc --ptxas-options=-v`\n\n"
            "**Controlling register usage:**\n"
            "- `__launch_bounds__(maxThreadsPerBlock, minBlocksPerSM)` — hints to compiler\n"
            "- `#pragma unroll N` — controls loop unrolling (increases register pressure)\n"
            "- Reduce variable lifetimes by restructuring code\n\n"
            "On the 4090, 32 registers/thread allows max 1,536 threads/SM (full occupancy). "
            "64 registers/thread halves occupancy to 768 threads/SM."
        ),
        "specs": [
            ("Registers per SM", "65,536 × 32-bit"),
            ("Max registers per thread", "255"),
            ("At 32 regs/thread, 256 threads/block", "→ 8 blocks/SM → 100% occupancy"),
            ("At 64 regs/thread", "→ max 4 blocks/SM → 50% occupancy"),
        ],
        "example": (
            "# Check register usage and spills\n"
            "# nvcc -arch=sm_89 --ptxas-options=-v mykernel.cu\n"
            "# Output: 'ptxas info: Used 32 registers, 0 bytes smem, 0 bytes lmem'\n"
            "# 'lmem' > 0 means register spilling — bad!\n\n"
            "// Limit registers via launch bounds\n"
            "__global__ __launch_bounds__(256, 4) void myKernel(...) { ... }"
        ),
        "tags": ["registers", "register spilling", "occupancy", "launch_bounds", "local memory", "ptxas"],
    },

    # ─────────────────────────────────────────────────────────────────────
    # CATEGORY: execution — Thread execution model
    # ─────────────────────────────────────────────────────────────────────

    {
        "id": "exec-thread-hierarchy",
        "category": "execution",
        "title": "Thread Hierarchy: Thread → Warp → Block → Grid",
        "summary": "CUDA organizes threads in a 4-level hierarchy. The warp (32 threads) is the fundamental execution unit — understanding it is the key to writing fast kernels.",
        "detail": (
            "**Thread:** The smallest unit. Has its own registers and local memory. "
            "Identified by `threadIdx.{x,y,z}` within its block.\n\n"
            "**Warp:** 32 consecutive threads that execute **in lockstep** on the same SM. "
            "All threads in a warp execute the same instruction simultaneously (SIMT). "
            "This is hardware — you cannot change the warp size.\n\n"
            "**Thread Block:** 1–1024 threads grouped together. Scheduled to a single SM. "
            "All threads in a block can:\n"
            "- Use `__syncthreads()` to synchronize\n"
            "- Share `__shared__` memory\n"
            "Identified by `blockIdx.{x,y,z}` and `blockDim.{x,y,z}`.\n\n"
            "**Grid:** Collection of blocks. Blocks execute independently (no inter-block sync in basic CUDA). "
            "Identified by `gridDim.{x,y,z}`.\n\n"
            "**RTX 4090 limits:**\n"
            "- Max 1,024 threads per block\n"
            "- Max 2,147,483,647 blocks per grid dimension\n"
            "- 128 SMs each running up to 48 warps = 6,144 concurrent warps = 196,608 threads"
        ),
        "specs": [
            ("Warp size", "32 threads (hardware constant)"),
            ("Max threads per block", "1,024"),
            ("Max warps per SM", "48"),
            ("Max concurrent threads (4090)", "128 SMs × 1,536 = 196,608"),
            ("Typical block size", "128 or 256 (multiples of 32)"),
        ],
        "example": (
            "// 1D kernel launch — process N elements\n"
            "int threadsPerBlock = 256;\n"
            "int blocksPerGrid = (N + threadsPerBlock - 1) / threadsPerBlock;\n"
            "myKernel<<<blocksPerGrid, threadsPerBlock>>>(d_data, N);\n\n"
            "__global__ void myKernel(float *data, int N) {\n"
            "    int idx = blockIdx.x * blockDim.x + threadIdx.x;\n"
            "    if (idx < N) data[idx] = sqrtf(data[idx]);\n"
            "}"
        ),
        "tags": ["thread", "warp", "block", "grid", "threadIdx", "blockIdx", "SIMT", "hierarchy"],
    },

    {
        "id": "exec-occupancy",
        "category": "execution",
        "title": "Occupancy — Hiding Memory Latency",
        "summary": "Occupancy = active warps / max warps per SM. High occupancy lets the SM hide memory latency by switching to a ready warp while another waits for data. Aim for ≥50%.",
        "detail": (
            "When a warp issues a global memory load (~600 cycle latency), the SM **warp scheduler** "
            "immediately switches to another ready warp. With enough warps resident, the SM stays busy. "
            "This is **latency hiding** — the core reason GPU throughput is so high despite high latency.\n\n"
            "**Occupancy is limited by whichever resource runs out first:**\n"
            "1. Registers: 65,536/SM ÷ (regs/thread × threads/block)\n"
            "2. Shared memory: 100 KB/SM ÷ bytes/block\n"
            "3. Block count: max 32 blocks/SM\n"
            "4. Thread count: max 1,536 threads/SM\n\n"
            "**Calculating occupancy:**\n"
            "- Use `cuda-occupancy-calculator.xlsx` (NVIDIA) or `cudaOccupancyMaxActiveBlocksPerMultiprocessor()`\n"
            "- Nsight Compute shows 'Theoretical Occupancy' and the limiting factor\n\n"
            "**Important nuance:** Higher occupancy does not always mean better performance. "
            "If your kernel is compute-bound, additional warps just compete for the same FUs. "
            "Focus on compute efficiency first, occupancy second."
        ),
        "specs": [
            ("Max warps per SM (4090)", "48"),
            ("50% occupancy = ", "24 warps/SM = 768 threads/SM"),
            ("100% occupancy = ", "48 warps/SM = 1,536 threads/SM"),
            ("Rule of thumb", "Aim for ≥50% — diminishing returns above 75%"),
        ],
        "example": (
            "// Runtime occupancy check (CUDA C++)\n"
            "#include <cuda_runtime.h>\n"
            "int blockSize, gridSize, minGridSize;\n"
            "cudaOccupancyMaxPotentialBlockSize(\n"
            "    &minGridSize, &blockSize, myKernel, 0, 0);\n"
            "printf('Optimal block size: %d\\n', blockSize);\n\n"
            "// Python equivalent\n"
            "import torch\n"
            "# Check with Nsight Compute: ncu --target-processes all python script.py"
        ),
        "tags": ["occupancy", "latency hiding", "warp scheduler", "warps", "performance", "registers", "shared memory"],
    },

    {
        "id": "exec-warp-divergence",
        "category": "execution",
        "title": "Warp Divergence",
        "summary": "When threads in the same warp take different branches (if/else), the warp executes both paths serially with masking — halving or worse throughput. Avoid conditional logic that splits warps.",
        "detail": (
            "Because all 32 threads in a warp execute the same instruction, a branch that splits the warp "
            "forces the hardware to execute **both paths sequentially** — threads inactive on each path "
            "are masked out (their results discarded).\n\n"
            "**Worst case:** 32 threads each take a unique branch → 32× slowdown\n"
            "**No divergence:** All threads take the same branch → no penalty\n\n"
            "**Ada improvement:** Ada Lovelace adds 'Warp Specialization' for some patterns — "
            "the compiler can schedule different warps for each branch path, reducing divergence cost.\n\n"
            "**How to avoid:**\n"
            "1. Ensure threads 0–31 (a warp) always take the same branch\n"
            "2. Restructure so divergent branches are in separate kernel launches\n"
            "3. Use predicated execution: `data[i] = (cond) ? a : b;` instead of if/else\n"
            "4. Sort input data so similar-behaving threads are grouped"
        ),
        "specs": [
            ("Warp size", "32 threads (all execute same instruction)"),
            ("Divergent branches", "Both paths execute serially"),
            ("Max divergence penalty", "32× for 32 unique paths"),
            ("Ada mitigation", "Warp Specialization (compiler-managed)"),
        ],
        "example": (
            "// BAD — diverges if threadIdx.x determines branch (50% each)\n"
            "if (threadIdx.x % 2 == 0) { result = a * b; }  // threads 0,2,4...\n"
            "else { result = a + b; }                         // threads 1,3,5...\n\n"
            "// BETTER — no divergence if all threads in warp have same x/32 group\n"
            "if (blockIdx.x % 2 == 0) { result = a * b; }  // whole blocks diverge (OK)\n"
            "else { result = a + b; }\n\n"
            "// BEST — avoid branch entirely with ternary\n"
            "result = (threadIdx.x % 2 == 0) ? a * b : a + b;  // predicated, no branch"
        ),
        "tags": ["warp divergence", "branch", "SIMT", "if/else", "predication", "performance"],
    },

    {
        "id": "exec-sync",
        "category": "execution",
        "title": "Synchronization Primitives",
        "summary": "__syncthreads() synchronizes all threads in a block. atomicAdd/CAS handle inter-thread data races. Cooperative Groups (CUDA 9+) enable flexible warp/grid-level sync.",
        "detail": (
            "**__syncthreads():** Block-level barrier. All threads in the block must reach this call "
            "before any proceed. Used after writing to shared memory. Cost: ~30 cycles.\n"
            "⚠️ Never call __syncthreads() conditionally — all threads must hit it or the kernel deadlocks.\n\n"
            "**Atomics:** Thread-safe read-modify-write on global or shared memory.\n"
            "- `atomicAdd(addr, val)` — adds val, returns old value\n"
            "- `atomicCAS(addr, compare, val)` — compare-and-swap primitive\n"
            "- `atomicMax/Min/Or/And/Xor` — other variants\n"
            "Ada has improved atomic throughput: 2× vs Ampere for scattered atomics.\n\n"
            "**Warp-level:** `__syncwarp()` syncs within a warp (cheap). "
            "`__ballot_sync()`, `__shfl_sync()` enable warp-level reductions without shared memory.\n\n"
            "**Cooperative Groups (CUDA 9+):** Generalized sync for subsets of threads. "
            "Enables grid-level sync with `grid.sync()` (requires cooperative launch)."
        ),
        "specs": [
            ("__syncthreads()", "Block barrier, ~30 cycles, all threads must reach it"),
            ("atomicAdd FP32 (shared mem)", "~1 cycle on Ada (hardware native)"),
            ("atomicAdd FP32 (global mem)", "~100 cycles (L2 arbitration)"),
            ("__syncwarp()", "Warp barrier, ~5 cycles"),
            ("__shfl_sync()", "Warp-level broadcast/shuffle, ~5 cycles"),
        ],
        "example": (
            "// Warp reduction using __shfl_sync (no shared memory needed)\n"
            "__device__ float warpReduceSum(float val) {\n"
            "    for (int offset = 16; offset > 0; offset /= 2)\n"
            "        val += __shfl_down_sync(0xffffffff, val, offset);\n"
            "    return val;  // lane 0 holds the sum\n"
            "}\n\n"
            "// Block reduction (combine warp reduces)\n"
            "__shared__ float partial[32];  // one slot per warp\n"
            "float sum = warpReduceSum(val);\n"
            "if (threadIdx.x % 32 == 0) partial[threadIdx.x / 32] = sum;\n"
            "__syncthreads();\n"
            "if (threadIdx.x < 32) sum = warpReduceSum(partial[threadIdx.x]);"
        ),
        "tags": ["syncthreads", "atomics", "atomicAdd", "syncwarp", "shfl_sync", "cooperative groups", "warp reduction"],
    },

    # ─────────────────────────────────────────────────────────────────────
    # CATEGORY: performance — Optimization techniques
    # ─────────────────────────────────────────────────────────────────────

    {
        "id": "perf-roofline",
        "category": "performance",
        "title": "Roofline Model — Are You Memory or Compute Bound?",
        "summary": "The roofline model tells you whether your kernel is limited by compute throughput or memory bandwidth. This determines where to optimize.",
        "detail": (
            "**Arithmetic Intensity (AI)** = FLOPs performed ÷ bytes transferred from/to memory.\n\n"
            "Your RTX 4090 has:\n"
            "- Peak FP32: 82.6 TFLOPS\n"
            "- Memory bandwidth: 1,008 GB/s\n"
            "- **Ridge point** = 82,600 / 1,008 = **~82 FLOP/byte**\n\n"
            "If your kernel's AI < 82: **memory-bound** → optimize data layout, coalescing, shared memory\n"
            "If your kernel's AI > 82: **compute-bound** → use Tensor Cores, minimize FP ops\n\n"
            "**Typical kernels:**\n"
            "- GEMM (matrix multiply): AI ≈ N/2 → compute-bound for large N (uses Tensor Cores)\n"
            "- Vector add: AI = 1/4 → extremely memory-bound\n"
            "- Softmax / LayerNorm: AI ≈ 10–50 → memory-bound\n"
            "- Attention (quadratic in seq len): AI = O(d_model) → compute-bound for long sequences\n\n"
            "Nsight Compute generates roofline plots automatically."
        ),
        "specs": [
            ("RTX 4090 FP32 peak", "82.6 TFLOPS"),
            ("RTX 4090 BW peak", "1,008 GB/s"),
            ("Ridge point (FP32)", "~82 FLOP/byte"),
            ("Vector add AI", "0.25 FLOP/byte — memory-bound"),
            ("Dense GEMM AI (N=4096)", "~2048 FLOP/byte — compute-bound"),
        ],
        "example": (
            "# Estimate arithmetic intensity of a kernel\n"
            "# FLOPs: count multiply-add operations\n"
            "# Bytes: count unique global memory accesses (not total, unique)\n\n"
            "# Vector add y = a*x + b: N FMAs = 2N FLOPs, loads 3N floats = 12N bytes\n"
            "# AI = 2N / 12N = 0.167 FLOP/byte — extremely memory bound\n\n"
            "# GEMM C = A@B (N×N matrices): 2N^3 FLOPs, loads 3N^2 floats\n"
            "# AI = 2N^3 / (12N^2) = N/6 — compute bound for N > 500"
        ),
        "tags": ["roofline", "arithmetic intensity", "memory bound", "compute bound", "bandwidth", "tflops", "optimization"],
    },

    {
        "id": "perf-nsight",
        "category": "performance",
        "title": "Profiling with Nsight Compute & Nsight Systems",
        "summary": "Nsight Compute profiles individual kernels (SM utilization, memory throughput, roofline). Nsight Systems profiles the full timeline (CPU/GPU overlap, bottlenecks).",
        "detail": (
            "**Nsight Compute (ncu):** Kernel-level profiler. Tells you exactly what's limiting each kernel.\n"
            "- SM throughput vs peak\n"
            "- L1/L2/DRAM bandwidth utilization\n"
            "- Occupancy and its limiting factor\n"
            "- Warp stall reasons (memory wait, sync, compute)\n"
            "- Roofline plot\n\n"
            "**Nsight Systems (nsys):** Timeline profiler. Shows:\n"
            "- Kernel launch overhead\n"
            "- cudaMemcpy duration\n"
            "- CPU/GPU overlap\n"
            "- CUDA stream utilization\n\n"
            "**Quick commands:**\n"
            "```\n"
            "nsys profile python script.py          # full timeline\n"
            "ncu python script.py                   # all kernels (slow)\n"
            "ncu --kernel-name myKernel python ...  # specific kernel\n"
            "ncu --set full python ...              # full metrics\n"
            "```\n\n"
            "**PyTorch integration:**\n"
            "```python\n"
            "with torch.profiler.profile(activities=[...]) as prof:\n"
            "    model(input)\n"
            "print(prof.key_averages())\n"
            "```"
        ),
        "specs": [
            ("ncu", "Kernel profiler — hardware counters"),
            ("nsys", "Timeline profiler — system view"),
            ("nvtx", "Annotation API — mark regions in your code"),
            ("torch.profiler", "PyTorch wrapper around nsys/ncu"),
        ],
        "example": (
            "# Annotate your code with NVTX for nsys\n"
            "import nvtx\n\n"
            "@nvtx.annotate('forward_pass', color='blue')\n"
            "def forward(model, x):\n"
            "    return model(x)\n\n"
            "# Or use torch.cuda.nvtx directly\n"
            "torch.cuda.nvtx.range_push('attention')\n"
            "out = attention(q, k, v)\n"
            "torch.cuda.nvtx.range_pop()"
        ),
        "tags": ["nsight", "ncu", "nsys", "profiling", "performance", "nvtx", "torch profiler", "bottleneck"],
    },

    {
        "id": "perf-streams",
        "category": "performance",
        "title": "CUDA Streams — Overlapping Computation and Transfer",
        "summary": "CUDA streams let you overlap kernel execution with data transfers (H↔D). On RTX 4090 with PCIe 4.0, you can hide up to 32 GB/s copy bandwidth behind computation.",
        "detail": (
            "By default, all CUDA operations go into stream 0 and execute sequentially. "
            "With multiple streams, you can overlap:\n"
            "1. Kernel A on stream 1 **while** copying data B on stream 2\n"
            "2. Two independent kernels on separate streams (if SM resources allow)\n\n"
            "**Double buffering pattern:**\n"
            "While GPU processes batch N, CPU transfers batch N+1. "
            "This eliminates transfer latency from the critical path.\n\n"
            "**Requirements for overlap:**\n"
            "- Use `cudaMemcpyAsync` with pinned (page-locked) host memory\n"
            "- Independent streams with no dependencies\n"
            "- The GPU must have idle copy engines (CE) while running kernels\n\n"
            "**RTX 4090:** Has 2 copy engines (1 H→D, 1 D→H), so you can overlap:\n"
            "- 1 H→D transfer + 1 kernel + 1 D→H transfer simultaneously"
        ),
        "specs": [
            ("PCIe 4.0 x16 bandwidth", "~32 GB/s H→D, ~32 GB/s D→H"),
            ("Copy engines on 4090", "2 (bidirectional concurrent)"),
            ("cudaMemcpyAsync", "Non-blocking — requires pinned memory"),
            ("cudaMallocHost", "Allocates pinned host memory"),
        ],
        "example": (
            "cudaStream_t stream1, stream2;\n"
            "cudaStreamCreate(&stream1);\n"
            "cudaStreamCreate(&stream2);\n\n"
            "// Double buffering\n"
            "for (int i = 0; i < N; i += CHUNK) {\n"
            "    // Stream 1: copy this chunk\n"
            "    cudaMemcpyAsync(d_buf1, h_data+i, CHUNK*sizeof(float),\n"
            "                   cudaMemcpyHostToDevice, stream1);\n"
            "    // Stream 2: process previous chunk concurrently\n"
            "    if (i > 0) processKernel<<<grid, block, 0, stream2>>>(d_buf2);\n"
            "    cudaStreamSynchronize(stream2);\n"
            "    std::swap(d_buf1, d_buf2);\n"
            "}"
        ),
        "tags": ["streams", "overlap", "pcie", "memcpy", "async", "double buffering", "pinned memory", "cudaMemcpyAsync"],
    },

    # ─────────────────────────────────────────────────────────────────────
    # CATEGORY: gemma4 — Model architecture
    # ─────────────────────────────────────────────────────────────────────

    {
        "id": "gemma4-moe",
        "category": "gemma4",
        "title": "Mixture of Experts (MoE) — Why Gemma4 Fits in 24 GB",
        "summary": "Gemma4 26B is a Sparse MoE model. Despite 26B total parameters, only ~3.8B are active per token. This is why it runs in 24 GB VRAM at Q4 quantization.",
        "detail": (
            "A **Sparse Mixture of Experts** model has a large pool of 'expert' FFN layers, "
            "but only activates a small subset per token via a learned 'router' network.\n\n"
            "**Gemma4 26B architecture:**\n"
            "- Total parameters: ~26 billion\n"
            "- Active parameters per token: ~3.8 billion (just 2 of the many experts activated)\n"
            "- VRAM needed: all 26B parameters must reside in VRAM (inactive experts still loaded)\n\n"
            "**Why this matters for you:**\n"
            "- Inference speed scales with **active** params → similar speed to a 4B dense model\n"
            "- Memory scales with **total** params → needs 24 GB VRAM at Q4_K_M\n"
            "- At 256K context + Q4: VRAM use = ~12 GB (model) + ~20 GB (KV cache) ≈ 32 GB (OOM!)\n"
            "- Practical max context on 4090: ~80K tokens\n\n"
            "**MoE routing:** Each token is processed by a tiny router that selects 2 experts "
            "from a pool of ~8 per layer. Different tokens may activate different experts, "
            "enabling specialization across a much larger parameter space than compute cost implies."
        ),
        "specs": [
            ("Total parameters", "~26 billion"),
            ("Active parameters per token", "~3.8 billion"),
            ("VRAM at Q4_K_M", "~13 GB (model weights)"),
            ("VRAM per 1K context tokens", "~0.2 GB (KV cache at BF16)"),
            ("Experts per layer", "~8 (top-2 selected per token)"),
            ("Practical max context on 4090", "~80K tokens"),
        ],
        "example": None,
        "tags": ["MoE", "mixture of experts", "gemma4", "parameters", "VRAM", "quantization", "active parameters", "router"],
    },

    {
        "id": "gemma4-attention",
        "category": "gemma4",
        "title": "Grouped-Query Attention (GQA) & Context Scaling",
        "summary": "Gemma4 uses GQA to reduce KV cache size. Each group of query heads shares one KV head — reducing KV cache VRAM by up to 8× vs standard multi-head attention.",
        "detail": (
            "**Standard Multi-Head Attention (MHA):** H query heads, H key heads, H value heads.\n"
            "**Grouped-Query Attention (GQA):** H query heads, H/G key heads, H/G value heads. "
            "G query heads share one KV head.\n\n"
            "**Why it matters:** KV cache size = 2 × layers × seq_len × d_head × n_kv_heads × bytes\n\n"
            "For Gemma4 at 256K tokens, BF16:\n"
            "- MHA (H=32 heads): 2 × 32 × 256K × 128 × 32 × 2 bytes ≈ **68 GB** (doesn't fit!)\n"
            "- GQA (H/G=4 KV heads): 4× smaller → **17 GB** (marginal on 4090)\n\n"
            "**Flash Attention (used by Ollama):** Fused kernel that computes attention without "
            "materializing the full N×N attention matrix. Reduces memory from O(N²) to O(N). "
            "This is why you can run 80K context on a single 4090 at all.\n\n"
            "**Practical guidance:** For chat tasks, use num_ctx=8192–16384. "
            "For long document analysis, 32768–65536 is achievable. "
            "256K context requires ≥2× A100 80GB GPUs."
        ),
        "specs": [
            ("num_ctx=8192", "~2 GB KV cache, fast"),
            ("num_ctx=32768", "~8 GB KV cache, moderate"),
            ("num_ctx=131072", "~32 GB KV cache, exceeds 4090"),
            ("Flash Attention", "O(N) memory vs O(N²) naive"),
        ],
        "example": None,
        "tags": ["GQA", "grouped query attention", "KV cache", "flash attention", "context window", "num_ctx", "VRAM"],
    },

    {
        "id": "gemma4-tokenization",
        "category": "gemma4",
        "title": "Tokenization & Context Budget",
        "summary": "Gemma4 uses SentencePiece tokenization. 1 token ≈ 0.75 words in English. Your 8192 context budget ≈ 6,000 words ≈ a 20-page document.",
        "detail": (
            "**Tokens vs words:** English text: ~1.3 tokens/word. Code: ~2–4 tokens/word (more symbols).\n\n"
            "**Context budget at num_ctx=8192:**\n"
            "- System prompt: ~200 tokens\n"
            "- Each conversation turn: ~100–500 tokens\n"
            "- Available for user query + response: ~7,500 tokens\n\n"
            "**Practical limits by content type:**\n"
            "| Content | 8K ctx budget |\n"
            "|---------|---------------|\n"
            "| Chat conversation | ~60 back-and-forth turns |\n"
            "| Python script analysis | ~500 lines of code |\n"
            "| Short story | ~5,000 words |\n"
            "| Annual report (10-K) | ~10% of a typical filing |\n\n"
            "**Truncation strategy:** When context is full, Ollama removes the oldest messages "
            "(sliding window). Critical info (from early in the chat) may be dropped. "
            "For long tasks, summarize periodically or increase num_ctx.\n\n"
            "**Generation budget:** num_predict=2048 means responses up to ~1,500 words. "
            "For longer output, increase num_predict (at the cost of slower worst-case latency)."
        ),
        "specs": [
            ("Tokens per English word", "~1.3"),
            ("8K context ≈", "~6,000 words"),
            ("32K context ≈", "~24,000 words (~2 research papers)"),
            ("Tokenizer", "SentencePiece (BPE variant)"),
        ],
        "example": (
            "# Count tokens before sending a long prompt\n"
            "# pip install sentencepiece tiktoken\n"
            "import tiktoken  # approximate for Gemma\n"
            "enc = tiktoken.get_encoding('cl100k_base')  # GPT-4 tokenizer, similar count\n"
            "tokens = enc.encode(text)\n"
            "print(f'{len(tokens)} tokens ({len(tokens)/1.3:.0f} words equiv)')"
        ),
        "tags": ["tokenization", "context window", "tokens", "num_ctx", "sentencepiece", "budget", "num_predict"],
    },

    {
        "id": "gemma4-sampling",
        "category": "gemma4",
        "title": "Sampling Parameters — How They Actually Work",
        "summary": "Temperature, top-p, top-k, and min-p control how Gemma4 samples the next token from the probability distribution over its 256K vocabulary.",
        "detail": (
            "After Gemma4 computes logits for the next token, a **sampling pipeline** selects one:\n\n"
            "1. **Temperature** divides all logits: `logits / T`. Low T → sharper distribution → "
            "model picks its most confident token. High T → flatter → more random.\n\n"
            "2. **Top-K** keeps only the top K tokens by probability, zeroes the rest.\n\n"
            "3. **Top-P (nucleus)** keeps the smallest set of tokens whose cumulative probability ≥ P, "
            "zeroes the rest. Adapts to the distribution width.\n\n"
            "4. **Min-P** keeps tokens with probability ≥ min_p × P(top). "
            "Elegant: automatically removes the 'long tail' of very improbable tokens.\n\n"
            "5. **Repeat Penalty** multiplies logits of recently seen tokens by 1/penalty "
            "(< 1 if penalty > 1), discouraging repetition.\n\n"
            "**Typical flows:**\n"
            "- Factual QA: temperature 0.1–0.3, top_p 0.9 (near-deterministic)\n"
            "- Creative writing: temperature 0.8–1.2, top_p 0.95\n"
            "- Code generation: temperature 0.2–0.4, top_p 0.95\n"
            "- Balanced chat (Mithrandir default): temperature 0.7, top_p 0.9, top_k 40"
        ),
        "specs": [
            ("Vocabulary size", "~256,000 tokens"),
            ("Default temperature", "0.7"),
            ("Default top-p", "0.9"),
            ("Default top-k", "40"),
            ("Default repeat_penalty", "1.1"),
            ("Greedy (T=0)", "Always picks max probability token — deterministic"),
        ],
        "example": None,
        "tags": ["temperature", "top_p", "top_k", "min_p", "repeat_penalty", "sampling", "logits", "vocabulary"],
    },

    # ─────────────────────────────────────────────────────────────────────
    # CATEGORY: inference — CUDA meets LLM inference
    # ─────────────────────────────────────────────────────────────────────

    {
        "id": "inf-quantization",
        "category": "inference",
        "title": "Quantization — Fitting 26B Parameters in 24 GB",
        "summary": "Quantization reduces weight precision from FP16 (2 bytes) to INT4 (0.5 bytes). Q4_K_M runs Gemma4 26B in ~13 GB at ~65 tok/s. Higher quality costs more VRAM.",
        "detail": (
            "**GGUF quantization formats (Ollama uses llama.cpp GGUF):**\n\n"
            "| Format | Bits/weight | VRAM (26B) | Speed (4090) | Quality |\n"
            "|--------|-------------|-----------|--------------|----------|\n"
            "| FP16 | 16 | ~52 GB | Doesn't fit | Reference |\n"
            "| Q8_0 | 8 | ~27 GB | Doesn't fit (barely) | Very high |\n"
            "| Q6_K | 6 | ~20 GB | ~40 tok/s | High |\n"
            "| Q5_K_M | 5 | ~17 GB | ~55 tok/s | Good |\n"
            "| Q4_K_M | 4 | ~13 GB | ~65 tok/s | Default |\n"
            "| Q3_K_M | 3 | ~10 GB | ~80 tok/s | Noticeable quality loss |\n\n"
            "**K-quantization (K_M, K_L, K_S):** Groups weights into blocks of 32 and uses "
            "a shared scale factor. The 'M' variant mixes precision — some layers use higher bits "
            "for critical weights (attention, embeddings).\n\n"
            "**Check current model in Ollama:**\n"
            "`ollama show gemma4:27b --modelinfo`"
        ),
        "specs": [
            ("Q4_K_M (default)", "~13 GB VRAM, ~65 tok/s on 4090"),
            ("Q5_K_M", "~17 GB VRAM, ~55 tok/s — recommended"),
            ("Q6_K", "~20 GB VRAM, ~40 tok/s — high quality"),
            ("BF16", "~52 GB VRAM — requires multi-GPU"),
        ],
        "example": (
            "# Check active model and quantization in Ollama\n"
            "ollama list\n"
            "ollama show gemma4:27b\n\n"
            "# Pull a specific quantization\n"
            "ollama pull gemma4:27b-instruct-q5_K_M\n\n"
            "# Monitor VRAM usage while running\n"
            "nvidia-smi dmon -s mu -d 1  # memory util every 1s"
        ),
        "tags": ["quantization", "GGUF", "Q4", "Q8", "VRAM", "int4", "fp16", "llama.cpp", "bits per weight"],
    },

    {
        "id": "inf-kvcache",
        "category": "inference",
        "title": "KV Cache — The Bottleneck for Long Conversations",
        "summary": "The KV cache stores key and value tensors for all past tokens so they don't need recomputation. It grows linearly with context length and is the primary VRAM consumer for long chats.",
        "detail": (
            "During autoregressive generation, the model computes attention over all previous tokens. "
            "The KV cache stores K and V tensors for every past token so they can be reused.\n\n"
            "**KV cache size formula:**\n"
            "`size = 2 × n_layers × n_kv_heads × d_head × seq_len × dtype_bytes`\n\n"
            "For Gemma4 26B at BF16 (2 bytes), GQA with 4 KV heads:\n"
            "- 1K context: ~0.25 GB\n"
            "- 8K context: ~2 GB\n"
            "- 32K context: ~8 GB\n"
            "- 128K context: ~32 GB (exceeds 4090!)\n\n"
            "**Prefill vs decode phase:**\n"
            "- **Prefill:** Process the entire prompt at once (batched, Tensor Core-heavy, fast)\n"
            "- **Decode:** Generate one token at a time (sequential, memory-bandwidth-bound, slow)\n\n"
            "This is why long prompts generate the first token slowly (prefill) but stream quickly thereafter.\n\n"
            "**Optimize:** Keep num_ctx matched to your actual needs. "
            "A 128K context window initialized but rarely used wastes VRAM that could serve more requests."
        ),
        "specs": [
            ("Per 1K tokens (Gemma4 Q4)", "~0.25 GB"),
            ("At 8K ctx", "~2 GB KV cache"),
            ("At 32K ctx", "~8 GB KV cache"),
            ("Available after model load (13 GB model)", "~11 GB for KV cache"),
            ("Max context on 4090", "~44K tokens (11 GB ÷ 0.25 GB/K)"),
        ],
        "example": None,
        "tags": ["KV cache", "context", "VRAM", "prefill", "decode", "attention", "memory", "sequence length"],
    },

    {
        "id": "inf-python-cuda",
        "category": "inference",
        "title": "Writing CUDA Kernels from Python — PyTorch, CuPy, and Numba",
        "summary": "You can write and run CUDA kernels directly from Python without a C++ build step. PyTorch custom ops, CuPy RawKernel, and numba.cuda all work on your RTX 4090.",
        "detail": (
            "**Option 1: CuPy RawKernel** — write raw CUDA C in a Python string, compile JIT:\n"
            "```python\n"
            "import cupy as cp\n"
            "kernel = cp.RawKernel(r'''\n"
            "    extern \"C\" __global__ void add(float *a, float *b, float *c, int n) {\n"
            "        int i = blockIdx.x * blockDim.x + threadIdx.x;\n"
            "        if (i < n) c[i] = a[i] + b[i];\n"
            "    }\n"
            "''', 'add')\n"
            "a, b = cp.ones(1024), cp.ones(1024)\n"
            "c = cp.zeros(1024)\n"
            "kernel((32,), (32,), (a, b, c, 1024))\n"
            "```\n\n"
            "**Option 2: Numba CUDA JIT** — write Python, compiles to PTX:\n"
            "```python\n"
            "from numba import cuda\n"
            "@cuda.jit\n"
            "def add_kernel(a, b, c):\n"
            "    i = cuda.grid(1)\n"
            "    if i < a.size:\n"
            "        c[i] = a[i] + b[i]\n"
            "```\n\n"
            "**Option 3: PyTorch Custom CUDA Extension** — for production kernels:\n"
            "```python\n"
            "from torch.utils.cpp_extension import load_inline\n"
            "```\n\n"
            "**Option 4: Triton** — Google-backed, write GPU kernels in Python, auto-tuned:\n"
            "`pip install triton` — already used by PyTorch 2.x for flash attention, etc."
        ),
        "specs": [
            ("CuPy", "Raw CUDA C in Python strings, JIT compile"),
            ("numba.cuda", "Python-like GPU kernels, JIT to PTX"),
            ("Triton", "Block-level GPU programming, auto-tuned"),
            ("torch.utils.cpp_extension", "Full CUDA C++ extensions for PyTorch"),
        ],
        "example": (
            "# Quickest way to verify CUDA works from Python\n"
            "import torch\n"
            "x = torch.randn(1000, 1000, device='cuda')\n"
            "y = torch.matmul(x, x.T)  # runs on Tensor Cores\n"
            "print(f'Device: {y.device}, dtype: {y.dtype}')\n\n"
            "# CuPy: NumPy-compatible GPU arrays\n"
            "import cupy as cp\n"
            "x = cp.random.randn(1000, 1000, dtype=cp.float32)\n"
            "print(cp.cuda.runtime.getDeviceProperties(0)['name'])"
        ),
        "tags": ["python", "cupy", "numba", "triton", "custom kernels", "RawKernel", "cuda.jit", "pytorch extension"],
    },

    {
        "id": "inf-flash-attention",
        "category": "inference",
        "title": "Flash Attention — How Ollama Fits Long Contexts",
        "summary": "Flash Attention is a memory-efficient attention kernel that avoids materializing the full N×N attention matrix. It's what makes 32K+ context possible on a single GPU.",
        "detail": (
            "**Standard attention complexity:**\n"
            "- Time: O(N²d) — quadratic in sequence length\n"
            "- Memory: O(N²) — must store full NxN attention matrix\n\n"
            "**Flash Attention (Dao et al., 2022):**\n"
            "- Computes attention in tiles that fit in SRAM\n"
            "- Never materializes the full N×N matrix\n"
            "- Memory: O(N) — linear in sequence length!\n"
            "- Speed: 2–4× faster than standard attention (memory-bound elimination)\n\n"
            "**Flash Attention 2 improvements:**\n"
            "- Better work partitioning across warps\n"
            "- Parallelism over sequence length (not just batch/heads)\n"
            "- On H100: 2–9× speedup vs standard; RTX 4090: 2–4× speedup\n\n"
            "**Flash Attention 3 (Ada/Hopper):**\n"
            "- Uses FP8 Tensor Cores and async memory pipelines\n"
            "- Only available on Hopper (H100) — not on RTX 4090\n\n"
            "Ollama automatically uses Flash Attention when available. "
            "You can verify: `OLLAMA_FLASH_ATTENTION=1 ollama serve`"
        ),
        "specs": [
            ("Standard attention memory", "O(N²) — 32K context = 4GB just for attention"),
            ("Flash Attention memory", "O(N) — 32K context = 128MB"),
            ("Speedup on 4090", "~2–4× vs naive"),
            ("Required for 32K+ context", "Yes — otherwise OOM"),
        ],
        "example": (
            "# Check if Flash Attention is enabled in Ollama\n"
            "$env:OLLAMA_FLASH_ATTENTION = '1'\n"
            "ollama serve  # Windows PowerShell\n\n"
            "# In PyTorch 2.x, Flash Attention 2 is the default backend:\n"
            "import torch\n"
            "with torch.backends.cuda.sdp_kernel(\n"
            "    enable_flash=True, enable_math=False, enable_mem_efficient=False\n"
            "):\n"
            "    out = torch.nn.functional.scaled_dot_product_attention(q, k, v)"
        ),
        "tags": ["flash attention", "attention", "memory", "context", "sequence length", "SRAM", "tiling", "Ollama"],
    },
]


# ─────────────────────────────────────────────────────────────────────────
# Search function (used by /api/docs/search and the agent tool)
# ─────────────────────────────────────────────────────────────────────────

def search_docs(query: str, max_results: int = 5) -> str:
    """
    Keyword search over the docs index.
    Returns a plain-text summary of matching entries, suitable for agent injection.
    """
    q = query.lower()
    scores: list[tuple[int, dict]] = []

    for doc in DOCS:
        score = 0
        if q in doc["title"].lower():        score += 10
        if q in doc["summary"].lower():      score += 5
        if q in (doc["detail"] or "").lower(): score += 3
        for tag in doc.get("tags", []):
            if q in tag.lower():             score += 4
        for kv in doc.get("specs", []):
            if q in kv[0].lower() or q in kv[1].lower(): score += 2
        if score > 0:
            scores.append((score, doc))

    scores.sort(key=lambda x: -x[0])
    top = scores[:max_results]

    if not top:
        return f"No docs found matching '{query}'. Try: cuda, memory, warp, occupancy, gemma4, quantization, attention."

    lines = [f"Documentation results for '{query}':\n"]
    for _, doc in top:
        lines.append(f"### {doc['title']} [{doc['category']}]")
        lines.append(doc["summary"])
        if doc.get("specs"):
            lines.append("Key specs: " + " | ".join(f"{k}: {v}" for k, v in doc["specs"][:3]))
        lines.append("")

    return "\n".join(lines)


def get_all_docs() -> list[dict]:
    """Return all docs (sans heavy detail text) for the frontend browser."""
    return DOCS


def get_categories() -> list[str]:
    return ["rtx4090", "memory", "execution", "performance", "gemma4", "inference"]
