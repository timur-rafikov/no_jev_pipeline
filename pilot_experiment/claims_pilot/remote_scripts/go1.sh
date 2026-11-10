source /venv/main/bin/activate
export CUDA_VISIBLE_DEVICES=0 HF_HOME=/workspace/hf
python collect.py --model Qwen/Qwen3-14B --traces traces_46.jsonl --out out
echo COLLECT_DONE
