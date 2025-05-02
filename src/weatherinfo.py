import os
import json

from typing import List, Tuple, Dict, Set, Any
from pprint import pprint
from collections import defaultdict

import requests
import datetime
import dotenv
import slack_sdk
import decimal
import math

_DEBUG_ADDRESS_=False
_DEBUG_STORE_IMG_=False

# SP=chr(0x2002) # 1/2em幅のスペース
SP=chr(0x2007) # 固定幅フォントの数字と同じ幅のスペース
SP_ZEN=chr(0x3000) # 「全角」のスペース
# SP_ZEN=chr(0x2003) # 1em幅のスペース
SP_NRM=chr(0x0020) # 「通常」のスペース

def load_json(url:str)->any:
    print(url)
    resp = requests.get(url)
    print(f'{resp.status_code} {resp.reason}')
    json_raw = resp.text
    json_obj = json.loads(json_raw)
    # pprint(json_obj)
    return json_obj

def parse_dt_str(dt_str:str)->datetime.datetime:
    return datetime.datetime.fromisoformat(dt_str)

def prepare_slack():
    global slack_cli
    global slack_bot_user_id
    global slack_ch_id
    if slack_cli is None:
        slack_cli = slack_sdk.WebClient(token=slack_token)
    if slack_bot_user_id is None:
        resp_a = slack_cli.auth_test()
        slack_bot_user_id = resp_a["user_id"]
    print(f'BotのユーザーID: {slack_bot_user_id}')

    if slack_ch_id is None:
        resp_C=slack_cli.conversations_list()
        for channel in resp_C["channels"]:
            if f'#{channel["name"]}'==slack_ch_nm:
                slack_ch_id = channel['id']
                break
        else:
            raise ValueError('チャンネルIDを特定できない')
    print(f'チャンネルID: {slack_ch_id}')

def send_slack_text(text: str, blocks:List[Dict[str,any]] = None, event_type: str = None, event_payload: any = None) -> float:
    msgjson={
        'channel': slack_ch_id,
        'text': text,
    }
    if blocks is not None:
        msgjson['blocks']=blocks
        pprint(blocks)
    if event_type is not None:
        assert event_payload is not None, "event_typeを指定する場合event_payloadは必須です"
        msgjson['metadata']={'event_type': event_type}
    if event_payload is not None:
        assert event_type is not None, "event_payloadを指定する場合event_typeは必須です"
        msgjson['metadata']['event_payload']=event_payload

    resp_p = slack_cli.chat_postMessage(**msgjson)
    post_ts=resp_p["ts"]
    print(f'送信成功: {post_ts}')
    return post_ts

def send_slack_images(
        files:List[bytes],
        file_names:List[str] = None,
        file_mimetypes:List[str] = None,
        file_titles:List[str] = None,
        file_alts:List[str] = None,
    ) -> Tuple[str, str]: #(file_id, url_private)
        slack_up_files:List[str, str]=list()
        for i, file in enumerate(files):
            slack_get_up_params={
                'filename': upload_fname,
                'length': len(bytes_img_up),
            }
            if file_names is not None:
                slack_get_up_params['filename'] = file_names[i]
            if file_alts is not None:
                slack_get_up_params['alt_text'] = file_alts[i]

            resp_up_info = slack_cli.files_getUploadURLExternal(**slack_get_up_params)
            print(resp_up_info)
            print(f'{resp_up_info.status_code} {resp_up_info["ok"]}')
            print(resp_up_info['upload_url'], resp_up_info['file_id'])
            slack_up_files.append({'id':resp_up_info['file_id']})
            if file_titles is not None:
                slack_up_files[i]['title'] = file_titles[i]
            slack_post_headers={
                'Content-Length': str(len(file)),
            }
            if file_mimetypes is not None:
                slack_post_headers['Content-Type'] = file_mimetypes[i]
            resp_put = requests.post(
                resp_up_info['upload_url'],
                headers = slack_post_headers,
                data = file,
            )
            print(resp_put)
            print(f'{resp_put.status_code} {resp_put.reason}')
            resp_put.raise_for_status()
        resp_compl = slack_cli.files_completeUploadExternal(
            files = slack_up_files,
            # channel_id = slack_ch_id,
        )
        print(resp_compl)
        return [(x['id'],x['url_private'],) for x in resp_compl['files']]

def delete_slack_same_titles(event_type: str, post_ts: float=None, check_limit:int = 10):
    resp_h = slack_cli.conversations_history(
        channel=slack_ch_id,
        limit=check_limit, # 直近N件以内に同じタイトルがあれば削除
        include_all_metadata=True,
    ) #TODO post_tsがあるばあい、それをlatestとして指定する
    past_messages = resp_h["messages"]

    for past_msg in past_messages:
        # print(past_msg)
        past_user = past_msg.get("user", "system/unknown")
        past_ts = past_msg.get("ts")
        # print(f"{i}. ユーザー: {user}, 時間: {ts}, メッセージ: {text}")
        #消さない条件
        if past_user != slack_bot_user_id: #ユーザーが異なる
            # print("skip: user")
            continue
        if post_ts is not None and past_ts >= post_ts: #tsが指定されていて、それと同じか新しい
            # print("skip: ts")
            continue
        if event_type is not None and past_msg.get('metadata',{}).get('event_type') != event_type: #posttypeが異なる
            # print(f"skip: event_type me: {event_type}   you: {past_msg.get('metadata',{}).get('event_type')}")
            continue
        #ここに到達したら削除対象
        #ユーザーが同一
        #ぽstTypeが一致
        #TSがあった場合、それより古い

        resp_d = slack_cli.chat_delete(
            channel=slack_ch_id,
            ts=past_ts
        )
        if resp_d["ok"]:
            print(f'メッセージ削除成功: {past_ts}')
        else:
            print(f'メッセージ削除失敗??: {past_ts}')


