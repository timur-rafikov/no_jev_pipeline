source /venv/main/bin/activate
export HF_HOME=/workspace/hf
python sae_analyze.py --data out --out out/sae.json > out/sae.log 2>&1
CUDA_VISIBLE_DEVICES=0 python mech_causal.py --model Qwen/Qwen3-14B --traces traces_46.jsonl --data out --out out/causal.json > out/causal.log 2>&1
echo CAUSAL_DONE > out/causal_done
