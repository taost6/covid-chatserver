from argparse import ArgumentParser
import json

ap = ArgumentParser()
ap.add_argument("result_files", nargs="*", help="result files.")
opt = ap.parse_args()

result = []
for file in opt.result_files:
    js = json.load(open(file, encoding="utf-8"))
    n = 0
    d = {}
    for i,m in enumerate(js):
        if m["role"] == "user":
            d["id"] = n
            d["user"] = m["text"]
        elif m["role"] == "assistant":
            d["original"] = m["text"]
            d["response"] = js[i-1]["response"]
            result.append(d)
            d = {}
