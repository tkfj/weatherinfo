import re
import os

import requests
import bs4
import prettytable

import dotenv

dotenv.load_dotenv()

url = os.environ['TENKIJP_3H_URL']
slack_token = os.environ['SLACK_TOKEN']
slack_ch_nm = os.environ['SLACK_CH_NM']


response = requests.get(url)
html = response.text
# print(html)

soup = bs4.BeautifulSoup(html, "html.parser")
title = soup.find("h1").text
# print(title)

def trim_full(string:str)->str:
    if string is None:
        return None
    string=re.sub(r'^\s+','',string,flags=re.DOTALL)
    string=re.sub(r'\s+$','',string,flags=re.DOTALL)
    return string


def parse_one_day(tbl_elem_day:bs4.Tag):
    zzs=[]
    for _i, _tr1 in enumerate(tbl_elem_day.find_all('tr')):
        thk=None
        for _j, _th1 in enumerate(_tr1.find_all('th')):
            # print(f'  {_j+1}::')
            # pprint(_th1)
            # _tx=_tr1.text.replace('\n',' ')
            _tx=trim_full(_th1.text)
            # print(_tx)
            if _ma_d := re.search('日付',_tx,flags=re.DOTALL):
                thk='日付'
            elif _ma_d := re.search('時刻',_tx,flags=re.DOTALL):
                thk='時刻'
            elif _ma_d := re.search('天気',_tx,flags=re.DOTALL):
                thk='天気'
            else:
                thk=_th1.text
        tdv=[]
        for _j, _td1 in enumerate(_tr1.find_all('td')):
            # remove all 'div class=canvas-container' tag
            # 描画方法に関する指示がテキストで入るので(過ぎた時間の指定とか)
            for _scr in _td1.find_all('div', class_='canvas-container'):
                _scr.decompose()
            # print(f'{_j+1}::')
            # pprint(_td1)
            # _tx=_tr1.text.replace('\n',' ')
            _tx=trim_full(_td1.text)
            # print(_tx)
            if thk=='日付':
                if _ma_d := re.search(r'(今日|明日|明後日)\s*(\d+)\s*月\s*(\d+)\s*日\s*\(\s*([月火水木金土日])\s*\)',_tx,flags=re.DOTALL):
                    # pprint(_ma_d)
                    tdv.append(_ma_d.group(1))
                    tdv.append(_ma_d.group(2))
                    tdv.append(_ma_d.group(3))
                    tdv.append(_ma_d.group(4))
            else:
                tdv.append(_tx)
        zzs.append((thk,tdv,))
    pprint(zzs)
    _lk=None
    _lv=None
    _kv=dict()
    for _k, _v in zzs:
        if _k is None:
            if _lk is not None:
                if _lk=='時刻':
                    _kv[_lk]=_v
                elif _lk[:2]=='気温':
                    _kv[_lk]=_v
                elif _lk[:3]=='降水量':
                    _kv[_lk]=_v
        else:
            _kv[_k]=_v
        if _k is not None:
            _lk=_k
    return _kv

from pprint import pprint



tag_time=soup.find('time', class_='date-time')
announce_datetime_str=trim_full(tag_time.text)

tag_tbl_day1=soup.find('table', id='forecast-point-3h-today')
kv1=parse_one_day(tag_tbl_day1)
tag_tbl_day2=soup.find('table', id='forecast-point-3h-tomorrow')
kv2=parse_one_day(tag_tbl_day2)
tag_tbl_day3=soup.find('table', id='forecast-point-3h-dayaftertomorrow')
kv3=parse_one_day(tag_tbl_day3)

kvss=[kv1,kv2,kv3,]
pt = prettytable.PrettyTable()
pt.border = False
pt.preserve_internal_border = True
pt.field_names = ["Time", "Weather", "Temp.", "RH", "Rainfall", "Wind"]
pt.align['Time']='l'
pt.align['Werather']='l'
pt.align['temp.']='l'
pt.align['RH']='l'
pt.align['Rainfall']='l'
pt.align['Wind']='l'

