import json

d = json.load(open("logs/scanned_test_response.json", encoding="utf-8-sig"))
print("decision:", d.get("decision"))
print("reason:", d.get("reason"))
print()
print("extraction:", json.dumps(d.get("invoice_extraction"), indent=2))
print()
print("checks:")
for k, v in (d.get("checks") or {}).items():
    print(f" - {k}: {v['status']} -- {v['reason']}")
print()
print("audit steps:")
for s in (d.get("audit") or {}).get("processing_steps", []):
    print(" -", s)
