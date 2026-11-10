"""Offline verification, readable report and secret-scanned reproducible ZIP."""
import collections
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import zipfile
import assemble_v6 as a
import pipeline_v6 as p
from budget_v6 import Client
from client import save

ROOT=Path(__file__).resolve().parent


def main(output):
    batch=ROOT/'batches/v6_new3_20261028'
    verification=a.verify(batch);summary=verification['result'];client=Client(ROOT)
    budget=client.accounting()
    receipts=[json.loads(f.read_text()) for f in (ROOT/'requests').glob('*.json')]
    new=[r for r in receipts if r.get('tag',{}).get('protocol','').startswith('no-jev-edit-review-v6.')]
    if any(r.get('actual_usd') is None for r in new):raise ValueError('unresolved_new_charge')
    if budget['session_actual_usd']+max(0,budget['session_reserved_delta_usd'])>.2+1e-9:
        raise ValueError('session_limit_exceeded')
    costs=collections.defaultdict(lambda:{'calls':0,'cost_usd':0.0})
    for r in new:
        model=r['request']['model'];costs[model]['calls']+=1;costs[model]['cost_usd']+=r['actual_usd']
    checks=[]
    for path in sorted((ROOT/'diagnostics_v6/results').glob('*.json')):
        r=json.loads(path.read_text());checks.append({'case':r['case_id'],**r['evaluation']})
    allcases=json.loads((ROOT/'diagnostics_v6/cases.json').read_text())
    report={'protocol':p.VERSION,'model_chain':[p.GENERATOR,p.REVIEWER,p.AUDITOR],
        'budget':budget,'new_calls':len(new),'cost_by_model_including_debugging':dict(costs),
        'initial_diagnostics':json.loads((ROOT/'history/v6_0_initial/diagnostics_v6/SUMMARY.json').read_text()),
        'final_diagnostics':{'planned':len(allcases),'completed':len(checks),
            'full_pass':sum(r['full_pass'] for r in checks),'rows':checks},
        'new_real_sources':summary,'verification':verification,
        'offline_tests':(ROOT/'offline_test_results_v6.txt').read_text(),
        'source_review':json.loads((ROOT/'SOURCE_REVIEW_V6.json').read_text()),
        'citation_false_fact_controls':json.loads((ROOT/'CITATION_CONTROLS_V6.json').read_text()),
        'billing_reconciliation':json.loads((ROOT/'BILLING_V6.json').read_text()),
        'limits':['Small pilot; no validated population precision/recall or yield estimate.',
            'Diagnostic references and source review are assistant judgments, not human gold.',
            'Initial v6.0 false holds preserved; no relabeling of paid responses.',
            'Full judge experiment still requires a frozen judge prompt and model.'],
        'assembly_ready':summary['accepted_families']>0 and verification['passed'],
        'quality_validated_at_scale':False,
        'ready_for_judge_run':False}
    save(ROOT/'RELEASE_V6.json',report)
    e=html.escape
    parts=['<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Пайплайн v6 — результаты проверки</title><style>body{font:16px/1.55 system-ui;max-width:1040px;margin:auto;padding:28px;color:#182635;background:#f8fafc}h1,h2{line-height:1.2}section,details{background:white;border:1px solid #d7e0e8;border-radius:10px;padding:18px;margin:18px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}table{border-collapse:collapse;width:100%}th,td{text-align:left;border-bottom:1px solid #ddd;padding:9px}summary{cursor:pointer;font-weight:600}.muted{color:#516273}code{overflow-wrap:anywhere}</style>',
        '<h1>Пайплайн v6: проверка и примеры</h1>',
        '<p>Gemini 3.8 Flash → GPT-5.4-mini → DeepSeek V4.1 Flash 1017. Постановка с пятью вариантами сохранена.</p>',
        '<section><h2>Фактический результат</h2>',
        f'<p>Расход всей отладки: <b>${budget["session_actual_usd"]:.6f} из $0.20</b>. Новых исходников: {summary["selected"]}; принятых семейств: <b>{summary["accepted_families"]}</b>; готовых вариантов: <b>{summary["accepted_variants"]}</b>.</p>',
        f'<p>Контроли финальной версии: {sum(r["full_pass"] for r in checks)}/{len(checks)}; запланировано {len(allcases)}. Это проверка известных случаев, не оценка точности на всём датасете.</p>',
        '<p>Два отдельных контроля исправления цитат пройдены: модель отказалась подменять Pending на Filled и количество 50 на 150.</p>',
        '<pre>'+e(report['offline_tests'])+'</pre></section>',
        '<section><h2>Что было исправлено</h2><p>Общее правило завершения действия и доставки ответа для двух ревьюеров; доказательства результата и точные роли цитат; фиксированное число оценок по числу пользовательских запросов; сверка меток до и после удаления; точные цитаты с граничным многоточием; доказанные failure-примеры; один ограниченный повтор оборванного по длине аудита. Первая итерация дала два лишних отказа из шести контролей; эти ответы сохранены в history/v6_0_initial.</p>',
        '<p>Числа, ID, адреса и статусы Open/Pending сами по себе не запрещены. Неисполненная покупка и успешно поданная заявка различаются по запросу пользователя.</p></section>',
        '<section><h2>Контрольные примеры финальной версии</h2><table><tr><th>Пример</th><th>Семантика</th><th>Формат и доказательства</th></tr>']
    for row in checks:
        parts.append('<tr><td>'+e(row['case'])+'</td><td>'+('OK' if row['semantic_constraints_pass'] else e(', '.join(row['semantic_errors'])))+'</td><td>'+('OK' if row['contract_valid'] else e(str(row['contract_error'])))+'</td></tr>')
    parts.append('</table></section><h2>Новые реальные исходники</h2>')
    records=a.legacy.read_jsonl(batch/'selected_records.jsonl')
    for source in records:
        path=batch/'results'/(source['case_id']+'.json');row=json.loads(path.read_text()) if path.exists() else {'status':'not_started'}
        parts.append('<section><h3>'+e(source['id'])+'</h3><p>Статус: <b>'+e(row['status'])+'</b></p>')
        parts.append('<pre>'+e(json.dumps(row.get('decision',{}),ensure_ascii=False,indent=2))+'</pre>')
        parts.append('<p>Предложенное удаление:</p><pre>'+e(json.dumps(row.get('generation',{}),ensure_ascii=False,indent=2))+'</pre>')
        family=row.get('family')
        if family:
            parts.append('<table><tr><th>Условие</th><th>Атрибутированная цитата</th></tr>')
            for v in family['variants']:
                parts.append('<tr><td>'+e(v['condition'])+'</td><td>'+e(json.dumps(v['judge_payload']['status_annotation'],ensure_ascii=False))+'</td></tr>')
            parts.append('</table><details><summary>Общая основа всех пяти вариантов — полный трейс</summary>')
            for m in family['base']['messages']:
                parts.append('<details><summary>'+e(m['id']+' · '+m['role'])+'</summary><pre>'+e(m.get('content',''))+'</pre></details>')
            parts.append('</details>')
        for name in ['review','audit']:
            if name in row:parts.append('<details><summary>'+name+'</summary><pre>'+e(json.dumps(row[name],ensure_ascii=False,indent=2))+'</pre></details>')
            if name+'_citation_fix' in row:parts.append('<details><summary>Исправление цитат: '+name+'</summary><pre>'+e(json.dumps(row[name+'_citation_fix'],ensure_ascii=False,indent=2))+'</pre></details>')
        parts.append('</section>')
    parts.append('<section><h2>Ограничения</h2><p>Это небольшой пилот автоматической разметки. Гарантия качества тысяч примеров из него не следует. Контрольные случаи повторно использовались для отладки. Для запуска сборщика используйте README.md; целевой judge и его промпт пока не заданы.</p></section></html>')
    (ROOT/'REPORT_V6.html').write_text(''.join(parts))
    files=[]
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if not path.is_file() or any(x.startswith('.') or x=='__pycache__' for x in rel.parts) or path.suffix in ['.pyc','.zip','.tmp']:continue
        content=path.read_bytes()
        if re.search(rb'sk-or-v1-[A-Za-z0-9]{30,}',content):raise ValueError('secret_in_bundle')
        files.append((path,{'path':str(rel),'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}))
    manifest={'protocol':p.VERSION,'files':[r for _,r in files],'secrets_included':False}
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path,meta in files:z.write(path,'no_jev_pipeline/'+meta['path'])
        z.writestr('no_jev_pipeline/BUNDLE_MANIFEST_V6.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(output) as z:
        if z.testzip():raise ValueError('bad_zip')
        for _,meta in files:
            if hashlib.sha256(z.read('no_jev_pipeline/'+meta['path'])).hexdigest()!=meta['sha256']:raise ValueError('zip_hash_mismatch')
    print(json.dumps({'file':str(output),'bytes':Path(output).stat().st_size,'files':len(files),
        'cost_usd':budget['session_actual_usd'],'accepted_families':summary['accepted_families'],
        'accepted_variants':summary['accepted_variants'],'diagnostics_full_pass':report['final_diagnostics']['full_pass'],
        'diagnostics_completed':len(checks)},indent=2))


if __name__=='__main__':main(Path(sys.argv[1]).resolve())
