source /venv/main/bin/activate
export HF_HOME=/workspace/hf
python mech_analyze.py --data out --out out/mech_last.json --position last > out/mech_last.log 2>&1
python mech_analyze.py --data out --out out/mech_claimpos.json --position claim > out/mech_claim.log 2>&1
python sae_analyze.py --data out --out out/sae.json > out/sae.log 2>&1
CUDA_VISIBLE_DEVICES=0 python mech_causal.py --model Qwen/Qwen3-14B --traces traces_46.jsonl --data out --out out/causal.json > out/causal.log 2>&1
echo MECH_DONE > out/mech_done