def send_slack(
        text:str,
        blocks:List[Dict[str,any]] = None,
        header:str = None,
        footer:str|List[Dict[str,any]] = None,
        event_type:str = None,
        event_payload:any = None,
        remove_past:int = 0,
    )->None:
    prepare_slack()
    blocks_fix:List[any] = None
    if blocks is not None and len(blocks)>0:
        blocks_fix=blocks.copy()
    else:
        blocks_fix=[
            {
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": text,
                    "emoji": True
                }
            }
        ]
    if header is not None:
        blocks_fix.insert(0, {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header,
                "emoji": True
            }
        })
    if footer is not None:
        if isinstance(footer, str):
            blocks_fix.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": footer,
                }]
            })
        elif isinstance(footer, dict):
            blocks_fix.append({
                "type": "context",
                "elements": [footer]
            })
        else:
            raise ValueError(f'invalid footer type: {type(footer)}')
    try:
        post_ts = send_slack_text(text, blocks_fix, event_type=event_type, event_payload=event_payload)
        if remove_past > 0:
            delete_slack_same_titles(event_type, post_ts=post_ts, check_limit=remove_past)

    except slack_sdk.errors.SlackApiError as e:
        print("APIエラー:", e.response["error"])
        raise e
    return post_ts

def select_fcst_00_weather(raw_data: Dict[str,any], select_data: Dict[str,any], area_index: int) -> None:
    area_raw_data = raw_data['areas'][area_index]
    for i, dt_raw in enumerate(raw_data['timeDefines']):
        select_data[dt_raw]['weather']=area_raw_data['weathers'][i]
        select_data[dt_raw]['wind']=area_raw_data['winds'][i]
        select_data[dt_raw]['wave']=area_raw_data['waves'][i]
        select_data[dt_raw]['weather_code']=area_raw_data['weatherCodes'][i]

def select_fcst_01_pop(raw_data: Dict[str,any], select_data: Dict[str,any], area_index: int) -> None: #pop == Probability of Precipitation == Chance of rain
    area_raw_data = raw_data['areas'][area_index]
    for i, dt_raw in enumerate(raw_data['timeDefines']):
        select_data[dt_raw]['pop']=area_raw_data['pops'][i]

def select_fcst_02_temperature(raw_data: Dict[str,any], select_data: Dict[str,any], area_index: int) -> None:
    area_raw_data = raw_data['areas'][area_index]
    for i, dt_raw in enumerate(raw_data['timeDefines']):
        select_data[dt_raw]['temperature_minmax'] = area_raw_data['temps'][i] # 0時が「朝の最低気温」、9時が「日中の最高気温」で固定されているように見える。おそらく9時以降の発表では0時にも最高気温が入ってるっぽい TODO 仕様書。。。

def select_vpfd_area(raw_data: Dict[str,any], select_data: Dict[str,any]) -> None:
    for i, dt_json_raw in enumerate(raw_data['timeDefines']):
        dt_raw = dt_json_raw['dateTime']
        select_data[dt_raw]['weather'] = raw_data['weather'][i]
        select_data[dt_raw]['wind'] = raw_data['wind'][i]

def select_vpfd_point(raw_data: Dict[str,any], select_data: Dict[str,any]) -> None:
    for i, dt_json_raw in enumerate(raw_data['timeDefines'][:-1]): # 最後の要素は無視(areaは時間レンジの予報、pointは時刻瞬間の予報なので、pointが一つ多い。24時間以上の瞬間の気温をそこまで知りたいことはないので)
        dt_raw = dt_json_raw['dateTime']
        select_data[dt_raw]['temperature'] = raw_data['temperature'][i]
        select_data[dt_raw]['temperature_max'] = raw_data['maxTemperature'][i]
        select_data[dt_raw]['temperature_min'] = raw_data['minTemperature'][i]

def format_fcst(select_data:Dict[str,any]) -> List[str]:
    texts: List[str] = []
    text_translator = str.maketrans(f'０１２３４５６７８９．{SP_ZEN}',f'0123456789.{SP_NRM}','')
    for dt_raw in sorted(select_data.keys()):
        dt = parse_dt_str(dt_raw)
        forecast_weather: str =select_data[dt_raw]['weather'].translate(text_translator)
        forecast_wind:str = select_data[dt_raw]['wind'].translate(text_translator)
        forecast_wave:str = select_data[dt_raw]['wave'].translate(text_translator)
        weather_code:str = select_data[dt_raw]['weather_code']

        texts.append(
            f'{dt.month}月{dt.day}日'
            f'\n{SP}{forecast_weather}'
            f'\n{SP}{forecast_wind}'
            f'\n{SP}波{SP}{forecast_wave}'
            f'\n{SP}code:{SP}{weather_code}'
        )
    return texts

