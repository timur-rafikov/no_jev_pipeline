source /venv/main/bin/activate
export HF_HOME=/dev/shm/hf CUDA_VISIBLE_DEVICES=0
python collect.py --model Qwen/Qwen3-32B --traces traces_46.jsonl --out out32
echo COLLECT32_DONE
