"""Build readable markdown for the BFCL-failure traces, sorted by how many judge runs wrongly accepted them.
Run from pilot_experiment/ with ../raw present (BFCL score files give the expected calls)."""
import csv, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / 'raw'
RUNS = ['minicpm5_2b_full_nothink', 'qwen3_14b_full_nothink', 'qwen3_14b_nosys_nothink', 'qwen3_14b_compact_nothink',
        'qwen3_14b_full_think', 'qwen3_14b_nosys_think', 'qwen3_14b_compact_think']
man = {r['case_id']: r for r in csv.DictReader(open(HERE / 'manual_review.csv'))}
traces = {t['case_id']: t for t in map(json.loads, open(HERE / 'traces_50.jsonl'))}
runs = {r: {json.loads(l)['case_id']: json.loads(l) for l in open(HERE / 'results' / f'{r}.jsonl')} for r in RUNS}
scores = {}
for m in {t['model'] for t in traces.values()}:
    for l in list(open(RAW / f'{m}_score.jsonl'))[1:]:
        s = json.loads(l); scores[(m, s['id'])] = s


def flat(x):
    return [x] if isinstance(x, str) else [y for i in x for y in flat(i)]


def fence(text):
    return '```\n' + (text or '').replace('```', "'''") + '\n```'


out = HERE / 'review'
out.mkdir(exist_ok=True)
rows = []
for cid, t in traces.items():
    if t['source_gold'] != 'failure':
        continue
    s = scores[(t['model'], t['task_id'])]
    accepted = [r for r in RUNS if runs[r][cid]['p_yes_norm'] >= 0.5]
    cat = man[cid]['manual_category']
    L = [f"# {cid} ({t['task_id']}, агент {t['model']})", '',
         f"- **Ручная категория:** `{cat}`: {man[cid]['note']}",
         f"- **Ошибка BFCL:** `{s['error']['error_type'].split(':')[1]}`: {s['error']['error_message']}",
         f"- **Судьи приняли («Да») в {len(accepted)} из {len(RUNS)} прогонов**", '',
         '| прогон | p(Да) |', '|---|---|']
    L += [f"| {r} | {runs[r][cid]['p_yes_norm']:.3f} {'**← принял**' if r in accepted else ''} |" for r in RUNS]
    d = s['error'].get('details', {})
    if 'missing_items' in d:
        L += ['', f"**Не хватает результата, который есть в эталоне:** `{str(d['missing_items'])[:300]}`"]
    pa = json.loads(s['possible_answer']) if isinstance(s['possible_answer'], str) else s['possible_answer']
    md = json.loads(s['model_result_decoded']) if isinstance(s['model_result_decoded'], str) else s['model_result_decoded']
    L += ['', '## Эталон BFCL и вызовы агента по ходам', '', '| ход | эталон | агент |', '|---|---|---|']
    for i in range(max(len(pa), len(md))):
        g = '; '.join(flat(pa[i])) if i < len(pa) else ''
        a = '; '.join(flat(md[i])) if i < len(md) else ''
        L.append(f"| {i} | `{g[:300]}` | `{a[:300]}` |".replace('|', '\\|', 0))
    L += ['', '## Диалог (без системного промпта)', '']
    for m in t['messages']:
        if m['role'] in ('system', 'developer'):
            continue
        L += [f"**{m['role'].upper()}** `{m['id']}`", fence(m.get('content') if isinstance(m.get('content'), str) else json.dumps(m.get('content'), ensure_ascii=False)), '']
    (out / f'{cid}.md').write_text('\n'.join(L))
    rows.append((len(accepted), cid, t['task_id'], cat, s['error']['error_type'].split(':')[1], man[cid]['note']))

rows.sort(key=lambda r: (-r[0], r[1]))
idx = ['# Провальные по BFCL трейсы: где судья ошибается', '',
       'Отсортировано по числу прогонов судьи (из 7), которые приняли трейс как успешный. Категория — моя ручная разметка.', '',
       '| принято | трейс | ручная категория | тип ошибки BFCL | что не так |', '|---|---|---|---|---|']
idx += [f"| {n}/7 | [{c}]({c}.md) | `{cat}` | {et} | {note} |" for n, c, tid, cat, et, note in rows]
(out / 'INDEX.md').write_text('\n'.join(idx) + '\n')
print(len(rows), 'files in', out)
