source /venv/main/bin/activate
export CUDA_VISIBLE_DEVICES=0 HF_HOME=/workspace/hf
for m in compact nosys full; do
  python baseline_judge.py run --model Qwen/Qwen3-14B --device cuda --traces traces_46.jsonl --simplify $m --results out/vis46_qwen14_${m}_nothink.jsonl
done
echo ALLDONE
