OpenAI対応RISTEXチャットサーバ
==============================

ristex-chatserver

##

```
python retry_request.py -k apikey.txt -i chat_history_056-20241019.json -o chat_history_056-20241019-retry01.json
```

```
python retry_check_result.py  chat_history_056-20241019-retry01.json
```

## TODO

## requirement

openai
fastapi
aiofiles
