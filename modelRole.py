# modelRole.py
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError
import io
import os
from datetime import datetime, timedelta
import random
import argparse
import asyncio
from chatconf import ChatConfigModel, set_config
from typing import List

class PatientRoleProvider:
    """
    Google Drive上のExcelファイルから患者のロール設定を非同期で読み込み、AI用のプロンプトを生成する。
    設定はChatConfigModelオブジェクトから取得する。
    """
    def __init__(self, config: ChatConfigModel):
        if not config.gdrive_file_id:
            raise ValueError("設定にGoogle DriveのファイルID(gdrive_file_id)が指定されていません。")
        if not os.path.exists(config.gdrive_service_account):
            raise FileNotFoundError(f"サービスアカウントのキーファイルが見つかりません: {config.gdrive_service_account}")

        self.config = config
        self.sheet_name = 2
        self.cache_etag_file = "cache_etag.txt"
        self.cache_data_file = "cached_data.pkl"
        self.df = None
        self.loop = config.loop # アプリケーションとイベントループを共有する

        scope = ["https://www.googleapis.com/auth/drive.readonly"]
        self.creds = Credentials.from_service_account_file(self.config.gdrive_service_account, scopes=scope)
        self.drive_service = build("drive", "v3", credentials=self.creds)
        
        self.target_columns = [
            "ID", "氏名", "年齢", "生年月日", "性別", "変換後都道府県", "プロフィール",
            "感染日", "発症日",
            datetime(2022, 4, 2), datetime(2022, 4, 3), datetime(2022, 4, 4),
            datetime(2022, 4, 5), datetime(2022, 4, 6), datetime(2022, 4, 7),
            datetime(2022, 4, 8), datetime(2022, 4, 9), datetime(2022, 4, 10),
            datetime(2022, 4, 11), datetime(2022, 4, 12), datetime(2022, 4, 13),
            datetime(2022, 4, 14), datetime(2022, 4, 15), datetime(2022, 4, 16),
            datetime(2022, 4, 17), datetime(2022, 4, 18), datetime(2022, 4, 19),
            datetime(2022, 4, 20), datetime(2022, 4, 21), datetime(2022, 4, 22),
            datetime(2022, 4, 23), datetime(2022, 4, 24), datetime(2022, 4, 25),
            datetime(2022, 4, 26), datetime(2022, 4, 27), datetime(2022, 4, 28),
            datetime(2022, 4, 29), datetime(2022, 4, 30),
            '（旅行有の場合）旅行先が流行地か否か、旅行の目的等', '備考欄', '都道府県'
        ]

    async def _get_file_etag(self):
        try:
            file_metadata = await self.loop.run_in_executor(
                None, lambda: self.drive_service.files().get(fileId=self.config.gdrive_file_id, fields="md5Checksum").execute()
            )
            return file_metadata.get("md5Checksum")
        except HttpError as e:
            print(f"ETagの取得エラー: {e}")
            return None

    async def _download_and_read_excel(self):
        try:
            request = self.drive_service.files().get_media(fileId=self.config.gdrive_file_id)
            file_stream = io.BytesIO()
            downloader = MediaIoBaseDownload(file_stream, request)
            done = False
            while not done:
                status, done = await self.loop.run_in_executor(None, downloader.next_chunk)
            file_stream.seek(0)
            return pd.read_excel(file_stream, sheet_name=self.sheet_name)
        except HttpError as e:
            print(f"ファイルのダウンロードエラー: {e}")
            return None
        except ValueError as e:
            print(f"シート '{self.sheet_name}' の読み込みエラー: {e}")
            return None

    async def initialize(self):
        current_etag = await self._get_file_etag()
        
        cached_etag = None
        if os.path.exists(self.cache_etag_file):
            with open(self.cache_etag_file, "r") as f:
                cached_etag = f.read().strip()

        if current_etag and current_etag == cached_etag and os.path.exists(self.cache_data_file):
            self.df = pd.read_pickle(self.cache_data_file)
            return

        df = await self._download_and_read_excel()
        if df is not None:
            self.df = df
            if current_etag:
                df.to_pickle(self.cache_data_file)
                with open(self.cache_etag_file, "w") as f:
                    f.write(current_etag)

    def _get_column_indices(self):
        return {col: self.df.columns.tolist().index(col) if col in self.df.columns else -1 for col in self.target_columns}

    def _determine_interview_date(self, onset_date_str: str) -> (datetime, str):
        """発症日に基づいて調査日と時間帯を確率的に決定する"""
        try:
            onset_date = pd.to_datetime(onset_date_str)
        except (ValueError, TypeError):
            onset_date = datetime.now()

        rand_val = random.random()
        if rand_val < 0.5:
            return onset_date, "（PM・夜間）"
        elif rand_val < 0.9:
            return onset_date + timedelta(days=1), ""
        else:
            return onset_date + timedelta(days=2), ""

    def get_patient_prompt_chunks(self, patient_id: str) -> (List[str], str):
        """
        指定された患者IDのプロンプトを、API制限を考慮して分割されたチャンクのリストとして返す。
        """
        if self.df is None:
            raise RuntimeError("Provider is not initialized. Call `await provider.initialize()` first.")

        column_indices = self._get_column_indices()
        if column_indices.get("ID", -1) == -1:
            return ["エラー: 'ID'カラムが見つかりません。"]

        try:
            row_list = self.df.values.tolist()
            row = next(filter(lambda r: int(r[column_indices["ID"]]) == int(patient_id), row_list))
        except (StopIteration, ValueError):
            return [f"患者ID {patient_id} のデータは見つかりませんでした。"], None
        except Exception as e:
            return [f"検索中に予期せぬエラーが発生しました: {e}"], None

        # 調査日を決定
        onsetDate_idx = column_indices.get("発症日", -1)
        onsetDate_str = row[onsetDate_idx] if onsetDate_idx != -1 and pd.notna(row[onsetDate_idx]) else None
        interview_date, time_of_day = self._determine_interview_date(onsetDate_str)
        
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        weekday_str = weekdays[interview_date.weekday()]
        interview_date_str = interview_date.strftime("%Y年%m月%d日") + f"（{weekday_str}曜日）" + time_of_day

        chunks = []
        
        # --- チャンク1: 基本情報と指示 ---
        base_prompt = f"本日は{interview_date_str}です。\n"
        base_prompt += "以下に示す情報は全て、あなたに関する設定です。\n"
        base_prompt += "これらの設定を忠実に守り、役になりきって応答してください。\n"
        base_prompt += "具体的に質問されていることだけに答えてください。\n"
        base_prompt += "短く簡潔に回答し、最長でも100文字以内で解答してください。\n\n"

        base_info = ""
        for column_label, column_index in column_indices.items():
            if not isinstance(column_label, datetime) and column_index != -1:
                value = row[column_index]
                if pd.notna(value):
                    value_str = str(value).strip()
                    if value_str:
                        base_info += f'{column_label}: {value_str}\n'

        chunks.append(base_prompt + base_info)

        # --- チャンク2以降: 日ごとの行動履歴（調査日以前の情報のみ） ---
        for column_label, column_index in column_indices.items():
            if isinstance(column_label, datetime) and column_index != -1:
                # 調査日より後の情報は含めない
                if column_label.date() > interview_date.date():
                    continue
                
                value = row[column_index]
                if pd.notna(value):
                    date_str = column_label.strftime("%Y-%m-%d")
                    value_str = str(value).strip()
                    if value_str:
                        chunks.append(f"【{date_str}の行動履歴】\n{value_str}")

        return chunks, interview_date_str

    def get_patient_details(self, patient_id: str) -> dict:
        """
        指定された患者IDの詳細情報を辞書として返す。UI表示用。
        """
        if self.df is None:
            raise RuntimeError("Provider is not initialized.")

        column_indices = self._get_column_indices()
        if column_indices.get("ID", -1) == -1:
            return {"error": "ID column not found."}

        try:
            row_list = self.df.values.tolist()
            row = next(filter(lambda r: str(int(r[column_indices["ID"]])) == str(patient_id), row_list))
        except (StopIteration, ValueError):
            return {"error": f"Patient ID {patient_id} not found."}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {e}"}

        details = {}
        # mock.jsxの項目に合わせてデータを抽出・整形
        def get_value(col_name, default='N/A'):
            idx = column_indices.get(col_name, -1)
            if idx != -1 and pd.notna(row[idx]):
                return row[idx]
            return default

        details['id'] = get_value('ID', 'N/A')
        details['name'] = get_value('氏名')
        age_val = get_value('年齢', None)
        details['age'] = int(age_val) if age_val is not None else 'N/A'
        details['gender'] = get_value('性別')
        details['residence'] = get_value('変換後都道府県')
        birthDate = get_value('生年月日', None)
        details['birthDate'] = pd.to_datetime(birthDate).strftime('%Y年%m月%d日') if birthDate else '不明'
        
        onsetDate = get_value('発症日', None)
        details['onsetDate'] = pd.to_datetime(onsetDate).strftime('%Y年%m月%d日') if onsetDate else '不明'
        infectionDate = get_value('感染日', None)
        details['infectionDate'] = pd.to_datetime(infectionDate).strftime('%Y年%m月%d日') if infectionDate else '不明'
        
        details['symptoms'] = get_value('プロフィール', '情報なし')
        
        details['profile'] = get_value('プロフィール', '情報なし')
        details['notes'] = get_value('備考欄', '特になし')

        return details

    def get_available_patient_ids(self) -> list[str]:
        if self.df is None:
            raise RuntimeError("Provider is not initialized. Call `await provider.initialize()` first.")

        status_col = "作業ステータス"
        id_col = "ID"

        if status_col not in self.df.columns or id_col not in self.df.columns:
            print(f"必要なカラム '{status_col}' または '{id_col}' が見つかりません。")
            return []

        try:
            completed_df = self.df[self.df[status_col] == '完了']
            # 整数に変換してから文字列に変換することで、小数点以下を削除
            available_ids = completed_df[id_col].dropna().astype(float).astype(int).astype(str).unique().tolist()
            return available_ids
        except Exception as e:
            print(f"IDリストのフィルタリング中にエラーが発生しました: {e}")
            return []

async def main():
    parser = argparse.ArgumentParser(description="患者AIのプロンプトを生成します。")
    parser.add_argument("config_file", help="conf.jsonなどの設定ファイル")
    parser.add_argument("patient_id", help="対象の患者ID")
    
    args = parser.parse_args()

    try:
        config = set_config("test_modelRole", asyncio.get_event_loop(), [args.config_file])
        
        provider = PatientRoleProvider(config=config)
        print("Initializing and loading data...")
        await provider.initialize()
        print("Data loaded.")
        
        prompt_chunks = provider.get_patient_prompt_chunks(args.patient_id)
        print("\n--- Generated Prompt Chunks ---")
        for i, chunk in enumerate(prompt_chunks):
            print(f"--- Chunk {i+1} ---")
            print(chunk)
        print("------------------------\n")

    except (ValueError, FileNotFoundError) as e:
        print(f"エラー: {e}")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
