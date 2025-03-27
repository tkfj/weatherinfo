import os
import json

from pprint import pprint

import requests
import datetime
import dotenv
import slack_sdk

SP=chr(0x2002) # 1/2em幅のスペース

def load_json(url:str)->any:
    resp = requests.get(url)
    print(url)
    json_raw = resp.text
    json_obj = json.loads(json_raw)
    pprint(json_obj)
    return json_obj

dotenv.load_dotenv()

slack_token = os.environ['SLACK_TOKEN']
slack_ch_nm = os.environ['SLACK_CH_NM']

area_class10_cd = os.environ['JMA_AREA_CD'] # TOKYO 130010
area_url = 'https://www.jma.go.jp/bosai/common/const/area.json'
vpfd_url = f'https://www.jma.go.jp/bosai/jmatile/data/wdist/VPFD/{area_class10_cd}.json'
link_url = 'https://www.jma.go.jp/bosai/wdist/timeseries.html'
link_text = '気象庁 地域時系列予報'

icon_sunny_day = os.environ['ICON_SUNNY_DAY']
icon_sunny_night = os.environ['ICON_SUNNY_NIGHT']
icon_cloudy = os.environ['ICON_CLOUDY']
icon_rainy = os.environ['ICON_RAINY']
icon_snowy = os.environ['ICON_SNOWY']
icon_sleety = os.environ['ICON_SLEETY']

area_json = load_json(area_url)
vpfd_json = load_json(vpfd_url)

area_class10_json = area_json['class10s'][area_class10_cd]
area_class10_nm = area_class10_json['name']
area_office_cd = area_class10_json['parent']
area_office_json = area_json['offices'][area_office_cd]
area_office_nm= area_office_json['name']

pub_office_str=vpfd_json['publishingOffice']
rep_dt_raw_str=vpfd_json['reportDateTime']
rep_dt=datetime.datetime.fromisoformat(rep_dt_raw_str)
info_type=vpfd_json['infoType']
announce_dt_slack=f'{pub_office_str} {rep_dt.month}月{rep_dt.day}日{rep_dt.hour}時 {info_type}'
area_nm_raw=vpfd_json['pointTimeSeries']['pointNameJP'] # TODOこれはエリア名ではなく気温？ポイント名
area_nm_slack=f'{area_office_nm}{SP}{area_class10_nm}({area_nm_raw})'

print(announce_dt_slack)
last_d_slack=''
text_slacks_ar=[f'天気予報:{SP}{area_nm_slack}{SP}-{SP}{announce_dt_slack}']

# 数値の文字列の最大長を算出(符号を含めた桁数)
times_count=len(vpfd_json['areaTimeSeries']['timeDefines'])
temparetures_digits_raw=[len(f'{_x:.0f}') for _x in vpfd_json['pointTimeSeries']['temperature']]
tempareture_digits=max(temparetures_digits_raw)
wind_speeds_digits_raw=[len(f'{_x["speed"]:.0f}') for _x in vpfd_json['areaTimeSeries']['wind']]
wind_speed_digits=max(wind_speeds_digits_raw)
wind_directions_digits_raw=[len(_x["direction"]) for _x in vpfd_json['areaTimeSeries']['wind']]
wind_direction_digits=max(wind_directions_digits_raw)

for i, forecast_dt_raw in enumerate(vpfd_json['areaTimeSeries']['timeDefines']):
    forecast_dt = datetime.datetime.fromisoformat(forecast_dt_raw['dateTime'])
    forecast_d_slack=f'{forecast_dt.day:{SP}>2.0f}日'
    forecast_t_slack=f'{forecast_dt.hour:{SP}>2.0f}時'
    if forecast_d_slack==last_d_slack:
        forecast_d_slack=f'{SP}{SP}{SP}{SP}'
    else:
        last_d_slack=forecast_d_slack

    weather_str_raw=vpfd_json['areaTimeSeries']['weather'][i]

    match weather_str_raw:
        case '晴れ':
            weather_slack=f'{SP}晴れ{SP}'
            if 6 <= forecast_dt.hour < 18:
                weather_icon_slack=icon_sunny_day
            else:
                weather_icon_slack=icon_sunny_night
        case 'くもり':
            weather_slack=f'くもり'
            weather_icon_slack=icon_cloudy
        case '雨':
            weather_slack=f'{SP}{SP}雨{SP}{SP}'
            weather_icon_slack=icon_rainy
        case '雪':
            weather_slack=f'{SP}{SP}雪{SP}{SP}'
            weather_icon_slack=icon_snowy
        case '雨または雪': #民間予報ではみぞれ https://www.jma.go.jp/jma/kishou/know/yougo_hp/kousui.html によると予報分では「雨か雪」「雪か雨」と表現するが地域時系列予報では「雨または雪」固定
            weather_slack=f'みぞれ'
            weather_icon_slack=icon_sleety
        case _:
            weather_slack=weather_str_raw
            weather_icon_slack=weather_str_raw
    weather_slack=weather_str_raw
    tempareture_raw=vpfd_json['pointTimeSeries']['temperature'][i]
    tempareture_slack=f'{tempareture_raw:{SP}>{tempareture_digits}.0f}°C'
    wind_raw=vpfd_json['areaTimeSeries']['wind'][i]
    wind_direction_sp=wind_direction_digits-len(wind_raw["direction"])
    wind_direction_slack=f''
    wind_slack=f'{SP*wind_direction_sp}{wind_raw["direction"]}{SP*wind_direction_sp}{SP}{wind_raw["speed"]:{wind_speed_digits}.0f}m'# TODO 方角なしあるのかな(無風) ＃TODO 北 10mと 北西 1mがあったときに無駄にSP*2となる問題
    #TODO max/minTempretureに対応(主にUIの検討) アンダーラインオーバーラインがあれば。。。
    #TODO range(最大風速の範囲)に対応(主にUIの検討) gustってやつかな？
    # text_slacks_ar.append(f'{forecast_d_slack}{sp}{forecast_t_slack}{sp}{weather_icon_slack}{sp}{weather_slack}{sp}{tempareture_slack}{sp}{wind_slack}')
    text_slacks_ar.append(f'{forecast_d_slack}{SP}{forecast_t_slack}{SP}{weather_icon_slack}{SP}{tempareture_slack}{SP}{wind_slack}')

text_slacks_ar.append(f'from <{link_url} | {link_text} >')
text_slack='\n'.join(text_slacks_ar)

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



