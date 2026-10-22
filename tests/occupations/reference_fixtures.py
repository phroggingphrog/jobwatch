"""Tiny invented public occupation data; never candidate records."""
import csv
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, columns)
        writer.writeheader(); writer.writerows(rows)


def write_onet(directory, drop_column=None):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    write_csv(directory / 'occupation_data.csv', ['O*NET-SOC Code', 'Title', 'Description'], [
        {'O*NET-SOC Code': '13-2011.00', 'Title': 'Accountants', 'Description': 'Prepare financial records.'}])
    columns = ['O*NET-SOC Code', 'Task ID', 'Task Type', 'Task']
    rows = [{'O*NET-SOC Code': '13-2011.00', 'Task ID': '2', 'Task Type': 'Supplemental', 'Task': 'Supplemental task B'},
            {'O*NET-SOC Code': '13-2011.00', 'Task ID': '10', 'Task Type': 'Core', 'Task': 'Core task A'},
            {'O*NET-SOC Code': '13-2011.00', 'Task ID': '3', 'Task Type': 'Core', 'Task': 'Core task first'}]
    if drop_column:
        columns.remove(drop_column)
        rows = [{k:v for k,v in r.items() if k!=drop_column} for r in rows]
    write_csv(directory / 'task_statements.csv', columns, rows)
    write_csv(directory / 'essential_skills.csv', ['O*NET-SOC Code', 'Element Name', 'Scale ID', 'Data Value'], [
        {'O*NET-SOC Code': '13-2011.00', 'Element Name': 'Mathematics', 'Scale ID': 'IM', 'Data Value': '4.5'},
        {'O*NET-SOC Code': '13-2011.00', 'Element Name': 'Ignored level', 'Scale ID': 'LV', 'Data Value': '5'},
        *[{'O*NET-SOC Code': '13-2011.00', 'Element Name': f'Skill {i:02}', 'Scale ID': 'IM', 'Data Value': str(i/10)} for i in range(11)]])
    return directory


def write_esco(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    write_csv(directory / 'occupations_en.csv', ['conceptUri', 'preferredLabel', 'description', 'iscoGroup', 'code'], [
        {'conceptUri': 'http://data.europa.eu/esco/occupation/test', 'preferredLabel': 'accountant',
         'description': 'Produces accounts', 'iscoGroup': '2411', 'code': '2411.1'}])
    write_csv(directory / 'skills_en.csv', ['conceptUri', 'preferredLabel'], [
        {'conceptUri': 's1', 'preferredLabel': 'keep accounting records'}, {'conceptUri': 's2', 'preferredLabel': 'optional skill'}])
    write_csv(directory / 'occupationSkillRelations_en.csv', ['occupationUri', 'skillUri', 'relationType'], [
        {'occupationUri': 'http://data.europa.eu/esco/occupation/test', 'skillUri': 's1', 'relationType': 'essential'},
        {'occupationUri': 'http://data.europa.eu/esco/occupation/test', 'skillUri': 's2', 'relationType': 'optional'}])
    return directory


def write_xlsx(path, sheets):
    strings = []; indices = {}
    def col(n):
        out=''
        while n: n,r=divmod(n-1,26);out=chr(65+r)+out
        return out
    with zipfile.ZipFile(path, 'w') as z:
        for number, rows in sheets.items():
            body=[]
            for i,row in enumerate(rows,1):
                cells=[]
                for j, value in enumerate(row,1):
                    value=str(value)
                    if value not in indices:indices[value]=len(strings);strings.append(value)
                    cells.append(f'<c r="{col(j)}{i}" t="s"><v>{indices[value]}</v></c>')
                body.append('<row>'+''.join(cells)+'</row>')
            z.writestr(f'xl/worksheets/sheet{number}.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(body)+'</sheetData></worksheet>')
        z.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'+''.join('<si><t>'+escape(t)+'</t></si>' for t in strings)+'</sst>')
