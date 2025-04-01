import os
import json

from typing import List, Tuple, Dict, Set
from pprint import pprint
from collections import defaultdict

import requests
import datetime
import dotenv
import slack_sdk

_DEBUG_ADDRESS_=False

# SP=chr(0x2002) # 1/2em幅のスペース
SP=chr(0x2007) # 固定幅フォントの数字と同じ幅のスペース
SP_ZEN=chr(0x3000) # 「全角」のスペース
# SP_ZEN=chr(0x2003) # 1em幅のスペース
SP_NRM=chr(0x0020) # 「通常」のスペース

def load_json(url:str)->any:
    resp = requests.get(url)
    print(url)
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

def send_slack_text(message: str) -> float:
    resp_p = slack_cli.chat_postMessage(
        channel=slack_ch_id,
        text=message
    )
    post_ts=resp_p["ts"]
    print(f'送信成功: {post_ts}')
    return post_ts

def send_slack_images(
        files:List[bytes] = None,
        file_names:List[str] = None,
        file_mimetypes:List[str] = None,
        file_titles:List[str] = None,
        file_alts:List[str] = None,
        message: str = None, 
    ) -> str:
        slack_up_files:List[any]=list()
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

        print(f'to chhannel {slack_ch_id}')
        resp_compl = slack_cli.files_completeUploadExternal(
            files = slack_up_files,
            channel_id = slack_ch_id,
            initial_comment = message
        )
        print(resp_compl)
        return slack_up_files[-1]['id']

def delete_slack_same_titles(title: str, post_ts: float, post_file_id: str, check_limit:int = 10):
    if title is None:
        return
    title_slack=f'*{title}*'
    resp_h = slack_cli.conversations_history(
        channel=slack_ch_id,
        limit=check_limit, # 直近N件以内に同じタイトルがあれば削除
    ) #TODO post_tsがあるばあい、それをlatestとして指定する
    past_messages = resp_h["messages"]

    for past_msg in past_messages:
        print(past_msg)
        past_text = past_msg.get("text", "")
        past_user = past_msg.get("user", "system/unknown")
        past_ts = past_msg.get("ts")
        # print(f"{i}. ユーザー: {user}, 時間: {ts}, メッセージ: {text}")

        #消さない条件
        if past_user != slack_bot_user_id: #ユーザーが異なる
            continue
        if not past_text.startswith(title_slack): #1行目(タイトル)が異なる
            continue
        if post_ts is not None and past_ts >= post_ts: #tsが指定されていて、それと同じか新しい
            continue
        if post_file_id is not None and post_file_id in [f['id'] for f in past_msg.get('files',[])]: #filesが指定されていて、それが含まれる
            continue
        #ここに到達したら削除対象
        #ユーザーが同一
        #一行目(タイトル)が一致
        #TSがあった場合、それより古い
        #FILESがあった場合、含まない


        resp_d = slack_cli.chat_delete(
            channel=slack_ch_id,
            ts=past_ts
        )
        if resp_d["ok"]:
            print(f'メッセージ削除成功: {past_ts}')
        else:
            print(f'メッセージ削除失敗??: {past_ts}')


def send_slack(
        message:str,
        title:str = None,
        files:List[bytes] = None,
        file_names:List[str] = None,
        file_mimetypes:List[str] = None,
        file_titles:List[str] = None,
        file_alts:List[str] = None,
        remove_same_title: bool = False,
    )->None:
    prepare_slack()
    if title is not None:
        message_slack=f'*{title}*\n{message}'
    else:
        message_slack=f'{message}'
    try:
        if files is None:
            post_ts = send_slack_text(message_slack)
            file_id = None
        else:
            file_id = send_slack_images(files, file_names, file_mimetypes, file_titles, file_alts, message_slack)
            post_ts = None
        if remove_same_title and title is not None:
            delete_slack_same_titles(title, post_ts, file_id)

    except slack_sdk.SlackApiError as e:
        print("APIエラー:", e.response["error"])
        raise e

def select_fcst_00_weather(raw_data: any, select_data: any, area_index: int) -> None:
    area_raw_data = raw_data['areas'][area_index]
    for i, dt_raw in enumerate(raw_data['timeDefines']):
        select_data[dt_raw]['weather']=area_raw_data['weathers'][i]
        select_data[dt_raw]['wind']=area_raw_data['winds'][i]
        select_data[dt_raw]['wave']=area_raw_data['waves'][i]
        select_data[dt_raw]['weather_code']=area_raw_data['weatherCodes'][i]