def format_vpfd(select_data:Dict[str,any]) -> List[str]:
    texts: List[str] = []

    temperature_num_digits=max([len(f'{_x.get('temperature',0):d}') for _x in select_data.values()])
    wind_speed_num_digits=max([len(f'{_x.get('wind',{}).get('speed',0):d}') for _x in select_data.values()])
    wind_direction_num_digits=max([len(_x.get('wind',{}).get('direction','')) for _x in select_data.values()])

    last_d: int = None
    last_pop: str = None
    for dt_raw in sorted(select_data.keys()):
        dt = parse_dt_str(dt_raw)
        d_slack=f'{dt.day:{SP}>2d}日'
        t_slack=f'{dt.hour:{SP}>2d}時'
        if dt.day==last_d:
            d_slack=f'{SP*2}{SP_ZEN}'

        pop_raw: str = select_data[dt_raw].get('pop')
        if pop_raw is not None:
            pop_slack: str = f'{pop_raw:{SP}>3}%'
            last_pop = pop_raw
        elif last_pop is not None and dt.day == last_d: #降水確率が欠損の場合、同日内に限り直前と同じ値を採用(地域時系列天気は3時間単位だが、府県天気予報報由来の降水確率は6時間単位のため)。厳密にいうと時間内に降る確率であれば時間が長いほど高くなるはずだが、基本的に高いところに合わせて傘を持ち出すことしかできないので、値は入れた方がよさそう。
            pop_slack: str = f'{last_pop:{SP}>3}%'
            # pop_slack: str = f'{SP*4}'
        else:
            pop_slack: str = f'{SP*4}'
        weather_raw=select_data[dt_raw].get('weather')
        match weather_raw:
            case None:
                continue
                # 天気がないなら何も出さない(行を無視)。0時のtemperature_minmaxのデータのキーに起因して発生。
            case '晴れ':
                if 6 <= dt.hour < 18:
                    weather_icon_slack=icon_sunny_day
                else:
                    weather_icon_slack=icon_sunny_night
            case 'くもり':
                weather_icon_slack=icon_cloudy
            case '雨':
                weather_icon_slack=icon_rainy
            case '雪':
                weather_icon_slack=icon_snowy
            case '雨または雪': #民間予報ではみぞれ https://www.jma.go.jp/jma/kishou/know/yougo_hp/kousui.html によると予報文では「雨か雪」「雪か雨」と表現するが地域時系列予報では「雨または雪」固定
                weather_icon_slack=icon_sleety
        temperature_minmax_raw: str = select_data[dt_raw].get('temperature_minmax')
        if temperature_minmax_raw is not None:
            temperature_minmax_slack: str = f'{temperature_minmax_raw:{SP}>3}°C'
        else:
            temperature_minmax_slack: str = f'{SP*6}'
        temperature_raw=select_data[dt_raw]['temperature']
        temperature_slack=f'{temperature_raw:{SP}>{temperature_num_digits}}°C'
        wind_raw=select_data[dt_raw]['wind']
        wind_direction_sp=wind_direction_num_digits-len(wind_raw["direction"])
        wind_slack=f'{SP*wind_direction_sp}{wind_raw["direction"]}{SP*wind_direction_sp}{SP}{wind_raw["speed"]:{wind_speed_num_digits}.0f}m'# TODO 方角なしあるのかな(無風)→来た情報無加工で入れてるだけなので無問題 ＃TODO 北 10mと 北西 1mがあったときに無駄にSP*2となる問題(10m超えはレアなので放置)
        texts.append(
            f'{d_slack}{SP}{t_slack}'
            f'{SP}{weather_icon_slack}'
            f'{pop_slack}'
            f'{SP}{temperature_slack}'
            f'{SP}{wind_slack}'
            # f'{SP}{temperature_minmax_slack}'
        )

        last_d = dt.day
        if pop_raw is not None:
            last_pop = pop_raw
    return texts

def check_vpfd_update(past_messages:List[Dict[str,any]], vpfd_rep_dt:datetime.datetime , fcst_rep_dt: datetime.datetime)-> bool:
    vpfd_past_max_time=fcst_past_max_time=datetime.datetime.min.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    for past_msg in past_messages:
        # print(past_msg)
        if past_msg['user']!=slack_bot_user_id:
            # print('continue by user')
            continue
        if past_msg.get('metadata',{}).get('event_type') != slack_meta_event_type_fcst:
            # print('continue by event')
            continue
        vpfd_past_time=past_msg.get('metadata',{}).get('event_payload',{}).get('vpfd_reportDatetime')
        fcst_past_time=past_msg.get('metadata',{}).get('event_payload',{}).get('fcst_reportDatetime')
        if vpfd_past_time is None:
            # print('continue by vpfd null')
            continue
        if fcst_past_time is None:
            # print('continue by fcst null')
            continue
        chk_vpfd=parse_dt_str(vpfd_past_time)
        chk_fcst=parse_dt_str(fcst_past_time)
        if chk_vpfd>=vpfd_past_max_time and chk_fcst>=fcst_past_max_time:
            vpfd_past_max_time=chk_vpfd
            fcst_past_max_time=chk_fcst
    return (vpfd_rep_dt>vpfd_past_max_time) or (fcst_rep_dt>fcst_past_max_time)

