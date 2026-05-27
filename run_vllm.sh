#!/bin/bash
# vLLM launcher: Qwen2.5-VL-7B-Instruct-AWQ, single GPU (Quadro RTX 5000, 16GB).
# Turing(SM 7.5): FA2 미지원, vLLM 이 자동 SDPA fallback. TRITON_ATTN + enforce-eager 안정.
# 32B-AWQ TP=2 는 Turing 환경에서 IPC stuck 으로 사용 불가 → 단일 GPU 7B 로 폴백.

cd "$(dirname "$0")"
source .venv/bin/activate

export CUDA_HOME=/usr/lib/cuda
export PATH=$CUDA_HOME/bin:$PATH
export CUDA_VISIBLE_DEVICES=1
export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=TRITON_ATTN
export VLLM_LOGGING_LEVEL=INFO

exec vllm serve Qwen/Qwen2.5-VL-7B-Instruct-AWQ \
  --port 8080 \
  --served-model-name qwen2.5-vl-7b \
  --quantization awq \
  --gpu-memory-utilization 0.85 \
  --max-model-len 8192 \
  --limit-mm-per-prompt '{"image": 4}' \
  --trust-remote-code \
  --enforce-eager \
  --attention-backend TRITON_ATTN
