OpenAI対応RISTEXチャットサーバ
==============================

某プロジェクトのOpenAI Assistantフロントエンドとチャットサーバ

## 全体概要

![アーキテクチャ概略図](doc/arch01.png)

いまここ↓
![アーキテクチャ概略図](doc/v01.png)

## チャットサーバ

- 起動方法

```
python retry_request.py -k apikey.txt -i chat_history_056-20241019.json -o chat_history_056-20241019-retry01.json
```

## チャット履歴

```
python retry_check_result.py  chat_history_056-20241019-retry01.json
```

## TODO
- AI質問者の実装

## requirement

openai
fastapi
aiofiles