def select_fcst_01_pop(raw_data: any, select_data: any, area_index: int) -> None: #pop == Probability of Precipitation == Chance of rain
    area_raw_data = raw_data['areas'][area_index]
    for i, dt_raw in enumerate(raw_data['timeDefines']):
        select_data[dt_raw]['pop']=area_raw_data['pops'][i]

def select_fcst_02_temperature(raw_data: any, select_data: any, area_index: int) -> None:
    area_raw_data = raw_data['areas'][area_index]
    for i, dt_raw in enumerate(raw_data['timeDefines']):
        select_data[dt_raw]['temperature_minmax'] = area_raw_data['temps'][i] # 0時が「朝の最低気温」、9時が「日中の最高気温」で固定されているように見える。おそらく9時以降の発表では0時にも最高気温が入ってるっぽい TODO 仕様書。。。

def select_vpfd_area(raw_data: any, select_data: any) -> None:
    for i, dt_json_raw in enumerate(raw_data['timeDefines']):
        dt_raw = dt_json_raw['dateTime']
        select_data[dt_raw]['weather'] = raw_data['weather'][i]
        select_data[dt_raw]['wind'] = raw_data['wind'][i]

def select_vpfd_point(raw_data: any, select_data: any) -> None:
    for i, dt_json_raw in enumerate(raw_data['timeDefines'][:-1]): # 最後の要素は無視(areaは時間レンジの予報、pointは時刻瞬間の予報なので、pointが一つ多い。24時間以上の瞬間の気温をそこまで知りたいことはないので)
        dt_raw = dt_json_raw['dateTime']
        select_data[dt_raw]['temperature'] = raw_data['temperature'][i]
        select_data[dt_raw]['temperature_max'] = raw_data['maxTemperature'][i]
        select_data[dt_raw]['temperature_min'] = raw_data['minTemperature'][i]

def format_fcst(select_data:any) -> List[str]:
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

def format_vpfd(select_data:any) -> List[str]:
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

def proc_main(fcst_json:any, vpfd_json:any)->str:
    fcst_pub_office_raw: str = fcst_json[0]['publishingOffice']
    fcst_rep_dt_raw: str = fcst_json[0]['reportDatetime']
    fcst_rep_dt = parse_dt_str(fcst_rep_dt_raw)
    for i, _area_raw_data in enumerate(fcst_json[0]['timeSeries'][0]['areas']):
        if _area_raw_data['area']['code'] == area_class10_cd:
            fcst_area_index=i # 気温(観測所単位)はエリアと紐づきが定義されていないため、jsonの配列のインデックスで特定する
            break
        else:
            raise ValueError(f'area {area_class10_cd} not found.')
    
    fcst_select_data=defaultdict(dict)
    vpfd_select_data=defaultdict(dict)

    select_fcst_00_weather(fcst_json[0]['timeSeries'][0], fcst_select_data, fcst_area_index)
    select_fcst_01_pop(fcst_json[0]['timeSeries'][1], vpfd_select_data, fcst_area_index)
    select_fcst_02_temperature(fcst_json[0]['timeSeries'][2], vpfd_select_data, fcst_area_index)

    vpfd_pub_office_raw=vpfd_json['publishingOffice']
    vpfd_rep_dt_raw=vpfd_json['reportDateTime']
    vpfd_rep_dt=parse_dt_str(vpfd_rep_dt_raw)
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
    vpfd_texts.append(f'from <{vpfd_link_url} | {vpfd_link_text} >')
    vpfd_slack = '\n'.join(vpfd_texts)
    send_slack(vpfd_slack, title='時系列天気:', remove_same_title=True)

dotenv.load_dotenv()

slack_token = os.environ['SLACK_TOKEN']
slack_ch_nm = os.environ['SLACK_CH_NM']
slack_cli = None
slack_bot_user_id = None
slack_ch_id = None

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


