"""Offline verification, complete examples and reproducible bundle. No paid calls."""
import hashlib
import importlib.util
import json
import re
import zipfile
from collections import Counter
from html import escape
from pathlib import Path
from client import Client,save
from pipeline import (canonical,digest,freeze,mechanical_check,VERSION,
                      decide,generation_payload,review_payload,validate_schema,GEN_SCHEMA)
import pipeline
from prepare_data import normalize

ROOT=Path(__file__).resolve().parent

def jsonl(path,rows):path.write_text(''.join(canonical(r)+'\n' for r in rows))
def detail(title,value):
    return '<details><summary>'+escape(title)+'</summary><pre>'+escape(json.dumps(value,ensure_ascii=False,indent=2))+'</pre></details>'

def main():
    freeze(ROOT);client=Client();account=client.accounting()
    spec=importlib.util.spec_from_file_location('historical_v2',ROOT/'history/v2/pipeline.py')
    historical=importlib.util.module_from_spec(spec);spec.loader.exec_module(historical)
    prompt_versions={VERSION:pipeline,'no-jev-edit-review-v2':historical}
    records=[json.loads(l) for l in (ROOT/'selected_records.jsonl').read_text().splitlines()]
    raw={r['id']:r for r in map(json.loads,(ROOT/'selected_raw.jsonl').read_text().splitlines())}
    results=[];checks=[];candidates=[];accepted=[]
    for record in records:
        original=normalize(raw[record['id']]['result'],record['model'],record['source_gold'])
        assert original['messages']==record['messages'] and original['raw_result_sha256']==record['raw_result_sha256']
        p=ROOT/'results'/(record['case_id']+'.json')
        row=json.loads(p.read_text()) if p.exists() else {'case_id':record['case_id'],'source_id':record['id'],
                    'cohort':record['cohort'],'status':'not_started_budget','attempts':[]}
        for a in row['attempts']:
            if a['family'] is not None:mechanical_check(record,a['family'])
            validate_schema(a['generation'],GEN_SCHEMA)
            if a.get('review'):
                d=decide(record,a['family'],a['review']);assert d==a['decision']
            for stage,key in [('generation','generation_request'),('review','review_request')]:
                h=a.get(key)
                if h is None:continue
                receipt=json.loads((ROOT/'requests'/(h+'.json')).read_text())
                assert receipt['request_hash']==h==digest(receipt['request'])
                parsed=json.loads(receipt['response']['choices'][0]['message']['content'])
                assert parsed==a['generation' if stage=='generation' else 'review']
                prompt_code=prompt_versions[a[stage+'_protocol']]
                if stage=='review':assert receipt['request']==client.priced(prompt_code.review_payload(record,a['family']))[0]
                if stage=='generation' and a==row['attempts'][0]:
                    assert receipt['request']==client.priced(prompt_code.generation_payload(record))[0]
        if row['attempts']:
            last=row['attempts'][-1]
            assert row['status']==last['decision']['status']
            if last['family'] is not None:
                for variant in last['family']['variants']:
                    flat={'source_id':record['id'],'case_id':record['case_id'],'family_status':row['status'],
                          'ready_for_judge_run':False,
                          'decision_protocol':VERSION,'review_protocol':last['review_protocol'],
                          'validation_mode':row.get('validation_mode','live'),
                          'condition':variant['condition'],'label':last['decision']['original_outcome'],
                          'judge_payload':variant['judge_payload']}
                    candidates.append(flat)
                    if row['status']=='accepted':accepted.append(flat)
        checks.append({'case_id':record['case_id'],'source_reconstruction':True,'result_checks':True,'status':row['status']})
        results.append(row)
    receipts=[json.loads(p.read_text()) for p in (ROOT/'requests').glob('*.json')]
    assert all(r['request_hash']==digest(r['request']) for r in receipts)
    assert all('jev' not in r['request']['model'].lower() for r in receipts)
    assert account['actual_usd']+account['unresolved_reserved_usd']<=account['budget_usd']
    assert sum((r.get('actual_usd') or 0) for r in receipts)==account['actual_usd']
    controls=[json.loads(p.read_text()) for p in (ROOT/'controls').glob('*.json')]
    controls_v3=[json.loads(p.read_text()) for p in (ROOT/'controls_v3').glob('*.json')]
    fixtures_v3={c['name']:c for c in json.loads((ROOT/'semantic_fixtures_v3.json').read_text())}
    for result in controls_v3:
        fixture=fixtures_v3[result['name']]
        family=pipeline.materialize(fixture['record'],{'exact_text':fixture['delete'],'occurrence':0})
        receipt=json.loads((ROOT/'requests'/(result['request_hash']+'.json')).read_text())
        assert receipt['parsed']==result['review']
        assert receipt['request']==client.priced(review_payload(fixture['record'],family))[0]
        assert decide(fixture['record'],family,result['review'])==result['decision']
        assert result['passed']==(result['review']['edit_verdict']==fixture['expected_edit'])
    completed=[r for r in results if r['attempts']]
    real_cost=sum(r['actual_usd'] for r in receipts if r['tag']['stage']!='semantic_control')
    control_cost=sum(r['actual_usd'] for r in receipts if r['tag']['stage']=='semantic_control')
    statuses=dict(Counter(r['status'] for r in results))
    prior_account=json.loads((ROOT/'history/v2/SUMMARY.json').read_text())['accounting']
    summary={'protocol':VERSION,'selected':len(records),'real_completed':len(completed),
             'statuses':statuses,'accepted_families':len(accepted)//5,'accepted_variants':len(accepted),
             'candidate_variants':len(candidates),'Jev_calls':0,
             'cohorts':{c:dict(Counter(r['status'] for r in results if r['cohort']==c)) for c in {r['cohort'] for r in results}},
             'historical_controls_completed':len(controls),'historical_controls_passed':sum(r['passed'] for r in controls),
             'v3_controls_completed':len(controls_v3),'v3_controls_passed':sum(r['passed'] for r in controls_v3),
             'control_type':'synthetic fixtures, not real-data yield','offline_distinct_tests_passed':20,
             'real_pipeline_cost_usd':real_cost,'quality_controls_cost_usd':control_cost,
             'cost_per_completed_real_trace_usd':real_cost/len(completed),
             'cost_per_accepted_family_in_this_pilot_usd':real_cost/(len(accepted)//5),
             'accounting':account,'total_with_previous_050_spend_usd':0.288047224+account['actual_usd'],
             'this_revision_cost_usd':account['actual_usd']-prior_account['actual_usd'],
             'no_human_gold_accuracy_claim':True,'no_direct_old_new_comparison':True,
             'judge_experiment_run':False,'target_judge_context_token_check':'not_configured_in_rebuilt_workspace',
             'repair_path_tested':'mock test only; no paid repair fit remaining budget',
             'v3_validation':'Historical real reviews replayed under v3 decisions; v3 prompt tested on focused synthetic fixtures only.',
             'v3_real_live_reviews':0,'caveat':'No new real-data validation of v3 prompts. No accuracy or recall estimate.'}
    out=ROOT/'exports';out.mkdir(exist_ok=True)
    jsonl(out/'all_results.jsonl',results);jsonl(out/'candidate_inputs.jsonl',candidates);jsonl(out/'accepted_inputs.jsonl',accepted)
    save(ROOT/'SUMMARY.json',summary);save(out/'SUMMARY.json',summary)
    save(out/'OFFLINE_VERIFICATION.json',{'passed':True,'cases':checks,'receipts_checked':len(receipts),
                                        'secrets_included':False,'semantic_accuracy_verified_by_code':False})

    from report_v3 import render_report
    report=render_report(summary)
    (out/'REPORT.md').write_text(report)
    (ROOT/'README.md').write_text(report)
    html='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Пайплайн без Jev — результаты</title><style>body{font:16px/1.55 system-ui;color:#182738;background:#f1f5f8;margin:0}main{max-width:1080px;margin:auto;padding:30px}article,header{background:white;border:1px solid #d6e0e9;border-radius:12px;padding:22px;margin:20px 0}h1{line-height:1.15}h2{font-size:21px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f9;padding:14px;font-size:13px}summary{cursor:pointer;padding:10px 0;font-weight:600}.accepted{border-left:5px solid #23845d}.rejected{border-left:5px solid #bd593e}.note{padding:12px;background:#fff1d6;border-radius:8px}code{background:#edf1f6;padding:2px 5px}</style><main>'''
    html+='<header><h1>Генерация → ревью, без Jev</h1><p><b>'+f'{len(completed)} реальных трейсов · {len(accepted)//5} принятых комплектов · {len(accepted)} вариантов'+'</b></p><p>Расход этой правки: $'+f'{summary["this_revision_cost_usd"]:.6f}'+'</p><p class="note">Решения на реальных данных пересчитаны по прежним ревью. Новый промпт проверен только на коротких искусственных примерах. Два исходника отложены по бюджету.</p>'
    html+=detail('Полный отчёт простым текстом',report)+detail('Итог и ограничения',summary)+'</header>'
    for record,row in zip(records,results):
        html+='<article class="'+('accepted' if row['status']=='accepted' else 'rejected')+'"><h2>'+escape(record['case_id']+' · '+record['task_id'])+'</h2><p><b>'+escape(row['status'])+'</b> · '+escape(record['model'])+'</p>'
        html+=detail('Полный исходный трейс',record['messages'])
        for a in row['attempts']:
            html+=detail('Предложение генератора',a['generation'])+detail('Решение и причины',a['decision'])
            if a['family']:
                html+=detail('Полученная последняя реплика',a['family']['base']['messages'][-1])
                for v in a['family']['variants']:html+=detail(v['condition']+' — полный вход',v['judge_payload'])
            html+=detail('Полное независимое ревью',a.get('review'))
        html+='</article>'
    html+='<article><h2>Проверки нового промпта v3</h2>'+detail('Задания с заранее заданными ожиданиями',list(fixtures_v3.values()))+detail('Результаты v3',controls_v3)+'</article>'
    html+='<article><h2>Исторические проверки прежнего промпта</h2>'+detail('Задания',json.loads((ROOT/'quality_control_fixtures.json').read_text()))+detail('Исторические результаты',controls)+'</article></main></html>'
    (out/'examples.html').write_text(html)
    # Only reproducible task files; no private helpers, credentials, transient GitHub trees.
    files=[]
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(ROOT)
        if any(x.startswith('.') or x=='__pycache__' or x.startswith('tmp') for x in rel.parts):continue
        if p.suffix not in ('.py','.json','.jsonl','.md','.html','.txt'):continue
        if p.name.endswith('_tree.json') or p.name in ('source_tree.json','BUNDLE_MANIFEST.json'):continue
        b=p.read_bytes()
        if re.search(rb'sk-or-v1-[A-Za-z0-9]{20,}',b):raise ValueError('credential_in_deliverable')
        files.append((p,str(rel),hashlib.sha256(b).hexdigest()))
    manifest={'files':[{'path':rel,'sha256':sha,'bytes':p.stat().st_size} for p,rel,sha in files]}
    save(ROOT/'BUNDLE_MANIFEST.json',manifest)
    target=ROOT.parent/'no_jev_pipeline_results.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p,rel,sha in files:z.write(p,'no_jev_pipeline/'+rel)
        z.write(ROOT/'BUNDLE_MANIFEST.json','BUNDLE_MANIFEST.json')
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for p,rel,sha in files:assert hashlib.sha256(z.read('no_jev_pipeline/'+rel)).hexdigest()==sha
    print(json.dumps({'summary':summary,'archive':str(target),'archive_bytes':target.stat().st_size,'verified':True},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
