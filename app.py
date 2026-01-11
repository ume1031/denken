import os
import csv
import random
import json
import time
import glob
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, make_response
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.config['SECRET_KEY'] = 'denken-v2-1-full-logic-recovery-stable'

# ==========================================
# システム設定 & ユーティリティ
# ==========================================

# 日本時間設定 (JST)
JST = timezone(timedelta(hours=9))

def get_jst_now():
    """現在の日本時間を取得する。グラフの集計やログ記録に使用。"""
    return datetime.now(JST)

# CSVファイルを保存しているルートディレクトリの定義
# ディレクトリ構造: logic/csv_data/taku4/分野名/*.csv
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_BASE_DIR = os.path.join(BASE_DIR, "logic", "csv_data")

def get_storage(request):
    """
    Cookieからユーザーデータを取得。
    KeyErrorを防止し、データが壊れている場合は空のリストで初期化する。
    また、Cookieのサイズ制限（Header Too Large）を回避するため、
    蓄積されたログが100件を超える場合は、古いものから自動的に切り詰める処理を行う。
    """
    storage_str = request.cookies.get('denken_storage')
    storage = {"wrong_list": [], "logs": []}
    
    if storage_str:
        try:
            storage = json.loads(storage_str)
        except Exception as e:
            print(f"Cookie Load Error: {e}")
            storage = {"wrong_list": [], "logs": []}
    
    # データ構造の整合性チェック
    if not isinstance(storage, dict):
        storage = {"wrong_list": [], "logs": []}
    
    # 必須キーの存在とデータ型の保証（KeyError対策）
    if 'wrong_list' not in storage or not isinstance(storage['wrong_list'], list):
        storage['wrong_list'] = []
    if 'logs' not in storage or not isinstance(storage['logs'], list):
        storage['logs'] = []
    
    # 蓄積されたログが多すぎる場合は最新100件に制限する（安定動作のための制約）
    if len(storage['logs']) > 100:
        storage['logs'] = storage['logs'][-100:]
        
    return storage

# 全分野の定義（理論 ＋ 機械配下の全サブカテゴリを網羅）
ALL_CATEGORIES = [
    "理論", "直流機", "誘導機", "同期機", "変圧器", "四機総合問題", "電動機応用", 
    "電気機器", "パワーエレクトロニクス", "自動制御", "照明", "電熱", 
    "電気化学", "メカトロニクス", "情報伝送及び処理"
]

# ==========================================
# データ読み込みロジック
# ==========================================

