from openai import OpenAI
from pydantic import BaseModel
from typing import Optional, Literal, List
from time import sleep
import json
from argparse import ArgumentParser
import re
from os import environ
from modelHistory import History
from openai_etc import openai_get_apikey

class Config(BaseModel):
    wait_time: int = 5
    truncation_strategy: dict

def start_test(client,
               history: History,
               config: Config
               ) -> None:
    result = []
    end_status = [
        "completed",
        "incomplete",
    ]
    thread_id = client.beta.threads.create()
    for mi in history.history:
        if mi.role != "user":
            # append assistant's text.
            result.append(mi.model_dump())
            continue
        # submit user's text.
        thread_message = client.beta.threads.messages.create(
            thread_id=thread_id.id,
            role=mi.role,
            content=mi.text,
        )
        print(mi.role, mi.text)
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id.id,
            assistant_id=history.assistant_id,
            truncation_strategy=config.truncation_strategy,
        )
        while True:
            retrieved_run = client.beta.threads.runs.retrieve(
                thread_id=thread_id.id,
                run_id=run.id
            )
            print(f"STATUS: {retrieved_run}")
            print(f"{retrieved_run.status}")

            if retrieved_run.status in end_status:
                messages = client.beta.threads.messages.list(
                        thread_id=thread_id.id)
                response_text = messages.data[0].content[0].text.value
                print("assistant", response_text)
                result.append({
                        "role": "user",
                        "text": mi.text,
                        "response": response_text,
                        })
                break
            sleep(1)
        sleep(config.wait_time)
    return result

#
# main
#
ap = ArgumentParser()
ap.add_argument("-i", help="specify a history file.",
                dest="history_file", required=True)
ap.add_argument("-o", help="specify a result file.",
                dest="result_file", required=True)
ap.add_argument("-k", help="specify APIKEY file.",
                dest="apikey_storage")
ap.add_argument("-s", help="truncation strategy id.",
                dest="ts_id", default="last10")
ap.add_argument("-w", help="specify a number of waiting time in second.",
                dest="wait_time", type=int, default=30)
ap.add_argument("-v", help="set verbose mode.",
                action="store_true", dest="verbose")
opt = ap.parse_args()

if opt.history_file:
    js = json.load(open(opt.history_file, encoding="utf-8"))
    history = History.model_validate(js)
    config = Config(
            wait_time = opt.wait_time,
            truncation_strategy = {
                    "auto": {
                        "type": "auto",
                        "last_messages": None,
                    },
                    "last10": {
                        "type": "last_messages",
                        "last_messages": 10,
                    }
                }[opt.ts_id]
            )
    owa_client = OpenAI(api_key=openai_get_apikey(opt.apikey_storage))
    result = start_test(owa_client, history, config)
    if opt.result_file:
        json.dump(result, open(opt.result_file, "w", encoding="utf-8"),
                  ensure_ascii=False)