def proc_main(fcst_json:Dict[str,any], vpfd_json:Dict[str,any])->None:

    fcst_pub_office_raw: str = fcst_json[0]['publishingOffice']
    fcst_rep_dt_raw: str = fcst_json[0]['reportDatetime']
    fcst_rep_dt = parse_dt_str(fcst_rep_dt_raw)
    for i, _area_raw_data in enumerate(fcst_json[0]['timeSeries'][0]['areas']):
        if _area_raw_data['area']['code'] == area_class10_cd:
            fcst_area_index=i # 気温(観測所単位)はエリアと紐づきが定義されていないため、jsonの配列のインデックスで特定する
            break
        else:
            raise ValueError(f'area {area_class10_cd} not found.')
    
    vpfd_pub_office_raw=vpfd_json['publishingOffice']
    vpfd_rep_dt_raw=vpfd_json['reportDateTime']
    vpfd_rep_dt=parse_dt_str(vpfd_rep_dt_raw)

    if not check_vpfd_update(slack_past_msgs, vpfd_rep_dt, fcst_rep_dt):
        return #データ更新なし


    fcst_select_data=defaultdict(dict)
    vpfd_select_data=defaultdict(dict)

    select_fcst_00_weather(fcst_json[0]['timeSeries'][0], fcst_select_data, fcst_area_index)
    select_fcst_01_pop(fcst_json[0]['timeSeries'][1], vpfd_select_data, fcst_area_index)
    select_fcst_02_temperature(fcst_json[0]['timeSeries'][2], vpfd_select_data, fcst_area_index)

    vpfd_info_type=vpfd_json['infoType']
    vpfd_announce_dt_slack=f'{vpfd_pub_office_raw} {vpfd_rep_dt.month}月{vpfd_rep_dt.day}日{vpfd_rep_dt.hour}時 {vpfd_info_type}'
    vpfd_area_nm_raw=vpfd_json['pointTimeSeries']['pointNameJP'] # TODOこれはエリア名ではなく気温？ポイント名
    vpfd_area_nm_slack=f'{area_office_nm}{SP}{area_class10_nm}({vpfd_area_nm_raw})'

    select_vpfd_area(vpfd_json['areaTimeSeries'], vpfd_select_data)
    select_vpfd_point(vpfd_json['pointTimeSeries'], vpfd_select_data)

    fcst_texts= format_fcst(fcst_select_data)
    fcst_slack= '\n'.join(fcst_texts)
    # send_slack(fcst_slack, title='天気予報:', remove_same_title=True)

    vpfd_texts = [f'{vpfd_area_nm_slack}{SP}-{SP}{vpfd_announce_dt_slack}']
    vpfd_texts.extend(format_vpfd(vpfd_select_data))
    vpfd_slack = '\n'.join(vpfd_texts)
    vpfd_footer_slack={
        "type": "mrkdwn",
        "text": f'source: <{vpfd_link_url} | {vpfd_link_text} >',
    }
    vpfd_meta={
        'fcst_reportDatetime':fcst_rep_dt_raw,
        'vpfd_reportDatetime':vpfd_rep_dt_raw,
    }
    # send_slack_deplecated(vpfd_slack, header='時系列天気:', remove_same_title=True, post_type=slack_meta_event_type_fcst)
    send_slack(vpfd_slack, header='時系列天気', footer=vpfd_footer_slack, remove_past=10, event_type=slack_meta_event_type_fcst, event_payload=vpfd_meta)

dotenv.load_dotenv()

slack_token = os.environ['SLACK_TOKEN']
slack_ch_nm = os.environ['SLACK_CH_NM']
slack_cli = None
slack_bot_user_id = None
slack_ch_id = None

slack_meta_event_type_fcst = 'fjworks_weatherinfo'
slack_meta_event_type_nowc = 'fjworks_nowcast_rain'


area_class10_cd = os.environ['JMA_AREA_CD'] # TOKYO 130010
area_url = 'https://www.jma.go.jp/bosai/common/const/area.json'
fcst_url_format = 'https://www.jma.go.jp/bosai/forecast/data/forecast/{area_office_cd}.json'
vpfd_url_format = 'https://www.jma.go.jp/bosai/jmatile/data/wdist/VPFD/{area_class10_cd}.json'
vpfd_link_url = 'https://www.jma.go.jp/bosai/map.html'
vpfd_link_text = '気象庁 天気予報'

icon_sunny_day = os.environ['ICON_SUNNY_DAY']
icon_sunny_night = os.environ['ICON_SUNNY_NIGHT']
icon_cloudy = os.environ['ICON_CLOUDY']
icon_rainy = os.environ['ICON_RAINY']
icon_snowy = os.environ['ICON_SNOWY']
icon_sleety = os.environ['ICON_SLEETY']