print(announce_datetime_str)
text_slacks_ar=[f'天気予報:{announce_datetime_str} <{url} | tenki.jp >']
for kvs in kvss:
    if kvs["日付"][0] != '今日':
        continue
    if len(kvs['時刻'])>0:
        text_slacks_ar.append(f'{kvs["日付"][0]} {kvs["日付"][1]}月{kvs["日付"][2]}日({kvs["日付"][3]})')
    for _i ,_t in enumerate(kvs['時刻']):
        hour=kvs["時刻"][_i]
        hour_slack=f'{int(hour):2.0f}時'
        we_slack='　'
        we=kvs["天気"][_i]
        if we=='晴れ':
            # we_slack=':sunny:'
            we_slack='🔆'
        elif we=='曇り':
            # we_slack=':cloud:'
            we_slack='☁'
        elif we=='小雨':#1ミリの未満
            # we_slack=':closed_unbrella:'
            we_slack='🌂'
        elif we=='弱雨':#1ミリ以上 3ミリ未満の雨
            # we_slack=':unbrella:'
            we_slack='☂'
        elif we=='雨': #3ミリ以上の雨
            # we_slack=':unbrella_with_rain_drops:'
            we_slack='☔'
        # elif we=='みぞれ':#降水量関係なさそう ★いいアイコンがないのでいったんそのまま
        #     we_slack=':unbrella_with_rain_drops:'
        elif we=='湿雪':
            we_slack=':snowman:'
            we_slack='⛄'
        elif we=='乾雪':
            # we_slack=':snowman:'
            we_slack='⛄'
        elif we=='雪': #たぶんない
            # we_slack=':snowman:'
            we_slack='⛄'
        elif we=='雹': #？事前に予想されることある？？？？
            # we_slack=':snowman:'
            we_slack='⛄'
        else:
            we_slack=we
        atmp=kvs["気温(℃)"][_i]
        atmp_slack=f'{float(atmp):4.1f}°C' # 符号＋整数2＋小数で４
        rainfaill=kvs["降水量(mm/h)"][_i]
        rainfaill_slack=f'{int(rainfaill):2.0f}mm'
        chre=kvs["降水確率(%)"][_i]
        if chre=='---':
            chre_slack='    '
        else:
            chre_slack=f'{int(chre):3.0f}%'
        hmd=kvs["湿度(%)"][_i]
        hmd_slack=f'{int(hmd):3.0f}%'
        wnd_spd=kvs["風速(m/s)"][_i]
        wnd_spd_slack=f'{int(wnd_spd):2.0f}m'
        wnd_dir=kvs["風向"][_i]
        wnd_dir_slack=f'{wnd_dir.replace("北","N").replace("南","S").replace("東","E").replace("西","W"): >3}' #なんで英語にしてんの→文字数の計算
        pt.add_row([
            hour_slack,
            f'{we_slack} {we}',
            f'{atmp_slack}',
            hmd_slack,
            f'{chre_slack} {rainfaill_slack}',
            f'{wnd_dir_slack} {wnd_spd_slack}'
        ])
text_slacks_ar.append('```')
text_slacks_ar.append(pt.get_string())
text_slacks_ar.append('```')
text_slack='\n'.join(text_slacks_ar)

# with open('./hoge.txt', mode='w') as outf:
#     outf.write(html)

import slack_sdk

slack_cli = slack_sdk.WebClient(token=slack_token)

try:
    resp_a = slack_cli.auth_test()
    slack_bot_user_id = resp_a["user_id"]
    print("BotのユーザーID:", slack_bot_user_id)

    resp_C=slack_cli.conversations_list()
    for channel in resp_C["channels"]:
        if f'#{channel["name"]}'==slack_ch_nm:
            slack_ch_id = channel['id']
            break
    else:
        raise ValueError('チャンネルIDを特定できない')
    response = slack_cli.chat_postMessage(
        channel=slack_ch_id,
        text=text_slack
    )
    post_ts=response["ts"]
    print("送信成功！メッセージID:", post_ts)
    resp_h = slack_cli.conversations_history(
        channel=slack_ch_id,
        limit=10  # 最新10件
    )
    messages = resp_h["messages"]

    for msg in messages:
        # pprint(msg)
        text = msg.get("text", "")
        user = msg.get("user", "system/unknown")
        ts = msg.get("ts")
        # print(f"{i}. ユーザー: {user}, 時間: {ts}, メッセージ: {text}")
        if ts >= post_ts:
            continue
        if user != slack_bot_user_id:
            continue
        if text[:5] != "天気予報:":
            continue
        resp_d = slack_cli.chat_delete(
            channel=slack_ch_id,
            ts=ts
        )
        print(f'メッセージ削除成功: {ts} :{resp_d["ok"]}')
         

except slack_sdk.SlackApiError as e:
    print("APIエラー:", e.response["error"])

