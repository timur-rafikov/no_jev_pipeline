set -e
P=.venv/bin/python
for m in nosys compact; do $P baseline_judge.py run --model Qwen/Qwen3-14B --device cuda --simplify $m --results out/qwen14_nothink_$m.jsonl; done
for m in nosys compact; do $P baseline_judge.py think --model Qwen/Qwen3-14B --device cuda --simplify $m --batch 8 --results out/qwen14_think_$m.jsonl; done
echo ALLDONE
