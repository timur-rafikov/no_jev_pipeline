"""Build current examples and a self-contained archive; no API calls."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import zipfile
from build_dataset import read_jsonl

ROOT=Path(__file__).resolve().parent
BATCH=ROOT/'batches/v4_holdout8_20261027'


def main(output=None):
    output=Path(output) if output else ROOT.parent/'no_jev_pipeline_v4.zip'
    exports=ROOT/'exports';exports.mkdir(exist_ok=True)
    # The prior release is preserved in history/v3_new10_release.
    for old in exports.iterdir():
        if old.is_file():old.unlink()
    for source in (BATCH/'exports').iterdir():
        if source.is_file():shutil.copy2(source,exports/source.name)
    shutil.copy2(ROOT/'README_V4.md',ROOT/'README.md')
    shutil.copy2(ROOT/'README_V4.md',exports/'REPORT.md')
    for src,name in [(ROOT/'SUMMARY_V4.json','SUMMARY.json'),(BATCH/'OFFLINE_VERIFICATION.json','OFFLINE_VERIFICATION.json'),(BATCH/'QUALITY_AUDIT.json','QUALITY_AUDIT.json')]:
        shutil.copy2(src,exports/name)
    records=read_jsonl(BATCH/'selected_records.jsonl')
    audit=json.loads((BATCH/'QUALITY_AUDIT.json').read_text())
    summary=json.loads((ROOT/'SUMMARY_V4.json').read_text())
    esc=html.escape
    def pre(value):
        value=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)
        return '<pre>'+esc(value)+'</pre>'
    cards=[]
    for index,record in enumerate(records,1):
        row=json.loads((BATCH/'results'/(record['case_id']+'.json')).read_text())
        entry=row['attempts'][-1];family=entry.get('family')
        chunks=[f'<article id="case-{index}"><h2>{index}. {esc(record["task_id"])}</h2>',
                f'<p>Автоматический результат: <strong>{esc(row["status"])}</strong> · {esc(record["model"])}</p>',
                '<p class="note">Аудит: '+esc(audit['cases'][index-1]['issue'])+'</p>',
                '<h3>Последняя исходная реплика</h3>',pre(record['messages'][-1]['content'])]
        if family:
            chunks+=['<h3>Удалённый фрагмент</h3>',pre(family['deletion']['exact_text']),
                     '<h3>Реплика после правки</h3>',pre(family['base']['messages'][-1]['content'])]
            for variant in family['variants']:
                chunks+=['<details class="variant"><summary>'+esc(variant['condition'])+'</summary>',
                         '<p>Полный вход judge, без метки и служебного вердикта:</p>',pre(variant['judge_payload']),'</details>']
        else:chunks+=['<p>Подходящая правка не предложена; пять вариантов не создавались.</p>']
        chunks+=['<details><summary>Полный исходный трейс</summary>',pre({'messages':record['messages'],'tools':record['tools']}),'</details>',
                 '<details><summary>Ревью и решение</summary>',pre({'review':entry['review'],'decision':entry['decision']}),'</details></article>']
        cards.append(''.join(chunks))
    document='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Пилот v4.2 — восемь задач</title><style>
body{max-width:1100px;margin:32px auto;padding:0 20px;background:#f4f6f8;color:#17232f;font:16px/1.55 system-ui,sans-serif}h1{font-size:30px}article{background:white;border:1px solid #dbe2e8;border-radius:12px;padding:24px;margin:22px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f7;border:1px solid #dce4ea;padding:14px;border-radius:6px;font:13px/1.5 ui-monospace,monospace}summary{cursor:pointer;font-weight:650;padding:9px 0}.note{background:#fff3d4;border-left:4px solid #d8a342;padding:12px}nav a{display:inline-block;padding:4px 10px;margin-right:6px;background:white;border:1px solid #dbe2e8;border-radius:6px;color:#125da6}
</style><h1>Пилот v4.2: 8 задач → 20 вариантов</h1><p class="note"><strong>Автоматически принято 5 вариантов; без замечаний аудита — 0.</strong> Принятое семейство оставлено для разбора метки. Полностью автоматическое качество для массовой сборки не подтверждено.</p><p>Все варианты одного семейства имеют одну основу. Отличается только атрибутированная цитата о статусе. Результатов эксперимента с целевым judge здесь нет.</p>'''
    document+='<nav>'+''.join(f'<a href="#case-{i}">{i}</a>' for i in range(1,9))+'</nav>'+''.join(cards)
    document+='<details><summary>Итоги и расходы</summary>'+pre(summary)+'</details></html>'
    assert document.count('<article ')==8 and document.count('class="variant"')==20
    assert '<script' not in document and 'src="http' not in document
    (exports/'examples.html').write_text(document)
    files=[]
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if not path.is_file() or '__pycache__' in rel.parts or any(x.startswith('.') for x in rel.parts) or path.suffix in ('.zip','.pyc'):
            continue
        data=path.read_bytes()
        if re.search(rb'sk-or-v1-[a-fA-F0-9]{40,}',data):raise ValueError('credential_found_in_deliverable')
        files.append((path,{'path':str(rel),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}))
    manifest={'files':[meta for _,meta in files],'protocol':'no-jev-edit-review-v4.2','secrets_included':False}
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path,meta in files:archive.write(path,'no_jev_pipeline/'+meta['path'])
        archive.writestr('BUNDLE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for meta in manifest['files']:
            assert hashlib.sha256(archive.read('no_jev_pipeline/'+meta['path'])).hexdigest()==meta['sha256']
    print(json.dumps({'archive':str(output),'bytes':output.stat().st_size,'files':len(files),
                      'html_cases':8,'html_variants':20,'archive_hashes_verified':True}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args();main(args.output)
