"""Rebuild the public reference from pinned, hash-verified official downloads.

No network or candidate data. Invoke from repo root with source directory and output.
ANZSCO families are Jobwatch policy annotations, not ABS/O*NET classifications.
"""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict


def sheet(path, number):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as z:
        strings = [''.join(t.itertext()) for t in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', ns)]
        root = ET.fromstring(z.read(f'xl/worksheets/sheet{number}.xml'))
        for row in root.findall('.//m:row', ns):
            values = {}
            for cell in row.findall('m:c', ns):
                node = cell.find('m:v', ns)
                value = node.text if node is not None else ''
                if cell.attrib.get('t') == 's' and value:
                    value = strings[int(value)]
                values[re.sub('[0-9]', '', cell.attrib['r'])] = value
            yield values


def family(code):
    if code.startswith('2211'): return 'accounting'
    if code.startswith('551'): return 'finance_clerical'
    if code in {'531111', '561311', '561411', '561412', '561999'}: return 'back_office_admin'
    if code in {'224113', '224114', '224115'}: return 'data_analyst'
    if code == '261111': return 'business_analyst'
    if code.startswith('43'): return 'hospitality'
    if code.startswith('621'): return 'retail'
    if code.startswith('541'): return 'customer_service'
    return 'other'


def build(source: Path):
    manifest = json.loads((source / 'manifest.json').read_text())
    for name, receipt in manifest.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != receipt['sha256']:
            raise ValueError('source_hash_mismatch')
    def rows(name):
        with (source / name).open(newline='', encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))
    # Structure Table 5: six-digit occupation in E; title in F. Excludes nfd codes.
    titles = {r.get('E'): r['F'] for r in sheet(source / 'abs-structure.xlsx', 6)
              if re.fullmatch(r'\d{6}', r.get('E', '')) and r.get('F')}
    abs_pairs = defaultdict(set)
    previous = ''
    for r in sheet(source / 'abs-correspondence.xlsx', 4):
        if re.fullmatch(r'\d{4}', r.get('A', '')): previous = r['A']
        if previous and r.get('C') in titles: abs_pairs[previous].add(r['C'])
    soc_codes = defaultdict(set)
    for r in sheet(source / 'esco.xlsx', 1):
        isco = r.get('A', '').split('.')[0]
        soc = r.get('C', '')
        if re.fullmatch(r'\d{2}-\d{4}\.\d{2}', soc): soc_codes[soc].update(abs_pairs.get(isco, ()))
    dwas = [{'id': r['DWA Element ID'], 'title': r['DWA Element Name'], 'gwa_id': r['GWA Element ID']}
            for r in rows('gwas_to_iwas_to_dwas.csv')]
    core = {(r['O*NET-SOC Code'], r['Task ID']) for r in rows('task_statements.csv') if r['Task Type'] == 'Core'}
    task_counts = defaultdict(set); core_counts = defaultdict(set)
    for r in rows('tasks_to_dwas.csv'):
        key = r['O*NET-SOC Code'], r['DWA Element ID']
        task_counts[key].add(r['Task ID'])
        if (r['O*NET-SOC Code'], r['Task ID']) in core: core_counts[key].add(r['Task ID'])
    soc_dwas = defaultdict(dict)
    for (soc, dwa), tasks in task_counts.items():
        soc_dwas[soc][dwa] = len(core_counts[soc, dwa]) / len(tasks)
    ratings = defaultdict(dict)
    for r in rows('work_activities.csv'):
        if r['Scale ID'] == 'IM' and r['Recommend Suppress'] != 'Y' and r['Data Value']:
            ratings[r['O*NET-SOC Code']][r['Element ID']] = float(r['Data Value'])
    reverse = defaultdict(set)
    for soc, codes in soc_codes.items():
        if soc in soc_dwas:
            for code in codes: reverse[code].add(soc)
    occupations = []
    for code, socs in sorted(reverse.items()):
        weights = defaultdict(list); gwa = defaultdict(list)
        for soc in sorted(socs):
            for dwa, fraction in soc_dwas[soc].items(): weights[dwa].append(fraction)
            for key, value in ratings[soc].items(): gwa[key].append(value)
        occupations.append({'code': code, 'title': titles[code], 'family': family(code),
            'excluded': family(code) in {'hospitality','retail','customer_service'},
            'dwa_weights': {k: (len(v) + sum(v)) / len(socs) for k,v in sorted(weights.items())},
            'gwa_ratings': {k: sum(v)/len(v) for k,v in sorted(gwa.items())}})
    sources = {name: value['url'] + '#sha256=' + value['sha256'] for name,value in sorted(manifest.items())}
    return {'schema_version':1, 'version':'onet31.0-anzsco2022-esco2019-v1', 'sources':sources,
        'licenses': {name: 'CC-BY-4.0' for name in sources},
        'families':sorted({o['family'] for o in occupations}), 'dwas':sorted(dwas,key=lambda d:d['id']),
        'occupations':occupations,
        'crosswalks':[{'soc':soc,'anzsco_codes':sorted(c for c in codes if c in reverse)}
                     for soc,codes in sorted(soc_codes.items()) if soc in soc_dwas and any(c in reverse for c in codes)]}


if __name__ == '__main__':
    output = Path(sys.argv[2]); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(build(Path(sys.argv[1])),sort_keys=True,separators=(',',':'))+'\n')
