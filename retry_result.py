from argparse import ArgumentParser
import json

ap = ArgumentParser()
ap.add_argument("result_file", help="1st item.")
opt = ap.parse_args()

js = json.load(open(opt.result_file, encoding="utf-8"))
for i,m in enumerate(js):
    if m["role"] == "user":
        print("## user")
        print(m["text"])
    elif m["role"] == "assistant":
        print("- assistant(original)")
        print(m["text"])
        print("- assistant(result)")
        print(js[i-1]["response"])