nowc_rain_zoom=int(os.environ['NOWCAST_RAIN_ZOOM'])
nowc_rain_tile_x=int(os.environ['NOWCAST_RAIN_TILE_X'])
nowc_rain_tile_y=int(os.environ['NOWCAST_RAIN_TILE_Y'])
nowc_rain_pixel_x=int(os.environ['NOWCAST_RAIN_PIXEL_X'])
nowc_rain_pixel_y=int(os.environ['NOWCAST_RAIN_PIXEL_Y'])
nowc_rain_radar_range=int(os.environ['NOWCAST_RAIN_RADAR_RANGE'])
nowc_rain_coming_range=int(os.environ['NOWCAST_RAIN_COMING_RANGE'])
nowc_rain_detect_range=int(os.environ['NOWCAST_RAIN_DETECT_RANGE'])

if nowc_rain_zoom>14:
    raise ValueError('Zoomレベルは4から14の間で指定してください')
if nowc_rain_zoom>=10:
    zoom_f=10
elif nowc_rain_zoom>=8:
    zoom_f=8
elif nowc_rain_zoom>=6:
    zoom_f=6
elif nowc_rain_zoom>=4:
    zoom_f=4
else :
    raise ValueError('Zoomレベルは4から14の間で指定してください')
zoom_f_diff = nowc_rain_zoom - zoom_f


# area_json = load_json(area_url)

# area_class10_json = area_json['class10s'][area_class10_cd]
# area_class10_nm = area_class10_json['name']
# area_office_cd = area_class10_json['parent']
# area_office_json = area_json['offices'][area_office_cd]
# area_office_nm= area_office_json['name']

# fcst_url = fcst_url_format.format(area_office_cd=area_office_cd)
# fcst_json = load_json(fcst_url)

# vpfd_url = vpfd_url_format.format(area_class10_cd=area_class10_cd)
# vpfd_json = load_json(vpfd_url)

# proc_main(fcst_json, vpfd_json)


from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import math

out_img_size_x=nowc_rain_radar_range*2
out_img_size_y=nowc_rain_radar_range*2

pxl_x_min_raw=nowc_rain_pixel_x-nowc_rain_radar_range
pxl_x_max_raw=nowc_rain_pixel_x+nowc_rain_radar_range
pxl_y_min_raw=nowc_rain_pixel_y-nowc_rain_radar_range
pxl_y_max_raw=nowc_rain_pixel_y+nowc_rain_radar_range

print(pxl_x_min_raw,pxl_y_min_raw,)
print(pxl_x_max_raw,pxl_x_max_raw,)


nowc_json = load_json('https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json')
nowc_basetime = max(
    nowc_json, 
    key=lambda x: int(x['basetime'])
)['basetime']
nowc_validtime = max(
    filter(lambda x: x['basetime']==nowc_basetime, nowc_json)
)['validtime']

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

img_center=load_base_image_one(nowc_rain_zoom,nowc_rain_tile_x,nowc_rain_tile_y)
# img_center=load_rain_image_one(nowc_rain_zoom,nowc_rain_tile_x,nowc_rain_tile_y,'20250331092000', '20250331092000')
img_w=img_center.width
img_h=img_center.height

tile_x_min = math.trunc(math.floor(pxl_x_min_raw/img_w)) + nowc_rain_tile_x
tile_x_max = math.trunc(math.floor(pxl_x_max_raw/img_w)) + nowc_rain_tile_x
tile_y_min = math.trunc(math.floor(pxl_y_min_raw/img_h)) + nowc_rain_tile_y
tile_y_max = math.trunc(math.floor(pxl_y_max_raw/img_h)) + nowc_rain_tile_y

in_img_w=img_w*(tile_x_max-tile_x_min+1)
in_img_h=img_h*(tile_y_max-tile_y_min+1)
img_join: Image = Image.new('RGBA', (in_img_w, in_img_h))
for y in range(tile_y_min, tile_y_max+1): 
    for x in range(tile_x_min, tile_x_max+1):
        if x==nowc_rain_tile_x and y==nowc_rain_tile_y:
            img_load=img_center
        else:
            img_load=load_base_image_one(nowc_rain_zoom,x,y)
        if _DEBUG_ADDRESS_:
            draw=ImageDraw.Draw(img_load)
            draw.rectangle([(0,0),(img_load.width-1,img_load.height-1)],outline='black',width=1)
            draw.text((10,10), f'x={x}, y={y}',fill='black')
            if x==nowc_rain_tile_x and y==nowc_rain_tile_y:
                draw.line((0,0,img_load.width-1,img_load.height-1), fill='black', width=1)
                draw.line((0,img_load.width-1,img_load.height-1,0), fill='black', width=1)
        px=(x-tile_x_min)*img_w
        py=(y-tile_y_min)*img_h
        img_join.paste(img_load.convert('RGBA'),(px,py))
