#!/bin/bash
# Launcher for vLLM serving GLM-OCR on GPU 1.
# Uses TRITON_ATTN backend to avoid FlashInfer JIT path.

cd "$(dirname "$0")"
source .venv/bin/activate

export CUDA_HOME=/usr/lib/cuda
export PATH=$CUDA_HOME/bin:$PATH
export CUDA_VISIBLE_DEVICES=1
export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=TRITON_ATTN
export VLLM_LOGGING_LEVEL=INFO

exec vllm serve zai-org/GLM-OCR \
  --port 8080 \
  --served-model-name glm-ocr \
  --gpu-memory-utilization 0.85 \
  --max-model-len 8192 \
  --trust-remote-code \
  --enforce-eager \
  --attention-backend TRITON_ATTN