def load_csv_data(mode):
    """
    CSVファイルを再帰的に読み込む。
    mode: 'fill' (穴埋め/4択) または 'ox' (○×)
    """
    folder_mode = 'taku4' if mode == 'fill' else 'normal'
    search_path = os.path.join(CSV_BASE_DIR, folder_mode, "**", "*.csv")
    files = glob.glob(search_path, recursive=True)
    
    questions = []
    for f_path in files:
        f_name = os.path.basename(f_path)
        try:
            # Shift-JISやUTF-8(BOMあり)を考慮しつつ読み込み
            with open(f_path, encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    # 最低限 分野, 問題文, 解答 が必要
                    if len(row) >= 3:
                        cleaned_row = [str(cell).strip().replace('\r', '').replace('\n', '') for cell in row]
                        short_f_name = f_name.replace('.csv', '').replace('ox_', '').replace('normal_', '')
                        # IDのユニーク性を確保
                        q_id = f"{mode[:1]}_{short_f_name}_{i}" 

                        dummies = []
                        if mode == 'fill':
                            # 5列目以降にダミー選択肢がある場合、それを取得
                            raw_dummies = cleaned_row[4:7] if len(cleaned_row) >= 5 else []
                            # 空白や正解と同じものは排除
                            dummies = [d for d in raw_dummies if d and d != cleaned_row[2]]

                        questions.append({
                            'id': q_id, 
                            'category': cleaned_row[0], 
                            'front': cleaned_row[1], 
                            'back': cleaned_row[2], 
                            'note': cleaned_row[3] if len(cleaned_row) > 3 else "解説はありません。",
                            'dummies': dummies
                        })
        except Exception as e:
            print(f"Critical CSV Read Error ({f_path}): {e}")
            
    return questions

# ==========================================
# ルーティング
# ==========================================

@app.route('/')
def index():
    """
    メインメニューの表示。
    学習履歴からグラフデータを生成し、試験までの残り日数を計算する。
    """
    storage = get_storage(request)
    wrong_count = len(storage.get('wrong_list', []))
    now_jst = get_jst_now()
    
    # グラフ描画用の設定
    selected_cat = request.args.get('chart_cat', 'すべて')
    logs = storage.get('logs', [])
    
    chart_labels = []
    chart_values = []
    
    # 直近7日間のデータを集計
    for i in range(6, -1, -1):
        d_obj = now_jst - timedelta(days=i)
        d_str = d_obj.strftime('%m/%d')
        chart_labels.append(d_str)
        # 特定の分野、または「すべて」の回答数をカウント
        day_logs = [l for l in logs if l.get('date') == d_str and (selected_cat == 'すべて' or l.get('cat') == selected_cat)]
        chart_values.append(len(day_logs))
            
    # 試験日カウントダウン (2026年3月22日)
    exam_date = datetime(2026, 3, 22, tzinfo=JST)
    diff = exam_date - now_jst
    days_left = max(0, diff.days)
    
    chart_title = f"{selected_cat}の学習問題数"
    
    return render_template('index.html', 
                           categories=ALL_CATEGORIES, 
                           days_left=days_left, 
                           wrong_count=wrong_count,
                           labels=chart_labels,
                           values=chart_values,
                           selected_cat=selected_cat,
                           chart_title=chart_title)

@app.route('/start_study', methods=['POST'])
def start_study():
    """
    学習セッションの初期化。
    選択された分野、形式、問題数に応じてクイズリストを作成し、セッションに保存する。
    """
    session.clear() 
    mode = request.form.get('mode', 'fill')
    cat = request.form.get('cat', 'すべて')
    
    try:
        q_count = int(request.form.get('q_count', '10'))
    except (ValueError, TypeError):
        q_count = 10
    
    is_review = (request.form.get('review') == 'true')
    storage = get_storage(request)
    
    if is_review:
        # 復習モード：Cookieにある間違えたIDリストに合致する問題を抽出
        wrong_ids = storage.get('wrong_list', [])
        # すべてのCSVからデータをロードしてフィルタリング
        all_q = load_csv_data('fill') + load_csv_data('ox')
        all_q = [q for q in all_q if q['id'] in wrong_ids]
    else:
        # 通常モード：指定されたモードと分野で抽出
        all_q = load_csv_data(mode)
        if cat != 'すべて':
            all_q = [q for q in all_q if q['category'] == cat]

    if not all_q:
        return redirect(url_for('index'))

    # シャッフルして指定の問題数だけ抽出
    random.shuffle(all_q)
    selected_qs = all_q[:q_count]
    
    # セッションにクイズ情報を保存
    session['quiz_queue'] = selected_qs
    session['total_in_session'] = len(selected_qs)
    session['correct_count'] = 0
    session.modified = True 
    
    return redirect(url_for('study'))

@app.route('/study')
def study():
    """
    学習メイン画面。
    1. 前回の回答結果がある場合は「解説画面」として表示。
    2. 次の問題がある場合は「問題画面」として表示。
    """
    # 前回の回答結果を取得
    last_result = session.get('last_result')
    
    # 全ての問題を解き終わった後の判定
    if not last_result and (not session.get('quiz_queue') or len(session.get('quiz_queue')) == 0):
        if session.get('total_in_session'):
            return redirect(url_for('show_result'))
        return redirect(url_for('index'))

    # 解説画面のレンダリング
    if last_result:
        card = last_result['card']
        current_mode = 'fill' if card['id'].startswith('f_') else 'ox'
        return render_template('study.html', 
                               card=card, 
                               display_q=card['front'],
                               is_answered=True, 
                               is_correct=last_result['is_correct'],
                               correct_answer=last_result.get('correct_answer'),
                               mode=current_mode,
                               current=last_result['current'], 
                               total=session['total_in_session'],
                               progress=last_result['progress'])

    # 新しい問題の準備
    card = session['quiz_queue'][0]
    current_mode = 'fill' if card['id'].startswith('f_') else 'ox'
    display_q = card['front']
    choices = []
    
    if current_mode == 'fill':
        # 穴埋め表示ロジック
        if card['back'] in card['front']:
            display_q = card['front'].replace(card['back'], " 【 ？ 】 ")
        
        # 選択肢の生成（確実に4つ以上にするための堅牢化）
        correct_answer = str(card['back']).strip()
        dummies = [str(d).strip() for d in card.get('dummies', []) if d and str(d).strip() != correct_answer]
        
        # 重複を排除して正解を追加
        choices = [correct_answer] + dummies
        choices = list(dict.fromkeys(choices))
        
        # 選択肢が4つに満たない場合のダミー補充
        placeholders = ["選択肢A", "選択肢B", "選択肢C", "選択肢D"]
        for p in placeholders:
            if len(choices) >= 4:
                break
            if p not in choices:
                choices.append(p)
            
        random.shuffle(choices)

    # 進捗状況の計算
    idx = session['total_in_session'] - len(session['quiz_queue']) + 1
    progress = int(((idx - 1) / session['total_in_session']) * 100)
    
    return render_template('study.html', 
                           card=card, 
                           display_q=display_q, 
                           choices=choices, 
                           mode=current_mode,
                           progress=progress, 
                           current=idx, 
                           total=session['total_in_session'],
                           is_answered=False)

@app.route('/answer/<card_id>', methods=['POST'])
def answer(card_id):
    """
    ユーザーの回答を判定し、ログとCookieを更新する。
    """
    if not session.get('quiz_queue'):
        return redirect(url_for('index'))
        
    card = session['quiz_queue'][0]
    storage = get_storage(request)
    now_jst = get_jst_now()
    
    # 回答の取得と判定
    user_answer = str(request.form.get('user_answer', '')).strip()
    correct_answer = str(card['back']).strip()
    is_correct = (user_answer == correct_answer)
    
    # 履歴更新
    if is_correct:
        session['correct_count'] += 1
        # 正解したら復習リストから削除
        storage['wrong_list'] = [i for i in storage['wrong_list'] if i != card_id]
    else:
        # 間違えたら復習リストに追加
        if card_id not in storage['wrong_list']:
            storage['wrong_list'].append(card_id)
    
    # 統計用ログの記録 (最新100件に維持)
    storage['logs'].append({
        'date': now_jst.strftime('%m/%d'), 
        'cat': card['category'], 
        'correct': is_correct
    })
    storage['logs'] = storage['logs'][-100:]
    
    # キューから現在の問題を削除
    session['quiz_queue'].pop(0)
    
    # 進捗の再計算
    idx = session['total_in_session'] - len(session['quiz_queue'])
    progress = int((idx / session['total_in_session']) * 100)
    
    # 解説画面表示用に今回の結果を一時保存
    session['last_result'] = {
        'card': card, 
        'is_correct': is_correct, 
        'correct_answer': correct_answer, 
        'current': idx, 
        'progress': progress
    }
    session.modified = True 
    
    # Cookieの更新
    storage_json = json.dumps(storage, separators=(',', ':'))
    resp = make_response(redirect(url_for('study')))
    resp.set_cookie('denken_storage', storage_json, max_age=60*60*24*365, path='/', samesite='Lax')
    return resp

@app.route('/next_question')
def next_question():
    """解説を閉じて次の問題へ進む"""
    session.pop('last_result', None)
    session.modified = True
    return redirect(url_for('study'))

@app.route('/result')
def show_result():
    """最終結果のスコア表示"""
    t = session.get('total_in_session', 0)
    c = session.get('correct_count', 0)
    score = int((c / t) * 100) if t > 0 else 0
    return render_template('result.html', score=score, total=t, correct=c)

@app.route('/home')
def go_home():
    """セッションをリセットしてホームへ戻る"""
    session.clear()
    return redirect(url_for('index'))

# ==========================================
# サーバー起動
# ==========================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    # ホスト0.0.0.0で公開。デバッグモードは本番環境に応じて変更。
    app.run(host='0.0.0.0', port=port, debug=False)