crop_x_min=pxl_x_min_raw-(img_w*(tile_x_min - nowc_rain_tile_x))
crop_x_max=pxl_x_max_raw-(img_w*(tile_x_min - nowc_rain_tile_x))
crop_y_min=pxl_y_min_raw-(img_h*(tile_y_min - nowc_rain_tile_y))
crop_y_max=pxl_y_max_raw-(img_h*(tile_y_min - nowc_rain_tile_y))
if _DEBUG_ADDRESS_:
    draw=ImageDraw.Draw(img_join)
    draw.rectangle([(crop_x_min,crop_y_min),(crop_x_max-1,crop_y_max-1)],outline='blue',width=1)

img_crop = img_join.crop((crop_x_min,crop_y_min,crop_x_max, crop_y_max,))

tile_x_f = nowc_rain_tile_x >> zoom_f_diff
tile_x_min_f = tile_x_min >> zoom_f_diff
tile_x_max_f = tile_x_max >> zoom_f_diff
tile_y_f = nowc_rain_tile_y >> zoom_f_diff
tile_y_min_f = tile_y_min >> zoom_f_diff
tile_y_max_f = tile_y_max >> zoom_f_diff

in_img_w_f=img_w*(tile_x_max_f-tile_x_min_f+1)
in_img_h_f=img_h*(tile_y_max_f-tile_y_min_f+1)
img_join_f: Image = Image.new('RGBA', (in_img_w_f, in_img_h_f))
for y in range(tile_y_min_f, tile_y_max_f+1):
    for x in range(tile_x_min_f, tile_x_max_f+1):
        # print(x,y)
        img_load=load_rain_image_one(zoom_f,x,y,nowc_basetime, nowc_basetime)
        if _DEBUG_ADDRESS_:
            draw=ImageDraw.Draw(img_load)
            draw.rectangle([(0,0),(img_load.width-1,img_load.height-1)],outline='red',width=1)
            draw.text((40,10), f'x={x}, y={y}',fill='black')
        px=(x-tile_x_min_f)*img_w
        py=(y-tile_y_min_f)*img_h
        img_join_f.paste(img_load.convert('RGBA'),(px,py))
img_join_fr = img_join_f.resize((img_join_f.width << zoom_f_diff, img_join_f.height << zoom_f_diff), resample=Image.BOX)

crop_x_min_fr1 = img_w * (tile_x_min - (tile_x_min_f << zoom_f_diff))
crop_y_min_fr1 = img_h * (tile_y_min - (tile_y_min_f << zoom_f_diff))

img_join_fr1 = img_join_fr.crop((crop_x_min_fr1, crop_y_min_fr1, crop_x_min_fr1 + img_join.width, crop_y_min_fr1 + img_join.height,))
img_join_fr2 = img_join_fr1.crop((crop_x_min,crop_y_min,crop_x_max, crop_y_max,))
img_composite = Image.composite(
    img_join_fr2, img_crop,
    Image.eval(img_join_fr2.getchannel('A'), lambda a: 0xCC if a > 0 else 0x33)
)

dt_valid_utc=datetime.datetime.strptime(nowc_validtime, '%Y%m%d%H%M%S').replace(tzinfo=datetime.timezone.utc)
dt_valid_jst=dt_valid_utc.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
dt_valid_jst_slack=dt_valid_jst.strftime("%Y/%m/%d %H:%M")
dt_valid_jst_slack_fname=dt_valid_jst.strftime("%Y%m%d_%H%M")

img_mimetype_out='image/png'
upload_fname=f'nowcast_rain_{dt_valid_jst_slack_fname}.png'

buf_img_up=BytesIO()
img_up=img_composite.save(buf_img_up, format='PNG')
buf_img_up.seek(0)
bytes_img_up=buf_img_up.read()

send_slack(
    dt_valid_jst_slack,
    'ナウキャスト 雨雲レーダー',
    [bytes_img_up],
    [upload_fname],
    [img_mimetype_out],
    ['雨雲レーダー'],
    ['降雨エリア・強さが示されている地図画像'],
    remove_same_title=True,
)