map_zoom=int(os.environ['NOWCAST_RAIN_ZOOM'])
map_c_lat=float(os.environ['NOWCAST_RAIN_LAT'])
map_c_lng=float(os.environ['NOWCAST_RAIN_LNG'])
map_radar_meters=float(os.environ['NOWCAST_RAIN_RADAR_RANGE'])
map_coming_meters=float(os.environ['NOWCAST_RAIN_COMING_RANGE'])
map_detect_meters=float(os.environ['NOWCAST_RAIN_DETECT_RANGE'])

def latlng_to_tile_pixel(lat, lng, zoom):
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = (lng + 180.0) / 360.0
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0

    tile_x = int(x * n)
    tile_y = int(y * n)
    pixel_x = int((x * n * 256) % 256)
    pixel_y = int((y * n * 256) % 256)

    return tile_x, tile_y, pixel_x, pixel_y

def meters_per_pixel(lat, zoom):
    return (156543.03392 * math.cos(math.radians(lat))) / (2 ** zoom)


map_c_tile_x, map_c_tile_y, map_c_pxl_x, map_c_pxl_y = latlng_to_tile_pixel(map_c_lat, map_c_lng, map_zoom)
mpp=meters_per_pixel(map_c_lat,map_zoom)
map_radar_pxls=int(math.ceil(map_radar_meters/mpp))
map_coming_pxls=int(math.ceil(map_coming_meters/mpp))
map_detect_pxls=int(math.ceil(map_detect_meters/mpp))

pprint(
    f'{map_zoom=}\n'
    f'{map_c_tile_x=}\n'
    f'{map_c_tile_y=}\n'
    f'{map_c_pxl_x=}\n'
    f'{map_c_pxl_y=}\n'
    f'{map_radar_pxls=}\n'
    f'{map_coming_pxls=}\n'
    f'{map_detect_pxls=}\n'
)

prepare_slack()
slack_past_msgs_ts=f'{datetime.datetime.now(datetime.timezone.utc).timestamp() - 24 * 60 * 60: .6f}'
# print('past' , past_msgs_ts)
past_msgs_resp=slack_cli.conversations_history(
    channel=slack_ch_id,
    include_all_metadata=True,
    inclusive=True,
    limit=999, #ページングしない最大は999らしい?
    oldest=slack_past_msgs_ts,
)
slack_past_msgs=past_msgs_resp['messages']

area_json = load_json(area_url)

area_class10_json = area_json['class10s'][area_class10_cd]
area_class10_nm = area_class10_json['name']
area_office_cd = area_class10_json['parent']
area_office_json = area_json['offices'][area_office_cd]
area_office_nm= area_office_json['name']

fcst_url = fcst_url_format.format(area_office_cd=area_office_cd)
fcst_json = load_json(fcst_url)

vpfd_url = vpfd_url_format.format(area_class10_cd=area_class10_cd)
vpfd_json = load_json(vpfd_url)

proc_main(fcst_json, vpfd_json)


from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import math

out_img_size_x=map_radar_pxls*2
out_img_size_y=map_radar_pxls*2

map_zoom = map_zoom
if map_zoom>14:
    raise ValueError('Zoomレベルは4から14の間で指定してください')
if map_zoom>=10:
    rain_zoom=10
elif map_zoom>=8:
    rain_zoom=8
elif map_zoom>=6:
    rain_zoom=6
elif map_zoom>=4:
    rain_zoom=4
else :
    raise ValueError('Zoomレベルは4から14の間で指定してください')
zoom_diff = map_zoom - rain_zoom


nowc_json = load_json('https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json')
nowc_basetime = max(
    nowc_json, 
    key=lambda x: int(x['basetime'])
)['basetime']
nowc_validtime = max(
    filter(lambda x: x['basetime']==nowc_basetime, nowc_json)
)['validtime']


nowc_past_max_time=-1
for past_msg in slack_past_msgs:
    if past_msg['user']!=slack_bot_user_id:
        # print('continue by user')
        continue
    if past_msg.get('metadata',{}).get('event_type') != slack_meta_event_type_nowc:
        # print('continue by event')
        continue
    nowc_past_msg_base_time=past_msg.get('metadata',{}).get('event_payload',{}).get('basetime')
    nowc_past_msg_valid_time=past_msg.get('metadata',{}).get('event_payload',{}).get('validtime')
    if nowc_past_msg_base_time is None:
        # print('continue by base null')
        continue
    if nowc_past_msg_valid_time is None:
        # print('continue by valid null')
        continue
    if nowc_past_msg_base_time!=nowc_past_msg_valid_time:
        # print('continue by time diff')
        continue
    nowc_past_max_time=max(nowc_past_max_time, int(nowc_past_msg_base_time)) if nowc_past_max_time is not None else int(nowc_past_msg_base_time)
if nowc_past_max_time >= int(nowc_validtime):
    exit()

def load_image_url(url):
    print(url)
    resp_img = requests.get(url)
    print(f'{resp_img.status_code} {resp_img.reason}')
    resp_img.raise_for_status()
    return Image.open(BytesIO(resp_img.content))

def load_base_image_one(lvl: int, tilex: int, tiley: int) -> Image:
    url=f'https://www.jma.go.jp/tile/gsi/pale/{lvl}/{tilex}/{tiley}.png'
    return load_image_url(url)

