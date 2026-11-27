"""Build the `databricks genie create-space` payload from the version-controlled spec
(resources/genie/dpp_compliance_explorer.yml).

Usage:
  python scripts/create_genie_space_payload.py resources/genie/dpp_compliance_explorer.yml \
      <catalog> <schema> <warehouse-id> <workspace-parent-folder> > /tmp/genie.json
  databricks genie create-space --json @/tmp/genie.json
"""
import sys, json, re, hashlib
spec_path, catalog, schema, wh, parent = sys.argv[1:6]
txt=open(spec_path).read()
def block(key):
    m=re.search(rf'^{key}:\s*\n((?:\s+- .*\n?)+)', txt, re.M)
    return [l.strip()[2:].strip().strip('"') for l in m.group(1).splitlines() if l.strip().startswith('- ')]
desc=re.search(r'^description: \|\n((?:  .*\n|\n)+)', txt, re.M).group(1)
desc='\n'.join(l[2:] if l.startswith('  ') else l for l in desc.splitlines()).strip()
tables=sorted(t.replace('${var.catalog}',catalog).replace('${var.schema}',schema) for t in block('tables'))
hid=lambda s: hashlib.md5(s.encode()).hexdigest()
qs=sorted(({"id":hid(q),"question":[q]} for q in block('sample_questions')), key=lambda x:x['id'])
space={"version":2,"config":{"sample_questions":qs},
 "data_sources":{"tables":[{"identifier":t} for t in tables]},
 "instructions":{"text_instructions":[{"id":hid('instr'),"content":[desc+"\n\ngold_supplier_declaration_coverage: one row per supplier; evidence_status is COVERED, PARTLY_EXPIRED or NO_VALID_EVIDENCE and comes from supplier material declaration files ingested from the RAW landing volume."]}]}}
print(json.dumps({"warehouse_id":wh,"title":"DPP Compliance Explorer","description":desc.split('\n\n')[0].replace('\n',' '),"parent_path":parent,"serialized_space":json.dumps(space)}))
