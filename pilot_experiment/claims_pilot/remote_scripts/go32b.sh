source /venv/main/bin/activate
export HF_HOME=/dev/shm/hf
(python mech_analyze.py --data out32 --out out32/mech_last.json --position last > out32/mech_last.log 2>&1
 python mech_analyze.py --data out32 --out out32/mech_claimpos.json --position claim > out32/mech_claim.log 2>&1
 python perm_control.py out32 > out32/perm.log 2>&1
 python sae_analyze.py --data out32 --out out32/sae.json --family Qwen3-32B --layers 16,32,48 > out32/sae.log 2>&1) &
CUDA_VISIBLE_DEVICES=0 python mech_causal.py --model Qwen/Qwen3-32B --traces traces_46.jsonl --data out32 --out out32/causal.json --layers 16,32,40,46,52,58,63 > out32/causal.log 2>&1
wait
echo ALL32_DONE > out32/all_done