def load_rain_image_one(lvl: int, tilex: int, tiley: int, basetime: str, validtime: str) -> Image:
    url=f'https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/{lvl}/{tilex}/{tiley}.png'
    return load_image_url(url)

map_c_tile=load_base_image_one(map_zoom,map_c_tile_x,map_c_tile_y)
tile_w=map_c_tile.width
tile_h=map_c_tile.height

map_pxl_x = tile_w * map_c_tile_x + map_c_pxl_x
map_pxl_xmin = map_pxl_x-map_radar_pxls
map_pxl_xmax = map_pxl_x+map_radar_pxls
map_pxl_y = tile_h * map_c_tile_y + map_c_pxl_y
map_pxl_ymin = map_pxl_y-map_radar_pxls
map_pxl_ymax = map_pxl_y+map_radar_pxls
map_pxl_w = map_pxl_xmax - map_pxl_xmin
map_pxl_h = map_pxl_ymax - map_pxl_ymin

rain_pxl_x = map_pxl_x // (2 ** zoom_diff)
rain_pxl_xmin = rain_pxl_x - map_radar_pxls // (2 ** zoom_diff)
rain_pxl_xmax = rain_pxl_x + map_radar_pxls // (2 ** zoom_diff)
rain_pxl_y = map_pxl_y // (2 ** zoom_diff)
rain_pxl_ymin = rain_pxl_y - map_radar_pxls // (2 ** zoom_diff)
rain_pxl_ymax = rain_pxl_y + map_radar_pxls // (2 ** zoom_diff)
rain_pxl_w = rain_pxl_xmax - rain_pxl_xmin
rain_pxl_h = rain_pxl_ymax - rain_pxl_ymin

map_tile_xmin = map_pxl_xmin // tile_w
map_tile_xmax = map_pxl_xmax // tile_w
map_tile_ymin = map_pxl_ymin // tile_h
map_tile_ymax = map_pxl_ymax // tile_h

map_load_pxl_xmin = map_tile_xmin * tile_w
map_load_pxl_xmax = (map_tile_xmax + 1) * tile_w
map_load_pxl_ymin = map_tile_ymin * tile_h
map_load_pxl_ymax = (map_tile_ymax + 1) * tile_h

map_w = map_load_pxl_xmax - map_load_pxl_xmin
map_h = map_load_pxl_ymax - map_load_pxl_ymin
print((map_w, map_h))
map_img: Image = Image.new('RGBA', (map_w, map_h))

for ty in range(map_tile_ymin, map_tile_ymax + 1): 
    for tx in range(map_tile_xmin, map_tile_xmax + 1):
        # if tx == nowc_rain_tile_x and ty == nowc_rain_tile_y:
        #     img_load = map_c_tile
        # else:
        map_load = load_base_image_one(map_zoom, tx, ty)
        if _DEBUG_ADDRESS_:
            draw=ImageDraw.Draw(map_load)
            draw.rectangle([(0,0),(map_load.width-1,map_load.height-1)],outline='black',width=1)
            draw.text((10,10), f'x={tx}, y={ty}',fill='black')
            if tx==map_c_tile_x and ty==map_c_tile_y:
                draw.line((0,0,map_load.width-1,map_load.height-1), fill='black', width=1)
                draw.line((0,map_load.width-1,map_load.height-1,0), fill='black', width=1)
        if _DEBUG_STORE_IMG_:
            map_load.save(f'./map_load_{map_zoom}_{tx}_{ty}.png')
        px = (tx - map_tile_xmin) * tile_w
        py = (ty - map_tile_ymin) * tile_h
        print((px,py))
        map_img.paste(map_load.convert('RGBA'), (px, py))
if _DEBUG_ADDRESS_:
    draw=ImageDraw.Draw(map_img)
    draw.ellipse(
        (
            map_pxl_xmin - map_load_pxl_xmin,
            map_pxl_ymin - map_load_pxl_ymin,
            map_pxl_xmax - map_load_pxl_xmin,
            map_pxl_ymax - map_load_pxl_ymin,
        ),
        outline='red', width=1
    )

map_crop = map_img.crop((
    map_pxl_xmin - map_load_pxl_xmin,
    map_pxl_ymin - map_load_pxl_ymin,
    map_pxl_xmax - map_load_pxl_xmin,
    map_pxl_ymax - map_load_pxl_ymin,
 ))

if _DEBUG_STORE_IMG_:
    map_load.save('./map_load.png')
    map_img.save('./map_img.png')
    map_crop.save('./map_crop.png')

rain_tile_xmin = map_tile_xmin // (2 ** zoom_diff)
rain_tile_xmax = map_tile_xmax // (2 ** zoom_diff)
rain_tile_ymin = map_tile_ymin // (2 ** zoom_diff)
rain_tile_ymax = map_tile_ymax // (2 ** zoom_diff)

rain_load_pxl_xmin = rain_tile_xmin * tile_w
rain_load_pxl_xmax = (rain_tile_xmax + 1) * tile_w
rain_load_pxl_ymin = rain_tile_ymin * tile_h
rain_load_pxl_ymax = (rain_tile_ymax + 1) * tile_h

