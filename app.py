import os, csv, random, json, time, glob
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, make_response
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.config['SECRET_KEY'] = 'denken-v2-1-strict-logic'

# 日本時間設定
JST = timezone(timedelta(hours=9))

def get_jst_now():
    return datetime.now(JST)

# CSVファイルを保存しているルートディレクトリ
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_BASE_DIR = os.path.join(BASE_DIR, "logic", "csv_data")

def get_storage(request):
    """Cookieからデータを取得。"""
    data = request.cookies.get('denken_storage')
    storage = {"wrong_list": [], "logs": []}
    if data:
        try: storage = json.loads(data)
        except: pass
    return storage

TARGET_CATEGORIES = [
    "理論", "直流機", "誘導機", "同期機", "変圧器", 
    "四機総合問題", "電動機応用", "電気機器", "パワーエレクトロニクス", 
    "自動制御", "照明", "電熱", "電気化学", "メカトロニクス", "情報伝送及び処理"
]

def load_csv_data(mode):
    """CSVを再帰スキャンして読み込み。"""
    folder_mode = 'taku4' if mode == 'fill' else 'normal'
    search_path = os.path.join(CSV_BASE_DIR, folder_mode, "**", "*.csv")
    files = glob.glob(search_path, recursive=True)
    
    questions = []
    for f_path in files:
        try:
            with open(f_path, encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if len(row) >= 3:
                        dummies = []
                        if mode == 'fill':
                            raw_dummies = row[4:7] if len(row) >= 7 else []
                            dummies = [d.strip() for d in raw_dummies if d.strip()]
                        questions.append({
                            'id': f"{mode}_{os.path.basename(f_path)}_{i}", 
                            'category': row[0].strip(), 
                            'front': row[1].strip(), 
                            'back': row[2].strip(), # "正解" または "不正解" が入る
                            'note': row[3].strip() if len(row) > 3 else "",
                            'dummies': dummies
                        })
        except: pass
    return questions

@app.route('/')
def index():
    storage = get_storage(request)
    wrong_count = len(storage.get('wrong_list', []))
    now_jst = get_jst_now()
    selected_cat = request.args.get('chart_cat', 'すべて')
    logs = storage.get('logs', [])
    
    chart_labels, chart_values = [], []
    for i in range(6, -1, -1):
        d_str = (now_jst - timedelta(days=i)).strftime('%m/%d')
        chart_labels.append(d_str)
        day_logs = [l for l in logs if l.get('date') == d_str and (selected_cat == 'すべて' or l.get('cat') == selected_cat)]
        if day_logs:
            acc = sum(1 for l in day_logs if l.get('correct')) / len(day_logs) * 100
            chart_values.append(round(acc, 1))
        else: chart_values.append(0)
            
    days_left = max(0, (datetime(2026, 3, 22, tzinfo=JST) - now_jst).days)
    return render_template('index.html', categories=TARGET_CATEGORIES, days_left=days_left, 
                           wrong_count=wrong_count, labels=chart_labels, values=chart_values, selected_cat=selected_cat)

@app.route('/start_study', methods=['POST'])
def start_study():
    mode = request.form.get('mode', 'fill')
    cat = request.form.get('cat', 'すべて')
    q_count = int(request.form.get('q_count', 10))
    is_review = request.form.get('review') == 'true'
    storage = get_storage(request)
    
    if is_review:
        all_q = load_csv_data('fill') + load_csv_data('ox')
        all_q = [q for q in all_q if q['id'] in storage['wrong_list']]
    else:
        all_q = load_csv_data(mode)
    
    if cat != 'すべて':
        all_q = [q for q in all_q if q['category'] == cat]

    if not all_q: return redirect(url_for('index'))
    selected_qs = random.sample(all_q, min(len(all_q), q_count))
    session['quiz_queue'], session['total_in_session'], session['correct_count'] = selected_qs, len(selected_qs), 0
    return redirect(url_for('study'))

@app.route('/study')
def study():
    if not session.get('quiz_queue'): return redirect(url_for('show_result'))
    card = session['quiz_queue'][0]
    mode = 'fill' if card['id'].startswith('fill') else 'ox'
    display_q, choices = card['front'], []
    if mode == 'fill':
        if card['back'] in card['front']: display_q = card['front'].replace(card['back'], " 【 ？ 】 ")
        choices = random.sample([card['back']] + card['dummies'], 4)
    idx = session['total_in_session'] - len(session['quiz_queue']) + 1
    return render_template('study.html', card=card, display_q=display_q, choices=choices, 
                           mode=mode, progress=int(((idx-1)/session['total_in_session'])*100), 
                           current=idx, total=session['total_in_session'])

@app.route('/answer/<card_id>', methods=['POST'])
def answer(card_id):
    if not session.get('quiz_queue'): return redirect(url_for('index'))
    card = session['quiz_queue'][0]
    storage = get_storage(request)
    user_answer = request.form.get('user_answer')
    is_correct = (user_answer == card['back']) # 厳格判定
    
    if is_correct:
        session['correct_count'] += 1
        if card_id in storage['wrong_list']: storage['wrong_list'].remove(card_id)
    else:
        if card_id not in storage['wrong_list']: storage['wrong_list'].append(card_id)
    
    storage['logs'].append({'date': get_jst_now().strftime('%m/%d'), 'cat': card['category'], 'correct': is_correct})
    storage['logs'] = storage['logs'][-1000:]
    session['quiz_queue'].pop(0)
    session.modified = True 
    
    resp = make_response(render_template('study.html', card=card, display_q=card['front'], is_answered=True, 
                                         is_correct=is_correct, mode='fill' if card['id'].startswith('fill') else 'ox', 
                                         current=session['total_in_session'] - len(session['quiz_queue']), 
                                         total=session['total_in_session'], progress=100))
    resp.set_cookie('denken_storage', json.dumps(storage), max_age=60*60*24*365)
    return resp

@app.route('/result')
def show_result():
    t, c = session.get('total_in_session', 0), session.get('correct_count', 0)
    return render_template('result.html', score=int((c/t)*100) if t > 0 else 0, total=t, correct=c)

@app.route('/home')
def go_home():
    session.pop('quiz_queue', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))