source /venv/main/bin/activate
export HF_HOME=/dev/shm/hf
python -c "from huggingface_hub import snapshot_download; p=snapshot_download(\"Qwen/Qwen3-32B\"); print(p)"
echo DL_DONE