rain_w = rain_load_pxl_xmax - rain_load_pxl_xmin
rain_h = rain_load_pxl_ymax - rain_load_pxl_ymin
print((rain_w, rain_h))

rain_img: Image = Image.new('RGBA', (rain_w, rain_h))

for ty in range(rain_tile_ymin, rain_tile_ymax + 1): 
    for tx in range(rain_tile_xmin, rain_tile_xmax + 1):
        # rain_load = load_base_image_one(rain_zoom, tx, ty)
        rain_load=load_rain_image_one(rain_zoom,tx,ty,nowc_basetime, nowc_basetime)
        if _DEBUG_ADDRESS_:
            draw=ImageDraw.Draw(rain_load)
            draw.rectangle([(0,0),(rain_load.width-1,rain_load.height-1)],outline='blue',width=1)
            draw.text((10,10), f'x={tx}, y={ty}',fill='blue')
        if _DEBUG_STORE_IMG_:
            rain_load.save(f'./rain_load_{rain_zoom}_{tx}_{ty}.png')
        px = (tx - rain_tile_xmin) * tile_w 
        py = (ty - rain_tile_ymin) * tile_h
        print((px,py))
        rain_img.paste(rain_load.convert('RGBA'), (px, py))

rain_crop = rain_img.crop((
    rain_pxl_xmin - rain_load_pxl_xmin,
    rain_pxl_ymin - rain_load_pxl_ymin,
    rain_pxl_xmax - rain_load_pxl_xmin,
    rain_pxl_ymax - rain_load_pxl_ymin,
))
rain_resize = rain_crop.resize((map_crop.width, map_crop.height), Image.Resampling.BOX)
rain_composite = Image.composite(
    rain_resize, map_crop,
    Image.eval(rain_resize.getchannel('A'), lambda a: 0xCC if a > 0 else 0x33)
)
if _DEBUG_STORE_IMG_:
    rain_load.save('./rain_load.png')
    rain_img.save('./rain_img.png')
    rain_crop.save('./rain_crop.png')
    rain_resize.save('./rain_resize.png')
    rain_composite.save('./rain_composite.png')


wh=rain_crop.width // 2
hh=rain_crop.height // 2
rain_radar_pxls=map_radar_pxls//(2**zoom_diff)
rain_coming_pxls=map_coming_pxls//(2**zoom_diff)
rain_detect_pxls=map_detect_pxls//(2**zoom_diff)
print(wh,hh)
print(map_radar_pxls)
# memo
# L0   0mm 255,255,255,  0    0,  0,100 白（ただし透明） ←HSV　色相 彩度 明度
# L1 ~ 5mm 242,242,255,255  240,  5,100 限りなく白に近い水色
# L2 ~10mm 160,210,255,255  208, 37,100 薄い水色
# L3 ~20mm  33,140,255,255  211, 87,100 ほぼ青(濃い水色)
# L4 ~30mm 250,245,  0,255  き
# L5 ~50mm 255,153,  0,255 だいだい
# L6 ~80mm 255, 40,  0,255 あか
# L7 ~xxmm 180,  0,104,255 あずき
level_by_color={
    (255,255,255,  0):0,
    (242,242,255,255):1,
    (160,210,255,255):2,
    ( 33,140,255,255):3,
    (  0, 65,255,255):4,
    (250,245,  0,255):5,
    (255,153,  0,255):6,
    (255, 40,  0,255):7,
    (180,  0,104,255):8, #あずき
}
amount_by_level={
    1:'1mm/h未満',
    2:'1-5mm/h',
    3:'5-10mm/h',
    4:'10-20mm/h',
    5:'20-30mm/h',
    6:'30-50mm/h',
    7:'50-80mm/h',
    8:'80mm/h以上',
}
heavy_pos=None
heavy_dst=float('inf')
heavy_lvl=-1

near_pos=None
near_dst=float('inf')
near_lvl=-1

zzzz:Dict[any,any]=dict()
img_chart=Image.new("RGBA",rain_crop.size)
pxls=rain_crop.load()
pxlsw=img_chart.load()
for ty in range(0, wh):
    for tx in range(0, hh):
        l=math.hypot(tx,ty)
        if l > rain_coming_pxls and l > rain_detect_pxls:
            continue
        for yyy in [1,-1]: 
            if ty==0 and yyy==-1:
                continue
            for xxx in [1,-1]:
                if tx==0 and xxx==-1:
                    continue
                c=pxls[wh+tx*xxx,hh+ty*yyy]
                pc=level_by_color.get(c,-1)
                ccc=zzzz.get(c)
                if ccc is not None:
                    zzzz[c]=(ccc[0]+1, ccc[1], pc)
                else:
                    zzzz[c]=(1, len(zzzz)+1, pc)
                if pc>=0:
                    pxlsw[wh+tx*xxx,hh+ty*yyy]=(32*pc-1,32*pc-1,32*pc-1,255)
                else:
                    pxlsw[wh+tx*xxx,hh+ty*yyy]=(255,0,0,255)
                if pc > 0 and pc > heavy_lvl or (pc == heavy_lvl and l < heavy_dst):
                    heavy_pos=(wh+tx*xxx,hh+ty*yyy)
                    heavy_dst=l
                    heavy_lvl=pc
                if pc > 0 and l < near_dst or (l == near_dst and pc > near_lvl):
                    near_pos=(wh+tx*xxx,hh+ty*yyy)
                    near_dst=l
                    near_lvl=pc

