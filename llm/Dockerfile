FROM vllm/vllm-openai:latest

ARG LLM_MODEL=MediaTek-Research/Breeze-2-8B-Instruct
ARG HF_TOKEN=""

ENV HF_TOKEN=${HF_TOKEN}

# Build 時預載模型，部署不需要網路
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('${LLM_MODEL}')"

ENV HF_TOKEN=""

EXPOSE 8001

ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]
CMD ["--model", "MediaTek-Research/Breeze-2-8B-Instruct", "--port", "8001", "--max-model-len", "4096", "--dtype", "half", "--gpu-memory-utilization", "0.4"]
