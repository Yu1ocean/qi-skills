import json, sys

text = sys.stdin.read()
start = text.find('{')
if start == -1:
    raise SystemExit('NO_JSON_FOUND')
obj = json.loads(text[start:])
json.dump(obj, sys.stdout, ensure_ascii=False)