if near_lvl>0:
    near_dst_meters=near_dst*mpp
    heavy_dst_meters=heavy_dst*mpp
    if near_dst <= rain_detect_pxls:
        print( f'{amount_by_level[near_lvl]}[レベル{near_lvl}]の降水中です')
        if near_lvl<heavy_lvl:
            print( f'距離{heavy_dst_meters/1000:.1f}kmに{amount_by_level[heavy_lvl]}[レベル{heavy_lvl}]の降水があります')
    elif near_dst <= rain_coming_pxls:
        print( f'距離{near_dst_meters/1000:.1f}kmに{amount_by_level[near_lvl]}[レベル{near_lvl}]の降水があります')
        if near_lvl<heavy_lvl:
            print( f'距離{heavy_dst_meters/1000:.1f}kmに{amount_by_level[heavy_lvl]}[レベル{heavy_lvl}]の降水があります')

dt_valid_utc=datetime.datetime.strptime(nowc_validtime, '%Y%m%d%H%M%S').replace(tzinfo=datetime.timezone.utc)
dt_valid_jst=dt_valid_utc.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
dt_valid_jst_slack=dt_valid_jst.strftime("%Y/%m/%d %H:%M")
dt_valid_jst_slack_fname=dt_valid_jst.strftime("%Y%m%d_%H%M")

img_mimetype_out='image/png'
upload_fname=f'nowcast_rain_{dt_valid_jst_slack_fname}.png'

buf_img_up=BytesIO()
img_up=rain_composite.save(buf_img_up, format='PNG')
buf_img_up.seek(0)
bytes_img_up=buf_img_up.read()

prepare_slack()

uploaded_files=send_slack_images(
    [bytes_img_up],
    [upload_fname],
    [img_mimetype_out],
    ['雨雲レーダー'],
    ['降雨エリア・強さが示されている地図画像'],
)
slack_blocks:List[Dict[str,any]] = list()
# slack_blocks.append({
#     "type": "section",
#     "text": {
#         "type": "plain_text",
#         "text": dt_valid_jst_slack,
#         "emoji": True
#     }
# })

def get_8_direction(origin_x, origin_y, target_x, target_y):
    dx = target_x - origin_x
    dy = -(target_y - origin_y) #座標軸が南が正のため
    angle_rad = math.atan2(dy, dx)
    angle_deg = (math.degrees(angle_rad) + 360) % 360
    directions = ['東', '北東', '北', '北西', '西', '南西', '南', '南東']
    index = int(((angle_deg + 22.5) % 360) // 45)
    return directions[index]

if near_lvl>0:
    near_dst_meters=near_dst*mpp * (2 ** zoom_diff)
    heavy_dst_meters=heavy_dst*mpp* (2 ** zoom_diff)
    near_dir=get_8_direction(wh, hh, near_pos[0], near_pos[1])
    heavy_dir=get_8_direction(wh, hh, heavy_pos[0], heavy_pos[1])
    
    rainy_strs:List[str] = list()
    if near_dst <= rain_detect_pxls:
        rainy_strs.append(f'付近は{amount_by_level[near_lvl]}の降水')
        if near_lvl<heavy_lvl:
            rainy_strs.append( f'{heavy_dir} {heavy_dst_meters/1000:.1f}kmに{amount_by_level[heavy_lvl]}の降水')
    elif near_dst <= rain_coming_pxls:
        rainy_strs.append(f'{near_dir} {near_dst_meters/1000:.1f}kmに{amount_by_level[near_lvl]}の降水')
        if near_lvl<heavy_lvl:
            rainy_strs.append( f'{heavy_dir} {heavy_dst_meters/1000:.1f}kmに最大{amount_by_level[heavy_lvl]}の降水')
    if len(rainy_strs)>0:
        slack_blocks.append({
            "type": "section",
            "text": {
                "type": "plain_text",
                "text": '\n'.join(rainy_strs),
                "emoji": True
            }
        })
        
slack_blocks.extend([{
    "type": "image",
    "slack_file": {'id': fid},
    "alt_text":'雨雲レーダー',
} for (fid, furl) in uploaded_files])
slack_header=None
slack_footer={
    "type": "mrkdwn",
    "text": f'source: <https://www.jma.go.jp/bosai/nowc/ | 気象庁ナウキャスト > *{dt_valid_jst_slack}*',
}
slack_text=dt_valid_jst_slack
slack_meta={
    'basetime':f'{nowc_basetime}',
    'validtime':f'{nowc_validtime}',
}
import time
for fid, furl in uploaded_files:
    waittime=2.5
    while True:
        # print(fid,furl)
        resp_fs=slack_cli.files_info(file=fid)
        if 'original_w' in resp_fs['file'] and 'original_h' in resp_fs['file']: #非同期アップロードが完了した時に設定されると思われる属性ができるまで待つ
            break
        time.sleep(waittime)
        # waittime=waittime*2
post_ts=send_slack(slack_text, slack_blocks, slack_header, slack_footer, slack_meta_event_type_nowc, slack_meta, 10)
